# 1. Knowledge Lake Custom Parser 예제 코드 분석

## 1.1 이 예제가 무엇인가

`1.awx_custom_parser_example_api`는 완성된 문서 파서가 아니다. 농협 Knowledge Lake(KL)가 사용자 정의 파서를 호출할 수 있도록 **API 서버의 뼈대와 결과 형식**을 보여 주는 예제다.

예제에서 이미 제공하는 부분은 다음과 같다.

- FastAPI 애플리케이션
- 비동기 작업 UUID 발급
- 작업 상태 파일 기록
- KL의 결과 폴링 API
- HRC 결과 파일을 ZIP으로 묶어 반환하는 처리
- Gunicorn 실행 설정과 셸 스크립트

우리가 구현해야 하는 부분은 `parsing_service.py`의 `parse()` 안에 들어갈 프로젝트별 실제 처리다. 이 프로젝트에서는 그 처리의 중심이 “원본 파일을 ETLwithLLM에 보내고 Default JSON을 HRC로 바꾸는 것”이다.

## 1.2 세 가지 진입점

“진입점”이라는 말을 하나로 사용하면 혼동된다. 예제에는 역할이 다른 세 진입점이 있다.

| 구분 | 파일 또는 함수 | 역할 |
|---|---|---|
| 프로세스 실행 진입점 | `server/flow/run-application.sh` | 플랫폼 컨테이너에서 Gunicorn 프로세스를 실행한다. |
| HTTP 진입점 | `server/flow/app_custom_parser/main.py` | KL이 호출하는 `/parsing`, `/parsing/result/{uuid}`, `/health`를 제공한다. |
| 실제 파싱 로직 진입점 | `parsing_service.py`의 `parse()` | 원본 파일을 분석하고 HRC 결과 파일을 만든다. |

별도의 `parser.py`는 기존 예제에 없다.

## 1.3 플랫폼 등록과 서버 실행의 의미

우리가 농협 외부에 별도 서버를 구축하고 URL을 전달하는 것으로 이해하면 안 된다. 미팅 내용을 기준으로는 소스코드를 농협 플랫폼에 등록하고, 농협 플랫폼이 그 소스로 서버 프로세스를 실행한다.

따라서 다음 두 문장은 동시에 맞다.

1. 우리는 별도 외부 FastAPI 서버를 직접 운영하지 않는다.
2. 우리가 등록하는 소스 안에는 FastAPI 앱과 Gunicorn 실행 코드가 들어 있다.

실행 주체가 농협 플랫폼일 뿐, KL이 실제로 호출하는 대상은 우리가 작성한 FastAPI 앱이다.

```text
[개발자]
  Custom Parser 소스 등록
          |
          v
[농협 플랫폼]
  run-application.sh 실행
          |
          v
  gunicorn main:app
          |
          v
[KL]
  POST /parsing 호출
```

## 1.4 원본 예제 디렉터리의 역할

```text
1.awx_custom_parser_example_api/
├─ readme.md                         # 동기/비동기 API와 HRC 규격 설명
├─ 2.Package.txt                     # 예제 환경에 설치된 패키지 목록
├─ in_sample.hwp                     # 입력 예제
├─ out_sample_hrc.jsonl              # HRC 본문 예제
├─ out_sample_hrc.json               # 문서 INFO 예제
├─ image/BIN0001.jpg                 # 이미지 예제
└─ server/flow/
   ├─ run-application.sh             # 서버 실행
   ├─ setup-application.sh           # 추가 wheel 설치
   ├─ test-application.sh            # /parsing 호출과 폴링 예제
   ├─ requirements.txt
   ├─ whl/
   ├─ readme/
   │  ├─ parser_howto.txt            # 비동기 계약 설명
   │  └─ parser_readme.txt           # 로컬 실행 순서
   └─ app_custom_parser/
      ├─ main.py                     # FastAPI 계약
      ├─ gunicorn_config.py
      └─ service/parsing_service.py  # 실제 parse() 구현 위치
```

`2.Package.txt`는 실행 환경 전체의 패키지 스냅샷에 가깝다. 우리 코드가 전부를 요구한다는 뜻은 아니다. 실제 전달 의존성은 최소한으로 별도 고정해야 한다.

## 1.5 `run-application.sh` 코드 흐름

핵심 코드는 다음과 같다.

```bash
export FLOW_APP_NAME="app_custom_parser"

if [ -d "/infer-model" ]; then
    export PATH_SOURCE=`tree -ifd /infer-model | grep flow | head -n 1`
    export PATH_TEMP="$PATH_INFER_ENV/temp"
else
    export PATH_SOURCE="/project/work/flow"
    export PATH_TEMP="/project/work/flow/temp"
fi

cd $PATH_SOURCE/$FLOW_APP_NAME
export PYTHONPATH=$PYTHONPATH:$CUSTOM_LIBS
gunicorn main:app --config gunicorn_config.py
```

순서대로 해석하면 다음과 같다.

1. 앱 디렉터리 이름을 `app_custom_parser`로 고정한다.
2. 플랫폼 추론 환경인지 로컬 예제 환경인지에 따라 소스·임시 디렉터리를 정한다.
3. 로그 설정을 플랫폼 경로에 맞춘다.
4. `app_custom_parser` 디렉터리로 이동한다.
5. 별도로 설치한 `custom_libs`를 `PYTHONPATH`에 추가한다.
6. `main.py` 안의 `app` 객체를 Gunicorn/Uvicorn worker로 실행한다.

`main:app`의 의미는 “`main.py` 모듈에서 `app`이라는 FastAPI 객체를 가져와 실행한다”는 뜻이다.

이 스크립트는 플랫폼이 이미 서버를 제공한다는 의미가 아니라, 플랫폼이 **우리 FastAPI 서버 프로세스를 어떤 방식으로 실행하는지** 보여 준다.

`gunicorn_config.py`는 `MLDL_PROBE_PORT` 환경변수를 사용하고 기본 포트를 `9101`로 둔다. 그래서 `test-application.sh`도 `127.0.0.1:9101`을 호출한다. 일반 환경의 기본 worker 수는 2, 플랫폼 추론 환경에서는 8로 설정되어 있다. 여러 worker가 동일 작업 상태를 읽으므로 작업 디렉터리는 모든 worker가 공유할 수 있는 경로여야 한다.

## 1.6 `setup-application.sh`와 의존성

예제는 다음 한 줄만 실행한다.

```bash
pip install --target=/project/work/flow/custom_libs \
  /project/work/flow/whl/python_multipart-0.0.17-py3-none-any.whl
```

인터넷에서 패키지를 내려받는 것이 아니라 전달된 wheel 파일을 `custom_libs`에 설치한다. 폐쇄망에서는 이와 같이 필요한 패키지와 wheel을 함께 전달해야 할 가능성이 높다.

우리 구현에서 HTTP 클라이언트로 `requests` 또는 `httpx`를 사용한다면 다음을 먼저 확인해야 한다.

- Python 3.11 기본 환경에 이미 설치되어 있는가
- 없다면 wheel을 함께 전달할 수 있는가
- 농협 플랫폼이 요구하는 의존성 명세 파일 이름과 설치 방식은 무엇인가

## 1.7 KL의 비동기 API 계약

### 최초 요청

```http
POST /parsing
Content-Type: multipart/form-data
```

입력:

- `src_file`: 원본 문서 파일
- `option`: Base64로 인코딩된 JSON 문자열

호출 예:

```bash
curl -X POST http://host/parsing \
  -F "src_file=@sample.pdf" \
  -F "option=e30="
```

`e30=`은 `{}`를 Base64로 인코딩한 값이다.

정상 응답은 HTTP 202이며 형식을 그대로 지켜야 한다.

```json
{
  "result": "OK",
  "body": {
    "uuid": "12378ba806e44279afdf81e6437210a9",
    "timeout": 600
  }
}
```

여기서 UUID는 ETLwithLLM의 `task_id`가 아니다. KL이 우리 Custom Parser 작업을 다시 조회하기 위한 **바깥쪽 작업 ID**다.

### 결과 폴링

```http
GET /parsing/result/{uuid}
```

처리 중:

```json
{"status": "PARSING"}
```

파싱 오류:

```json
{"status": "ERROR", "message": "오류 상세 내용"}
```

완료:

- HTTP 200
- `kl-core-s2-output.zip` 반환

가이드에는 30초 이내 작업이면 최초 POST에서 HTTP 200과 ZIP을 직접 반환할 수도 있다고 되어 있다. 그러나 ETLwithLLM 분석 시간이 길 수 있으므로 이번 구현은 비동기 202 + 폴링 구조를 유지한다.

## 1.8 `main.py`의 실제 처리

### 1단계: 요청 접수

원본 코드는 다음 API를 정의한다.

```python
@app.post("/parsing")
async def parsing_text_docx_to_json(
    src_file: UploadFile,
    background_tasks: BackgroundTasks,
    option: str = None,
):
```

실제 구현에서는 multipart 필드임을 명확히 하기 위해 다음처럼 쓰는 것이 안전하다.

```python
from fastapi import File, Form, UploadFile

@app.post("/parsing")
async def request_parsing(
    background_tasks: BackgroundTasks,
    src_file: UploadFile = File(...),
    option: str | None = Form(None),
):
    ...
```

예제는 `option` 디코딩이 주석 처리되어 있고 `options = {}`로 덮어쓴다. 실제 구현에서는 Base64 디코딩과 JSON 파싱을 복원해야 한다.

```python
import base64
import json

options = {}
if option:
    decoded = base64.b64decode(option)
    options = json.loads(decoded.decode("utf-8"))
```

옵션에는 다음이 들어올 수 있다.

- `parser_info`: Parser ID, 실행 방식, OCR 공급자 정보 등
- `doc_data`: KL 문서 ID, 제목, 카테고리, 원천 시스템 정보, 사용자 메타 등

### 2단계: 작업 디렉터리와 UUID 생성

```python
_uuid = uuid.uuid4().hex
work_dir = os.path.join(PATH_WORK, _uuid)
img_dir = os.path.join(work_dir, "image")
os.makedirs(img_dir, exist_ok=True)
```

각 요청을 UUID 디렉터리로 분리하므로 동시에 여러 문서가 들어와도 파일이 섞이지 않는다.

### 3단계: 원본 저장 및 상태 기록

```python
file_fullpath = os.path.join(work_dir, base_filename)
with open(file_fullpath, "wb") as file_object:
    file_object.write(src_file.file.read())

write_parse_status(work_dir, "PARSING")
```

`genaikl.status` 파일에 다음처럼 상태가 기록된다.

```json
{"status": "PARSING", "message": ""}
```

### 4단계: 실제 파싱을 별도 프로세스로 실행

```python
background_tasks.add_task(
    run_method_in_subprocess,
    TIMEOUT,
    work_dir,
    img_dir,
    file_fullpath,
    options,
)
```

`run_method_in_subprocess()`는 내부적으로 다음과 같은 Python 명령을 실행한다.

```python
from service.parsing_service import parse
parse(work_dir, img_dir, file_path, options)
```

이번 프로젝트에서는 바로 이 `parse()`가 다음 작업을 수행해야 한다.

```text
ETL 분석 요청
  -> ETL 상태 폴링
  -> Default JSON 조회
  -> HRC JSONL/INFO JSON 생성
  -> 상태 DONE 또는 ERROR 기록
```

### 5단계: 즉시 202 반환

FastAPI 요청은 실제 OCR 완료를 기다리지 않고 UUID를 반환한다. 이후 KL이 결과 API를 폴링한다.

### 6단계: 결과 API

`GET /parsing/result/{uuid}`는 `genaikl.status`를 읽는다.

- `DONE`: 결과 파일을 ZIP으로 묶고 반환
- `PARSING`: `{"status":"PARSING"}` 반환
- 그 외: 오류 반환

완료 ZIP의 내부 파일은 디렉터리 경로 없이 루트에 들어간다.

```text
kl-core-s2-output.zip
├─ 원본파일명_hrc.jsonl
├─ 원본파일명_hrc.json
├─ 원본파일명_img.zip       # 실제 HRC image 참조가 있을 때만
└─ doc_data.json            # 변경할 때만
```

이 네 종류 외의 중간 JSON, ETL 원본 응답, 로그, P1/P3, 광고 요약 같은 sidecar는 결과
ZIP에 포함하지 않는다. `_hrc.jsonl`과 `_hrc.json`은 필수이며 나머지 둘만 조건부다.

여기서 `원본파일명`은 확장자를 포함한다. 원본 README 21~23행과 샘플 구현 109~110행은
모두 `src_file.filename + "_hrc..."` 형식이다. 따라서 `광고.pdf`의 결과명은
`광고.pdf_hrc.jsonl`, `광고.pdf_hrc.json`, 조건부 `광고.pdf_img.zip`이다.

## 1.9 `parse()`가 지켜야 하는 상태 계약

함수 시그니처:

```python
def parse(work_dir, img_dir, file_path, option=None):
    ...
```

인자 의미:

| 인자 | 의미 |
|---|---|
| `work_dir` | 현재 KL 요청 전용 작업 디렉터리 |
| `img_dir` | HRC가 참조할 추출 이미지 저장 디렉터리 |
| `file_path` | KL에서 받은 원본 파일의 로컬 경로 |
| `option` | Base64 옵션을 디코딩한 딕셔너리 |

필수 동작:

```python
def parse(work_dir, img_dir, file_path, option=None):
    try:
        write_parse_status(work_dir, "PARSING")

        # ETLwithLLM 요청, 결과 조회, HRC 변환

        write_parse_status(work_dir, "DONE")
    except Exception as exc:
        write_parse_status(work_dir, "ERROR", str(exc))
```

`DONE`은 모든 필수 결과 파일이 정상적으로 닫히고 검증된 후에만 기록해야 한다.

## 1.10 HRC JSONL 규격

JSONL은 JSON 배열 하나가 아니라, 한 줄마다 독립적으로 파싱 가능한 JSON 객체가 하나씩 들어가는 형식이다.

```jsonl
{"item":"h1","value":"상품 안내"}
{"item":"text","value":"NH농협은행 광고 문구","page":1}
{"item":"table","value":"<table>...</table>","type_property":{"title":"금리표"},"page":1}
```

허용되는 `item`:

- `text`
- `table`
- `image`
- `h1`, `h2`, `h3`, `h4`

공통 필수값:

- `item`
- `value`

원본 가이드는 `page`를 `text`, `table`, `image`에 추가할 수 있다고 설명하고 heading
예제에는 넣지 않는다. 따라서 초기 구현도 `h1`~`h4`에는 `page`를 넣지 않는다. 페이지를
알 수 없는 text/table/image는 0을 사용할 수 있다. ETL `pageId`와 HRC 페이지 번호의
기준은 실제 결과로 확인해야 한다.

### 헤딩의 의미

`h1`~`h4`는 단순 텍스트가 아니라 이후 본문 청크에 적용되는 계층 메타데이터다.

```jsonl
{"item":"h1","value":"대출상품"}
{"item":"h2","value":"금리 안내"}
{"item":"text","value":"최저 연 3.5%","page":1}
```

KL 적재 후 마지막 `text`에는 `대출상품 > 금리 안내`가 메타로 연결되는 식이다.

### 표

```json
{
  "item": "table",
  "value": "<table><tr><td>...</td></tr></table>",
  "type_property": {"title": ""},
  "page": 1
}
```

`type_property.title`은 제목이 없어도 빈 문자열로 반드시 넣는다.

### 이미지

```json
{
  "item": "image",
  "value": "BIN0001.jpg",
  "type_property": {
    "title": "",
    "width": 70,
    "height": 100,
    "ratio": "11%"
  },
  "page": 1
}
```

이미지 파일은 `img_dir`에 실제로 존재해야 하며 최종 `_img.zip` 안의 파일명과 일치해야 한다. 폭과 높이는 가이드상 mm 단위다.

### Custom metadata

```json
{
  "item": "text",
  "value": "최저 연 3.5%",
  "page": 1,
  "cust_meta": [
    {"name": "cust_attr1", "value": "문서ID"},
    {"name": "cust_sattr1", "value": "대출금리"}
  ]
}
```

- `cust_attr1`~`cust_attr10`: 원본 표의 표현상 조회 only, 임베딩에는 포함되지 않음
- `cust_sattr1`~`cust_sattr5`: 검색·조회용, 임베딩에 포함됨

README 앞부분의 `cust_arrt`/`cust_mata` 표기는 오타로 보이며 후반 정의표와 샘플의 `cust_attr`/`cust_meta`를 기준으로 해야 한다.

번호별 의미는 프로젝트가 정의해야 하지만 아직 확정하지 않는다. 특히 `cust_sattr`는
임베딩과 검색에 포함되므로 Retrieval 호출부가 실제로 사용할 상품군·문서 유형·심의 유형을
확인한 뒤 매핑해야 한다. 현재 기본 exporter는 `cust_meta`를 출력하지 않는다.

## 1.11 INFO JSON과 `doc_data.json`

`원본파일명_hrc.json`은 본문이 아니라 문서 정보다.

```json
{
  "name": "sample.pdf",
  "source": "/work/sample.pdf",
  "file_type": "pdf",
  "size": 68475,
  "title": "문서 제목",
  "parsed_status": "S",
  "page_info": [
    {"page": 1, "width": 595.3, "height": 841.9}
  ]
}
```

본문·임베딩의 중심은 `_hrc.jsonl`이고 `_hrc.json`은 필수 문서 INFO 파일이다.

INFO 샘플의 페이지 크기 단위는 입력 형식에 따라 다르게 보인다. HWP 예제는 21.0×29.7,
PDF 예제는 약 595.3×841.9이며, ETL Default JSON 예시는 1275×1650이다. ETL 값을 그대로
쓰면 렌더링 픽셀을 PDF point로 오인할 수 있으므로 실제 ETL 결과와 KL 수용 결과로 단위를
확정해야 한다. 현재 변환기는 ETL 값을 보존하지만 이 값은 최종 단위 확정 전 임시 구현이다.

`doc_data.json`은 KL에서 전달된 Doc Data를 변경해야 할 때만 만든다. README에 따르면 변경값은 VectorDB에만 반영된다. 원본 업무 시스템의 문서 자체를 수정하는 기능으로 이해하면 안 된다.

## 1.12 기존 예제를 그대로 복사하면 안 되는 이유

예제는 의도적으로 완성품이 아니며 다음 사항을 수정해야 한다.

1. `option` 디코딩이 주석 처리되어 있다.
2. `parse()`가 하드코딩된 Kubernetes 샘플 JSONL을 쓴다.
3. `parse()`의 예외 처리 구문에 문법 오류가 있다.

```python
except Exception as e:(
    write_parse_status(...))
```

올바른 형태는 다음과 같다.

```python
except Exception as exc:
    write_parse_status(work_dir, "ERROR", str(exc))
```

4. 예제 `parse()`는 `_hrc.json` INFO 파일을 만들지 않는다.
5. JSONL에서 참조하는 이미지가 실제 `img_dir`에 생성되지 않는다.
6. `TIMEOUT = os.getenv("TIMEOUT", 600)`은 환경변수가 있으면 문자열이 되므로 `int(...)` 변환이 필요하다.
7. 결과를 한 번 반환하면 작업 디렉터리를 즉시 삭제하므로 재조회 정책을 확인해야 한다.
8. `parser_howto.txt`는 파싱 오류일 때 HTTP 200 + `ERROR`를 요구하지만 예제 `main.py`는 일부 오류를 HTTP 500으로 반환한다. 실제 구현은 포털 계약을 우선하여 정리해야 한다.
9. 타임아웃 시 작업 디렉터리를 삭제하면 KL이 `ERROR` 상태를 확인하지 못할 수 있다. 일정 시간 오류 상태를 보존하는 정책이 필요하다.

예제의 `DO NOT EDIT` 주석은 플랫폼 계약 부분을 임의로 바꾸지 말라는 의미로 이해해야 하지만, 예제 자체의 명백한 문법 오류와 미구현 코드를 그대로 보존하라는 뜻은 아니다.

## 1.13 이번 프로젝트에서 제거할 과거 구조

과거 PoC에서는 다음처럼 목적별 API를 추가했다.

- 규정문서 파싱 API
- 광고 심의 입력 파싱 API

이번 농협 등록본에서는 KL이 이미 정한 `/parsing` 하나가 문서 접수의 표준 진입점이다. 따라서 우선은 별도 `/ad/parsing`을 만들지 않고 `parse()` 내부에서 공통 흐름을 구현한다.

문서 유형별 처리가 필요하면 API를 나누는 대신 `option`, 파일 확장자, 문서 메타데이터 또는 후처리 설정으로 분기한다.

```text
POST /parsing
  -> parse(...)
       -> ETLwithLLM
       -> 공통 HRC 변환
       -> 필요할 때만 광고 후처리
```

이렇게 해야 KL 등록 계약은 하나로 유지하면서 내부 처리만 확장할 수 있다.
