# 3. KL Custom Parser와 ETLwithLLM 통합 구조

## 3.1 결론부터 보기

이번 농협 내부용 프로그램은 “새 OCR 모델 서버”가 아니다. KL이 호출할 수 있는 Custom Parser API를 제공하고, 실제 OCR/DLA는 농협의 ETLwithLLM API에 위임한 뒤 결과를 KL HRC 규격으로 번역하는 **어댑터이자 오케스트레이터**다.

```text
입력 계약                         내부 분석 계약                    출력 계약

KL Custom Parser 규격             ETLwithLLM API                    KL HRC 규격
src_file + option       ->         원본 + tr_data        ->         *_hrc.jsonl
POST /parsing                       status polling                    *_hrc.json
GET /parsing/result/{uuid}          Default JSON                      *_img.zip
```

핵심 책임은 세 가지다.

1. KL 비동기 API 계약 유지
2. ETLwithLLM 비동기 작업 관리
3. DLA Default JSON을 HRC로 손실 없이 변환

광고 상품군·템플릿·라벨링은 위 세 가지가 작동한 뒤 붙이는 선택적 후처리다.

## 3.2 전체 시퀀스

```text
Knowledge Lake         Custom Parser              ETLwithLLM
      |                       |                         |
      | POST /parsing         |                         |
      | src_file, option      |                         |
      |---------------------->|                         |
      |                       | 원본 임시 저장          |
      |                       | outer UUID 생성         |
      | 202 + UUID + timeout  |                         |
      |<----------------------|                         |
      |                       |                         |
      |                       | POST /etl/auto/start    |
      |                       | tr_data + upfiles       |
      |                       |------------------------>|
      |                       | task_ids, file_paths    |
      |                       |<------------------------|
      |                       |                         |
      | GET /result/{uuid}    |                         |
      |---------------------->|                         |
      | {status:PARSING}      | GET /file/info          |
      |<----------------------|------------------------>|
      |                       | chunk_status            |
      |                       |<------------------------|
      |                       |    ... 반복 ...         |
      |                       |                         |
      |                       | GET /file/result/list   |
      |                       |------------------------>|
      |                       | 결과 파일 경로          |
      |                       |<------------------------|
      |                       | GET /file/result/doc    |
      |                       |------------------------>|
      |                       | Default JSON            |
      |                       |<------------------------|
      |                       |                         |
      |                       | Default JSON 검증        |
      |                       | HRC 변환·후처리          |
      |                       | DONE 기록               |
      |                       |                         |
      | GET /result/{uuid}    |                         |
      |---------------------->|                         |
      | 결과 ZIP             |                         |
      |<----------------------|                         |
```

## 3.3 두 개의 비동기 작업 ID

이 구조에는 작업 ID가 두 종류다.

| 작업 ID | 생성 주체 | 소비 주체 | 용도 |
|---|---|---|---|
| Custom Parser UUID | `main.py` | KL | `/parsing/result/{uuid}` 조회 |
| ETL `task_id`·`file_path` | ETLwithLLM | `parse()` | ETL 상태·결과 조회 |

두 ID를 동일한 값처럼 사용하면 안 된다. Custom Parser 작업 상태에 ETL ID를 연결해 기록할 수는 있지만 외부 계약은 각각 별개다.

```json
{
  "status": "PARSING",
  "phase": "ETL_PROCESSING",
  "etl_task_id": "internal-task-id",
  "etl_file_path": "sample.pdf/v1/sample.pdf",
  "message": ""
}
```

KL에는 기존 계약에 필요한 `PARSING`만 반환하고, 상세 단계는 내부 진단용 상태 파일에 보존할 수 있다.

## 3.4 권장 내부 상태

```text
RECEIVED
  -> ETL_SUBMITTING
  -> ETL_PROCESSING
  -> ETL_RESULT_LOADING
  -> CONVERTING
  -> PACKAGING_READY
  -> DONE

어느 단계에서든 -> ERROR
```

기존 KL 계약의 외부 상태로는 다음처럼 매핑한다.

| 내부 상태 | KL 응답 |
|---|---|
| `RECEIVED`~`PACKAGING_READY` | `{"status":"PARSING"}` |
| `DONE` | ZIP |
| `ERROR` | `{"status":"ERROR","message":"..."}` |

## 3.5 `parse()`의 최종 책임

권장 구조를 개념 코드로 표현하면 다음과 같다.

```python
def parse(work_dir, img_dir, file_path, option=None):
    try:
        write_parse_status(work_dir, "PARSING")

        config = load_runtime_config(option)
        etl = EtlClient(
            base_url=config.etl_base_url,
            credentials=config.credentials,
        )

        request_result = etl.start(
            file_path=file_path,
            author=config.author,
            ws_id=config.ws_id,
            res_type="default",
            prj_config=config.prj_config,
        )

        etl_file_path = request_result.file_paths[0]
        etl.wait_until_done(
            file_path=etl_file_path,
            timeout_seconds=config.etl_timeout,
        )

        default_json = etl.get_default_result(etl_file_path)
        document = convert_default_json(default_json)
        document = apply_optional_ad_postprocess(document, config)

        write_hrc_jsonl(document, work_dir, file_path)
        write_hrc_info(document, work_dir, file_path)
        write_images(document, img_dir)
        validate_outputs(work_dir, img_dir, file_path)

        write_parse_status(work_dir, "DONE")
    except Exception as exc:
        write_parse_status(work_dir, "ERROR", safe_error_message(exc))
```

실제 코드를 한 함수에 모두 작성하라는 뜻은 아니다. 플랫폼이 요구하는 공개 함수는 `parse()` 하나로 유지하되 내부 모듈에 책임을 나눈다.

```text
parse()
├─ runtime config 해석
├─ ETL client 호출
├─ Default JSON schema 검증
├─ 내부 문서 모델 변환
├─ 선택적 광고 후처리
├─ HRC exporter
└─ 출력 검증 및 상태 기록
```

## 3.6 Default JSON에서 내부 문서 모델로 변환하는 이유

ETL JSON을 HRC로 바로 바꾸면 구현은 짧지만 다음 문제가 생긴다.

- OCR 공급자 필드명과 KL 필드명이 코드 전체에 퍼진다.
- 실제 ETL JSON이 가이드와 조금 다를 때 수정 범위가 커진다.
- bbox polygon, confidence, 표 셀 등 HRC에 바로 넣지 않는 정보가 사라진다.
- 광고 후처리 로직이 ETL 원본 구조에 강하게 종속된다.

따라서 중간 모델을 하나 둔다.

```text
ETL Default JSON
  -> NormalizedDocument
       ├─ pages
       │   ├─ width, height
       │   └─ regions
       │       ├─ source_type
       │       ├─ text/html
       │       ├─ polygon
       │       ├─ rect
       │       ├─ confidence
       │       ├─ lines
       │       └─ table cells
       └─ warnings
  -> HRC JSONL
```

기존 시연용 저장소의 `AdDocument` 개념을 참고할 수 있지만, 농협 등록본은 Python 3.11과 최소 의존성 기준으로 별도 정의한다. 현재 저장소 전체를 그대로 복사하지 않는다.

## 3.7 DLA 유형에서 HRC item으로의 초기 매핑

| ETL DLA `type` | HRC `item` 후보 | 변환 기준 |
|---|---|---|
| `Title` | `h1`~`h4` 또는 `text` | `section_level`이 신뢰 가능하면 헤딩, 아니면 보수적으로 처리 |
| `Text` | `text` | `contents`와 `pageId` 사용 |
| `List-item` | `text` | bullet 정보를 보존해 텍스트로 변환 |
| `Table` | `table` | HTML contents 사용, `type_property.title` 필수 |
| `Figure` | `image` | 실제 crop 이미지 확보 가능할 때만 image item 생성 |
| `Equation` | `text` | HRC 허용 item에 equation이 없으므로 텍스트 표현 정책 필요 |
| `PageHF` | `text` 또는 제외 | 검색 품질과 원문 보존 정책 확인 |
| `Index` | `text` 또는 헤딩 | 실제 결과를 보고 결정 |
| `Unknown` | `text` | 텍스트 누락 방지를 우선하고 경고 표시 |

초기 구현 원칙은 “잘못된 구조를 확정하는 것보다 텍스트를 보존하는 것”이다.

### `Title`을 곧바로 `h1`로 만들면 안 되는 이유

DLA의 `Title`은 제목처럼 보이는 영역 유형일 뿐 문서 계층 깊이를 항상 보장하지 않는다. `section_level`이 제공되더라도 실제 광고물에서 신뢰할 수 있는지 검증해야 한다.

초기 정책 후보:

```text
section_level 1~4가 있고 현장 샘플에서 일관됨
  -> h1~h4

section_level이 없거나 비정상
  -> 첫 대표 제목만 h1
  -> 나머지는 text 또는 규칙 기반 추론
```

### Figure 처리

Default JSON은 Figure 영역과 bbox를 주더라도 실제 crop 이미지 파일이 결과에 항상 포함된다는 보장은 없다. HRC `image`는 `_img.zip` 안의 실제 파일을 참조해야 하므로 다음 중 하나가 필요하다.

1. `res_type=figure` 결과를 추가로 받아 이미지 저장
2. 원본 PDF/이미지에서 bbox 기준으로 직접 crop
3. 이미지 item을 만들지 않고 Figure 내부 OCR 텍스트만 보존

초기 등록 검증본은 3번으로 시작하고, 현장 결과와 요구사항이 확인되면 1번 또는 2번을 추가하는 편이 안전하다.

## 3.8 광고 후처리 범위

미팅 이해를 기준으로 농협 내부 Custom Parser의 최소 완료 기준은 다음이다.

```text
ETLwithLLM Default JSON
  -> 올바른 HRC JSONL/INFO JSON
```

기존 시연용 파이프라인의 다음 기능은 추가 고도화 범위다.

- DLA가 잘게 나눈 문구 조립
- 읽기 순서 보정
- 상품군 분류
- 광고 템플릿 선택
- 회사명·상품명·금리·유의사항 등 라벨링
- 심의용 구조 생성

농협 내부 VLM을 사용할 수 없을 수 있으므로 후처리는 두 모드로 분리한다.

| 모드 | 동작 |
|---|---|
| 기본 모드 | ETL OCR/DLA + 결정적 규칙 + HRC 변환 |
| VLM 확장 모드 | 농협 내부 vLLM 주소가 제공될 때 모호한 분류·라벨링 보조 |

VLM이 없을 때 분류되지 않은 값을 임의로 확정하지 않는다. `unresolved` 또는 검수 필요 상태로 남기고, 원문 텍스트는 HRC에 보존한다.

## 3.9 기존 두 API를 하나로 합치는 의미

과거 PoC의 “규정문서 파싱 API”와 “광고 심의입력 파싱 API”는 우리가 직접 API 서비스를 설계하면서 목적별로 나눈 것이다.

KL 등록형 Custom Parser에서는 외부 진입점이 이미 정해져 있다.

```text
POST /parsing
GET  /parsing/result/{uuid}
```

그러므로 농협 내부 등록본에서 별도 광고 API를 추가할 필요는 없다. 하나의 `parse()`에서 공통 HRC 변환을 수행하고, 필요하면 옵션이나 문서 메타로 광고 후처리만 활성화한다.

```python
document = convert_default_json(default_json)

if config.enable_ad_postprocess:
    document = postprocess_ad_document(document)

export_hrc(document)
```

이 구조에서 Custom Parser의 최종 출력은 HRC 계약 파일뿐이다. 과거의
`*_parsed.json`, `*_review_input.json`, `ad_summary.json`, ETL 원본 응답과 진단 로그는
KL 결과 ZIP에 넣지 않는다. ZIP 허용 목록은 다음과 같이 고정한다.

- 필수: `원본파일명_hrc.jsonl`
- 필수: `원본파일명_hrc.json`
- 조건부: 실제 HRC image 참조가 있을 때의 `원본파일명_img.zip`
- 조건부: VectorDB Doc Data를 실제 변경할 때의 `doc_data.json`

`원본파일명`은 확장자를 포함한다. 예를 들어 `광고.pdf_hrc.jsonl`이다.

## 3.10 KL 적재 이후의 범위

Custom Parser가 결과 ZIP을 반환하면 Custom Parser 작업은 끝난다. 이후 KL이 JSONL을 해석해 다음 작업을 수행한다.

```text
HRC JSONL
  -> 헤딩 메타 적용
  -> 청크 생성
  -> cust_meta 적용
  -> 임베딩
  -> 할당된 VectorDB 컬렉션 적재
```

심의 단계는 이후 Retrieval API를 호출해 적재된 문서를 검색하거나 조회하는 별도 단계다.

```text
심의 서비스
  -> KL Retrieval API
  -> VectorDB 검색/조회
  -> 광고 심의
```

Custom Parser가 VectorDB에 직접 접속하거나 심의를 실행하는 것으로 구현하지 않는다.

## 3.11 `cust_meta` 설계 원칙

메타 필드의 의미는 이 프로젝트가 정의하고 버전 관리해야 하지만 아직 번호별 의미를
배정하지 않는다. 원본 표에서 확인되는 차이는 다음뿐이다.

- `cust_attr1`~`cust_attr10`: 조회 only
- `cust_sattr1`~`cust_sattr5`: 검색·조회 및 임베딩 포함

현재 기본 exporter는 `cust_meta`를 출력하지 않는다. Retrieval API와 심의 호출부가 실제로
어떤 값을 조건으로 사용하는지 확인한 뒤 다음을 함께 결정한다.

- 상품군, 문서 유형, 심의 유형 중 검색어와 함께 임베딩할 값
- 정확 조회만 필요한 문서·원천 식별자
- 페이지·영역 추적을 HRC `page`로 충분히 처리할지 별도 메타로 둘지
- 번호별 의미, 누락값 정책, 스키마 버전과 재적재 정책

## 3.12 두 저장소의 역할

### 기존 `nh-ad-parser`

- 시연·연구·품질 고도화용
- 새 GPU의 PaddleX/Gemma 또는 대체 모델 사용 가능
- 영역 병합·템플릿·라벨링 실험
- P1/P3 및 검수 도구 유지

### 신규 `custom-parser`

- 농협 KL 등록용
- Python 3.11
- ETLwithLLM 공개 API 사용
- KL `/parsing` 계약과 HRC 출력에 집중
- 최소 의존성
- 농협 플랫폼의 소스 업로드 제약 준수

두 버전을 완전히 독립적으로 복사해 유지하면 후처리 버그 수정이 갈라질 수 있다. 공통 알고리즘은 다음 중 하나로 관리한다.

1. Python 3.11 호환 공통 모듈을 원본으로 두고 배포 시 평면 파일로 복사
2. 동일한 골든 테스트 입력·기대 결과를 두 저장소에서 실행
3. 농협용은 기능을 최소화하고 검증된 로직만 명시적으로 이식

현 시점에는 3번으로 시작하고, 공유 필요성이 커지면 1번으로 전환하는 것이 안전하다.

## 3.13 현재 구현과 최종 배포 구조

현재 구현은 원본 Custom Parser 예제와 직접 대조할 수 있도록 다음 계층을 유지한다.

```text
server/flow/
├─ run-application.sh
├─ setup-application.sh
├─ requirements.txt
├─ whl/
└─ app_custom_parser/
   ├─ main.py
   ├─ gunicorn_config.py
   └─ service/
      ├─ parsing_service.py
      ├─ status.py
      ├─ config.py
      ├─ etl_client.py
      ├─ document_model.py
      ├─ etl_adapter.py
      ├─ hrc_exporter.py
      └─ result_contract.py
```

기존 `run-application.sh`도 `app_custom_parser` 디렉터리로 이동하므로 이 구조는 현재
근거와 일치한다. “모든 파일 한 폴더”가 Python 파일의 완전 평면화를 의미하더라도 기존
진입 스크립트를 먼저 바꾸지 않는다. 농협의 최신 공식 템플릿을 받은 뒤 그 템플릿이 정한
경로와 import 구조로 별도 배포본을 구성한다.

## 3.14 이 방식에서 사용하지 않는 것

현재 선택된 아키텍처에서는 다음을 구현하지 않는다.

- 외부 DGX-Spark 주소 호출
- 별도 PaddleX OCR 서버 호출
- ETLwithLLM 컨테이너의 `custom_extension/implements` 마운트
- `extract_type=CUSTOMIZE` 사용
- Custom Parser가 VectorDB에 직접 적재
- Custom Parser가 Retrieval API를 호출해 심의까지 수행
- 별도 `/ad/parsing` 공개 API
- 로그인, 사용자 또는 workspace 생성 API
- ETL callback 수신 API

요구사항이 바뀌면 확장할 수 있지만, 초기 등록 검증 범위에는 포함하지 않는다.
