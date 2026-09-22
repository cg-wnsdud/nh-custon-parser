# NH Knowledge Lake Custom Parser 개발 기준

이 저장소는 농협 Knowledge Lake(KL)에 **소스코드 제공 방식으로 등록할 Custom Parser**를 개발하기 위한 공간이다.

다음 두 원본 자료의 계약을 기준으로 Python 3.11용 구현을 구성한다.

1. `1.awx_custom_parser_example_api`
   - KL이 Custom Parser를 어떻게 호출하는지 정의한다.
   - `/parsing`, `/parsing/result/{uuid}`, `parse()`와 HRC 결과 ZIP 규격이 핵심이다.
2. `[AgileSoDA] ETLwithLLM API가이드_v1.1.0`
   - Custom Parser가 농협 DLA/OCR에 원본 문서를 어떻게 보내고 결과를 받는지 정의한다.
   - 분석 요청, 상태 확인, 결과 조회, Default JSON 구조가 핵심이다.

```text
Knowledge Lake
  -> Custom Parser POST /parsing
  -> parsing_service.parse()
  -> ETLwithLLM 분석 요청 / 상태 폴링 / Default JSON 조회
  -> HRC JSONL/INFO 변환
  -> Custom Parser 결과 ZIP 반환
  -> KL 적재 및 후속 VectorDB 처리
```

## 전달 범위

- **우리가 전달하는 것은 `parsing_service.py`의 `parse()` 구현과 그 보조 모듈들이다.**
- **`main.py`와 `gunicorn_config.py`는 템플릿 원본 그대로 두고 전달본에도 넣지 않는다.**
  템플릿이 이 파일들을 함께 준 것은 동작 방식을 설명하기 위한 것이지 수정 대상이 아니다.
- 기능별 파일 분리는 허용되며, **하위 폴더 없는 flat 구성**으로 전달한다.
- ETL 접속값(`author`, `ws_id` 등)은 우리가 자리만 정의하고 **농협이 실행 시 주입**한다.
- 주입 방법과 구현 내용을 **문서로 함께 전달**한다
  (`server/flow/app_custom_parser/service/README.md`).

이전에 보낸 `kl-flat.zip`은 `main.py`와 `gunicorn_config.py`까지 포함한 평면 번들이었고,
플랫폼 진입점을 우리가 고쳐 보낸 형태여서 이 기준에 맞지 않는다. 해당 산출물은 제거했다.

## 저장소 구조

`server/flow` 아래는 제공받은 템플릿을 그대로 둔 영역이고, 우리 구현은 `service/`에만 있다.

```text
server/flow/                        # 템플릿 원본 미러 (수정 금지)
├─ run-application.sh
├─ setup-application.sh
├─ test-application.sh
├─ requirements.txt
├─ dummy.txt
├─ readme/{parser_howto.txt, parser_readme.txt}
├─ whl/python_multipart-0.0.17-py3-none-any.whl
└─ app_custom_parser/
   ├─ main.py                       # 템플릿 원본
   ├─ gunicorn_config.py            # 템플릿 원본
   └─ service/                      # ★ 우리 구현 (flat, 하위 폴더 없음)
      ├─ parsing_service.py         # 템플릿 진입점. DO NOT EDIT 영역 원본 유지
      ├─ etl_config.py              # 실행 시 주입값(환경변수) 해석
      ├─ etl_client.py              # ETLwithLLM API 호출
      ├─ etl_adapter.py             # Default JSON 검증·정규화
      ├─ document_model.py          # 내부 문서 모델
      ├─ hrc_exporter.py            # HRC JSONL/INFO 생성
      ├─ result_contract.py         # 결과 규격 검증
      ├─ vlm_client.py              # VLM 호출 (현재는 사용 가능 여부 확인용)
      └─ README.md                  # 농협 전달용 한글 안내
tools/                              # 우리 개발용 도구 (전달 대상 아님)
docs/                               # 분석·설계 문서
dist/nh-parser-flat/                # 농협 전달용 평면 생성본
```

`server/flow`의 템플릿 파일은 원본과 diff가 없어야 한다.

## README 구분

- 저장소 루트의 이 `README.md`는 개발·검증·설계 근거와 알려진 제약을 보존하는 내부 기준 문서다.
- `server/flow/app_custom_parser/service/README.md`는 농협 전달용으로, 파일별 역할과 배치 위치,
  필수 환경변수만 간단히 안내한다.

## ETL 설정 주입

템플릿 원본 `main.py`는 `options = {}`로 고정되어 있어 KL의 `option` 값이 `parse()`까지
오지 않는다. 그래서 접속 정보는 **환경변수로만** 받는다.

| 환경변수 | 필수 | 기본값 |
|---|---|---|
| `ETL_BASE_URL` | 필수 | - |
| `ETL_AUTHOR` | 필수 | - |
| `ETL_WS_ID` | 필수 | - |
| `ETL_PRJ_CONFIG` | 선택 | `{"extract_type":"dla","table_to_struct":"html"}` |
| `ETL_ANALYSIS_TIMEOUT_SECONDS` | 선택 | `540` |
| `ETL_CONNECT_TIMEOUT_SECONDS` | 선택 | `30` |
| `ETL_POLL_INITIAL_SECONDS` | 선택 | `1` |
| `ETL_POLL_MAX_SECONDS` | 선택 | `5` |

필수 값이 없으면 ETL을 호출하지 않고 다음 메시지로 실패한다.
`Missing ETL configuration: base_url/ETL_BASE_URL, author/ETL_AUTHOR, ws_id/ETL_WS_ID`

현재 `EtlConfig.from_environment()`는 환경변수만 읽는다. KL의 `option`을 사용하려면 원본
`main.py`가 해당 값을 디코딩해 `parse()`로 전달하도록 허용된 뒤 별도로 구현한다.

### `option`이란

KL이 `POST /parsing`에 `src_file`과 함께 보내는 Base64 인코딩 JSON 문자열이다. 템플릿
`readme.md`는 그 안에 **`parser_info`와 `doc_data` 두 덩어리**가 들어온다고 정의한다.

**`parser_info`** 는 KL에 등록된 파서 자체의 정보다. `id`, `parser_type`, `exe_type`,
`is_ocr`, `extensions` 등과 함께 `prop`에 OCR/LLM 제공자 정보(`supplier`, `url`, `key`)가
온다. 즉 외부 공급자의 주소와 키는 원래 이 경로로 받는 설계다.

**`doc_data`** 는 KL이 보관 중인 문서 메타데이터이며 **읽기 전용 입력**이다.
`doc_id`, `title`, `category1~4`, `lang_cd`, `origin_doc_id`, `origin_url`, `origin_doc_auth`,
`origin_sys_nm`, `doc_reg_date`, `reg_user_id`, `reg_user_nm`, `category_path`, 그리고 문서
Store에서 정의한 `user_meta.*` 가 들어온다.

파서가 이 값을 바꾸려면 작업 디렉터리에 **`doc_data.json`** 이라는 이름으로 내보내야 하며,
변경분은 VectorDB에만 반영된다(템플릿 `readme.md`). 문서 단위 메타인 `doc_data`와, HRC
JSONL의 각 item에 붙이는 `cust_meta`(`cust_attr1~10`, `cust_sattr1~5`)는 서로 다른 것이다.

#### 현재 코드에서의 취급

- `process_document()`가 `option["doc_data"]`를 읽어 `export_hrc()`로 넘긴다. INFO JSON의
  `title`, `subject`, `updated`가 이 값에서 나오며, 값이 없으면 `title`은 첫 heading으로 대체된다.
- `result_contract.py`는 작업 디렉터리에 `doc_data.json`이 있으면 결과 ZIP에 포함한다.
  다만 현재 파서는 이 파일을 만들지 않는다. 광고 후처리에서 파서가 계산한 값을 넣을지
  규칙이 정해지면 그때 생성한다.
- **실제로는 항상 비어 있다.** 템플릿 원본 `main.py`가 `options = {}`를 고정으로 넘기고,
  시그니처도 `option: str = None`이라 KL이 form-data로 보낸 값이 쿼리 파라미터로 해석돼
  버려지기 때문이다.

즉 수용 경로는 이미 있고, `main.py`가 `option: str = Form(None)`과 base64 디코딩을 하도록
허용되는 순간 추가 구현 없이 동작한다.

## Python 의존성

ETL HTTP 호출은 `requests`를 사용한다. 농협 플랫폼 이미지에 이미 설치되어 있으므로
현재 전달본에 wheel을 넣지 않았다. 템플릿 `2.Package.txt` 기준 설치 버전은 다음과 같다.

| 패키지 | 이미지 버전 |
|---|---|
| requests | 2.34.2 |
| urllib3 | 2.7.0 |
| certifi | 2026.7.22 |
| idna | 3.18 |
| charset-normalizer | 3.4.9 |

## 템플릿 원본을 고치지 않고 남겨 둔 이슈

아래는 템플릿 `main.py`의 동작이며, 우리 판단으로 수정하지 않고 전달 문서에 고지한다.

- `option` 파라미터가 쿼리로 선언되어 KL의 form-data를 받지 못한다(`option: str = None`).
- `TIMEOUT` 환경변수를 설정하면 `timeout + 10`에서 문자열/정수 연산 오류가 난다.
- `image` 디렉터리가 비어 있어도 빈 `_img.zip`을 만들어 결과 ZIP에 포함한다.
- 파싱 상태가 `ERROR`일 때 전용 분기가 없어 HTTP 500 + 메시지로 응답한다.

## 현재 HRC 구현의 확정 범위와 보류 범위

원본 자료로 확정된 것은 확장자를 포함한 파일명, 허용 item, 필수 `value`, table/image의
필수 부가 속성, text/table/image에 선택적으로 쓰는 `page`다. 원본 예제에 맞춰 heading에는
`page`를 넣지 않는다.

다음은 실제 ETL·KL·Retrieval 결과 확인 전까지 최종 규격으로 보지 않는다.

- ETL `page.width/height`와 HRC INFO 페이지 크기의 단위 변환
- ETL `pageId`를 HRC `page`로 사용하는 번호 기준
- `cust_attr1~10`, `cust_sattr1~5`의 프로젝트별 의미
- Figure crop과 `_img.zip` 생성
- 파서가 계산할 `doc_data.json` 변경 규칙

현재 exporter는 잘못된 의미가 적재되지 않도록 `cust_meta`와 `doc_data.json`을 만들지 않고,
Figure OCR 문구만 `text`로 보존한다.

## 로컬 검증

코어 모듈과 API 계약 테스트는 저장소에서 바로 돌릴 수 있다.

```bash
python -m unittest discover -s tests -v
```

FastAPI/Starlette가 없는 환경에서는 API 계약 테스트만 skip된다. 테스트는 전달본과 동일하게
`service/` 폴더를 import 경로에 넣고 flat 모듈로 불러온다.

## VLM 호출

VLM 결과를 HRC 구조에 반영하려면 정규화된 문서를 손에 쥔 시점이어야 하므로,
호출 지점은 `convert_default_json()` 과 `export_hrc()` 사이다. 현재 단계에서는 그 자리에
**사용 가능 여부 확인용 1회 호출**만 넣었고 응답을 HRC에 반영하지 않는다.

- `VLM_BASE_URL`, `VLM_MODEL` 이 없으면 호출 자체를 건너뛴다. ETL 값과 달리 필수가 아니다.
- 호출 실패는 경고만 남기고 파싱을 계속한다. VLM 때문에 파싱이 실패하면 안 된다.
- 응답은 `{원본파일명}_vlm.json` 으로 남긴다. `result_contract.py` 가 허용 파일만 ZIP에 담으므로
  결과 ZIP에는 포함되지 않는다.
- 요청은 OpenAI 호환 `POST {VLM_BASE_URL}/chat/completions` 이며, 이미지 입력을 위한
  멀티모달 content 생성(`user_content(prompt, image=...)`)까지는 구현해 두었다. 다만 현재
  ETL 호출이 `res_type: ["default"]` 라 crop 이미지를 받지 않으므로 실제 이미지 경로는 미정이다.
- 농협 플랫폼 이미지에는 `openai 2.46.0`, `pillow 12.3.0` 이 있으나 ETL 호출과 같은 방식을
  유지하기 위해 `requests` 로 구현했다.

## 다음 단계

- `parse()` 후처리 단계에 VLM 호출 로직 추가 (모델명·엔드포인트·키는 농협이 채우도록 분리,
  gemma 계열 OpenAI 호환 호출 규격 기준). 안내 문서에 주입 방법을 함께 정리한다.
