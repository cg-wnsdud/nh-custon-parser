# NH Knowledge Lake Custom Parser 개발 기준

이 저장소는 농협 Knowledge Lake(KL)에 **소스코드 제공 방식으로 등록할 Custom Parser**를 개발하기 위한 공간이다.

다음 두 원본 자료의 계약을 기준으로 Python 3.11용 1차 구현을 구성한다.

1. `1.awx_custom_parser_example_api`
   - KL이 Custom Parser를 어떻게 호출하는지 정의한다.
   - `/parsing`, `/parsing/result/{uuid}`, `parse()`와 HRC 결과 ZIP 규격이 핵심이다.
2. `[AgileSoDA] ETLwithLLM API가이드_v1.1.0`
   - Custom Parser가 농협 DLA/OCR에 원본 문서를 어떻게 보내고 결과를 받는지 정의한다.
   - 분석 요청, 상태 확인, 결과 조회, Default JSON 구조가 핵심이다.

두 자료는 경쟁 관계가 아니라 앞뒤로 연결되는 계약이다.

```text
Knowledge Lake
  -> Custom Parser POST /parsing
  -> parsing_service.parse()
  -> ETLwithLLM 분석 요청
  -> ETLwithLLM 상태 폴링
  -> Default JSON 조회
  -> HRC JSONL/INFO JSON 변환
  -> Custom Parser 결과 ZIP 반환
  -> KL 적재 및 후속 VectorDB 처리
```

중요한 구분은 다음과 같다.

- 농협 플랫폼이 등록된 소스를 실행하고 서비스 주소를 관리하므로, 우리가 별도 외부 서버를 운영하는 방식은 아니다.
- 하지만 등록하는 소스에는 FastAPI 앱과 실행 스크립트가 포함된다. 플랫폼이 이 소스를 실행하면 KL이 그 앱의 API를 호출한다.
- `run-application.sh`는 프로세스 실행 진입점이다.
- `app_custom_parser/main.py`는 HTTP API 진입점이다.
- `app_custom_parser/service/parsing_service.py`의 `parse()`는 실제 프로젝트 파싱 로직 진입점이다.
- 현재 선택한 방식에서는 ETLwithLLM 3장의 `custom_extension`을 플랫폼 내부에 마운트하는 것이 아니라, **KL Custom Parser의 `parse()`에서 ETLwithLLM 공개 API를 호출**한다.

## 문서 읽는 순서

1. [Custom Parser 예제 코드 분석](docs/01-custom-parser-example.md)
2. [ETLwithLLM API 분석](docs/02-etlwithllm-api.md)
3. [통합 구조와 구현 기준](docs/03-integrated-architecture.md)
4. [구현 및 검증 체크리스트](docs/04-implementation-checklist.md)

## 현재 확정된 개발 원칙

- Python 3.11을 기준으로 작성한다.
- 기존 규정문서 API와 광고 전용 API를 별도로 만들지 않는다.
- KL 계약인 `POST /parsing`과 `GET /parsing/result/{uuid}`를 유지한다.
- 실제 프로젝트 로직은 `parse(work_dir, img_dir, file_path, option)`에서 시작한다.
- `parse()`는 원본 파일을 ETLwithLLM에 보내고 Default JSON을 HRC 규격으로 변환한다.
- 결과 이름의 `원본파일명`에는 확장자가 포함된다. `광고.pdf` 입력이면 본문은
  `광고.pdf_hrc.jsonl`, INFO는 `광고.pdf_hrc.json`이다.
- `_hrc.json`은 문서 INFO 파일이며 JSONL과 역할이 다르다. 필드별 값과 단위는 실제
  KL 수용 결과로 최종 확인한다.
- 결과 ZIP에는 위 두 파일, 실제 이미지 참조가 있을 때의 `_img.zip`, 실제 Doc Data를
  변경할 때의 `doc_data.json`만 포함한다. 중간 결과나 광고용 sidecar는 포함하지 않는다.
- 광고 템플릿·라벨링 같은 추가 후처리는 기본 HRC 변환이 검증된 뒤 선택적으로 붙인다.
- 농협이 생성한 workspace의 접속 URL, `author`, `ws_id`는 option 또는 환경변수로
  주입하며 코드에 하드코딩하지 않는다. 로그인과 workspace 생성은 구현 범위가 아니다.

## 현재 구현

플랫폼 예제 구조를 보존한 실행본은 `server/flow` 아래에 있다.

```text
server/flow/
├─ run-application.sh
├─ setup-application.sh
├─ test-application.sh
├─ requirements.txt
├─ whl/
│  ├─ python_multipart-0.0.17-py3-none-any.whl
│  └─ SHA256SUMS
└─ app_custom_parser/
   ├─ main.py
   ├─ gunicorn_config.py
   └─ service/
      ├─ config.py
      ├─ etl_client.py
      ├─ etl_adapter.py
      ├─ document_model.py
      ├─ hrc_exporter.py
      ├─ result_contract.py
      ├─ status.py
      └─ parsing_service.py
```

구현된 흐름:

```text
POST /parsing
  -> Base64 option 검증 및 원본 안전 저장
  -> option은 디스크에 저장하지 않고 subprocess 표준입력으로 전달
  -> UUID별 subprocess에서 parse() 실행
  -> ETL 1.16 분석 요청
  -> 1.17 상태 폴링
  -> 1.18~1.20 Default JSON 조회
  -> 내부 문서 모델 정규화
  -> HRC JSONL/INFO 생성 및 검증
  -> DONE
  -> GET /parsing/result/{uuid}에서 허용 파일만 ZIP 반환
  -> 원본 예제와 같이 완료 또는 오류 결과 조회 후 작업 디렉터리 삭제
```

### ETL 설정

다음 option 형식을 우선 사용하며, 같은 이름의 환경변수를 fallback으로 지원한다.

```json
{
  "etl": {
    "base_url": "http://etl-host",
    "author": "provided-author",
    "ws_id": "provided-workspace-id",
    "analysis_timeout_seconds": 540,
    "prj_config": {
      "extract_type": "dla",
      "table_to_struct": "html"
    }
  },
  "doc_data": {
    "doc_id": "DOC-1",
    "origin_doc_id": "SOURCE-1",
    "origin_sys_nm": "NH"
  }
}
```

원본 KL option의 `parser_info.prop.url`도 ETL URL로 인식한다. `prop.key`는 일반 OCR
공급자용 필드지만 ETL 1.16 이후 문서에는 이를 어떤 헤더에 넣는지 규격이 없으므로 임의로
사용하지 않는다. `author`, `ws_id`는 `option.etl`, `parser_info.prop`의 ETL 확장값 또는
환경변수에서 받아야 한다.

환경변수는 `ETL_BASE_URL`, `ETL_AUTHOR`, `ETL_WS_ID`,
`ETL_CONNECT_TIMEOUT_SECONDS`, `ETL_ANALYSIS_TIMEOUT_SECONDS`,
`ETL_POLL_INITIAL_SECONDS`, `ETL_POLL_MAX_SECONDS`다. `option.etl` 값이 환경변수보다
우선한다. 미조회 작업 디렉터리는 기본 24시간 이후 새 요청 시 정리하며
`JOB_RETENTION_SECONDS`로 조정할 수 있다.

### 현재 HRC 구현의 확정 범위와 보류 범위

원본 자료로 확정된 것은 확장자를 포함한 파일명, 허용 item, 필수 `value`, table/image의
필수 부가 속성, text/table/image에 선택적으로 쓰는 `page`다. 원본 예제에 맞춰 heading에는
`page`를 넣지 않는다.

다음은 실제 ETL·KL·Retrieval 결과 확인 전까지 최종 규격으로 보지 않는다.

- ETL `page.width/height`와 HRC INFO 페이지 크기의 단위 변환
- ETL `pageId`를 HRC `page`로 사용하는 번호 기준
- `cust_attr1~10`, `cust_sattr1~5`의 프로젝트별 의미
- Figure crop과 `_img.zip` 생성
- 파서가 계산할 `doc_data.json` 변경 규칙

현재 기본 exporter는 잘못된 의미가 적재되지 않도록 `cust_meta`와 `doc_data.json`을 만들지
않고, Figure OCR 문구만 `text`로 보존한다.

### 로컬 검증

코어 모듈은 외부 패키지 없이 테스트할 수 있다.

```bash
python -m unittest discover -s tests -v
```

실제 앱 import와 기동에는 농협 예제 기반 이미지에 이미 포함된 `awx-dlp`, FastAPI,
Gunicorn, Uvicorn이 필요하다. 예제 환경에서 확인한 버전은 `platform-requirements.txt`에
분리했다. `setup-application.sh`는 이 네 패키지를 먼저 확인한 후 동봉한 `python-multipart` wheel을
폐쇄망 방식으로 설치한다. 실제 등록 이미지의 기본 패키지가 다르면 그 환경용 wheelhouse를
다시 고정해야 하며, 현재 번들이 임의로 인터넷에서 패키지를 내려받지는 않는다.

## 배포 직전에 반드시 재확인할 한 가지

미팅에서 전달된 “모든 파일을 한 폴더에 둔다”는 설명과 기존 샘플의 계층 구조는 서로 다르다. 기존 `run-application.sh`는 `app_custom_parser` 디렉터리로 이동하고 `main:app`을 실행한다. 따라서 실제 등록본을 평면 구조로 만들기 전에 다음 중 어느 의미인지 농협 측 템플릿으로 확정해야 한다.

- 업로드할 최상위 번들 하나만 허용한다는 의미
- `app_custom_parser` 안에서 하위 `service/` 폴더를 만들지 말라는 의미
- 실행 스크립트와 모든 Python 파일까지 완전히 동일 디렉터리에 두라는 의미

현재 소스는 원본 예제 계층 구조로 작성했으며 `run-application.sh`와 Gunicorn 플랫폼
설정을 원본 기준으로 유지한다. 완전 평면 배포를 요구하더라도 현재 진입 스크립트를 임의로
고치지 않고, 농협이 제공하는 최신 공식 템플릿을 받은 뒤 별도 배포본을 만든다.
