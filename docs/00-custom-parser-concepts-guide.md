# Custom Parser 전체 개념과 코드 이해 가이드

이 문서는 `custom-parser`를 처음 보는 사람이 다음 질문에 스스로 답할 수 있도록 만든 내부 학습 문서다.

- 이 프로그램은 왜 필요한가?
- Knowledge Lake, Custom Parser, ETLwithLLM은 각각 무엇인가?
- `.sh`, `.whl`, FastAPI, Gunicorn 같은 파일과 도구는 왜 들어 있는가?
- 파일 하나가 입력된 뒤 어떤 코드가 어떤 순서로 실행되는가?
- 무엇이 농협이 정한 계약이고, 무엇이 우리 구현이며, 무엇이 아직 미확정인가?
- 직접 제대로 구현됐는지 확인하려면 무엇을 어떤 순서로 검사해야 하는가?

이 파일은 개인 학습용이므로 `.gitignore`에 파일 경로를 명시했다. 실제 계약의 최종 근거는 농협이 제공한 Custom Parser 예제와 ETLwithLLM API 가이드다.

---

## 1. 한 문장으로 설명하면

이 프로그램은 **Knowledge Lake가 보낸 원본 문서를 농협 ETLwithLLM에 다시 전달해 OCR·문서 구조 분석 결과를 받고, 그 결과를 Knowledge Lake가 받아들일 수 있는 HRC 파일로 변환해 돌려주는 중간 연결 프로그램**이다.

```text
Knowledge Lake
  -> 우리 Custom Parser
  -> ETLwithLLM DLA/OCR
  -> 우리 Custom Parser
  -> HRC 결과 ZIP
  -> Knowledge Lake 적재
  -> VectorDB
  -> 이후 별도 심의 서비스의 Retrieval
```

여기서 Custom Parser는 OCR 모델 자체가 아니다. 농협 OCR 서비스를 호출하고 결과 형식을 바꾸는 **어댑터이자 후처리 프로그램**이다.

---

## 2. 등장하는 시스템과 역할

### 2.1 Knowledge Lake(KL)

Knowledge Lake는 문서를 받아 파싱하고, 파싱 결과를 청크·임베딩·VectorDB 적재 흐름으로 넘기는 농협 내부 플랫폼으로 이해한다.

이번 프로그램과 관련된 KL의 역할은 다음과 같다.

1. 등록된 Custom Parser 서비스를 실행한다.
2. 문서와 option을 `POST /parsing`으로 보낸다.
3. 반환받은 UUID로 `GET /parsing/result/{uuid}`를 반복 호출한다.
4. 완료 ZIP의 HRC JSONL과 INFO JSON을 읽는다.
5. 이후 KL 내부 적재 절차를 수행한다.

중요한 점은 우리가 농협 밖에서 별도 서버를 계속 운영하는 구조가 아니라는 것이다. 우리는 소스코드를 제공하고, 농협 플랫폼이 그 코드를 자신의 실행 환경에서 서버 프로세스로 띄운다.

### 2.2 Custom Parser

Custom Parser는 KL의 기본 파서 대신 프로젝트별 처리를 수행하도록 등록하는 사용자 정의 파서다.

이번 구현에서 하는 일은 다음과 같다.

- KL의 문서 요청 접수
- 바깥쪽 작업 UUID 발급
- ETLwithLLM 분석 요청
- ETL 작업 상태 폴링
- Default JSON 조회
- Default JSON을 내부 중간 모델로 정규화
- HRC JSONL과 INFO JSON 생성
- 결과 ZIP 반환

### 2.3 ETLwithLLM

ETLwithLLM은 원본 파일에 OCR과 문서 레이아웃 분석을 수행하는 별도 내부 서비스다. Custom Parser와 같은 프로그램이 아니다.

Custom Parser가 HTTP API로 ETLwithLLM을 호출한다. 현재 구현 범위는 가이드의 분석 요청, 상태 확인, 결과 목록 조회, 결과 내용 조회다.

### 2.4 OCR과 DLA

- **OCR(Optical Character Recognition)**: 이미지나 스캔 문서의 글자를 문자열로 읽는다.
- **DLA(Document Layout Analysis)**: 문서의 어느 영역이 제목, 본문, 표, 그림인지 분석한다.

글자만 읽으면 문서 구조가 사라질 수 있다. DLA는 OCR 문구에 위치와 영역 유형을 함께 부여해 후처리가 문서를 더 구조적으로 다루게 한다.

현재 기본값 `extract_type=dla`는 ETLwithLLM이 DLA 중심의 추출 경로를 사용하도록 요청하는 공개 설정이다. `CUSTOMIZE`는 이번 외부 API 연동 방식의 값이 아니며, ETLwithLLM 3장의 내부 확장 훅과 혼동하면 안 된다.

### 2.5 HRC

HRC는 KL이 Custom Parser 결과로 받는 구조화 문서 형식이다. 본문은 JSONL이며 각 줄에 다음 item 중 하나가 들어간다.

- `h1`, `h2`, `h3`, `h4`: 제목 계층
- `text`: 일반 텍스트
- `table`: 표
- `image`: 이미지 참조

예:

```jsonl
{"item":"h1","value":"상품 안내"}
{"item":"text","value":"가입 기간은 12개월입니다.","page":1}
{"item":"table","value":"<table>...</table>","type_property":{"title":""},"page":1}
```

JSONL은 JSON 배열이 아니다. **한 줄마다 완전한 JSON 객체 하나**가 있는 형식이다. 대용량 문서를 줄 단위로 처리하기 쉽다.

### 2.6 VectorDB와 Retrieval

- **임베딩**: 문구를 의미를 나타내는 숫자 벡터로 바꾸는 처리다.
- **VectorDB**: 임베딩 벡터를 저장하고 의미적으로 가까운 내용을 찾는 데이터베이스다.
- **Retrieval**: 이후 심의 프로그램이 VectorDB에서 필요한 문구나 문서를 검색·조회하는 단계다.

Custom Parser가 VectorDB에 직접 접속하는 것은 아니다. Custom Parser는 HRC ZIP을 KL에 반환하면 기본 역할이 끝난다. 적재와 Retrieval은 그 다음 단계다.

### 2.7 VLM

VLM(Vision-Language Model)은 이미지와 텍스트를 함께 이해하는 모델이다. 기존 시연용 파이프라인에서는 상품군 분류, 카드 경계, 템플릿 선택, 라벨링 등을 보조했다.

현재 농협 등록용 1차 버전에는 VLM을 넣지 않았다. 실제 내부 VLM 사용 가능 여부와 최종 광고 후처리 범위가 확정된 뒤 선택적으로 추가한다.

---

## 3. 서버와 API의 아주 기본적인 개념

### 3.1 서버와 클라이언트

- **서버**: 요청을 기다리다가 정해진 작업을 수행하고 응답한다.
- **클라이언트**: 서버에 요청을 보내는 쪽이다.

이 흐름에서는 역할이 한 번 바뀐다.

```text
KL --요청--> Custom Parser
KL은 클라이언트, Custom Parser는 서버

Custom Parser --요청--> ETLwithLLM
Custom Parser는 클라이언트, ETLwithLLM은 서버
```

### 3.2 API와 엔드포인트

API는 두 프로그램이 어떤 주소, 입력, 출력으로 통신할지 정한 계약이다. 엔드포인트는 그 계약의 개별 주소다.

- `POST /parsing`: 새 파싱 작업 생성
- `GET /parsing/result/{uuid}`: 작업 상태 또는 결과 조회
- `GET /health`: 서버 생존 확인

`POST`는 보통 새 작업이나 데이터를 전달할 때, `GET`은 상태나 결과를 읽을 때 쓴다.

### 3.3 HTTP 상태 코드와 업무 상태

두 종류의 상태를 구분해야 한다.

- **HTTP 상태 코드**: 통신 요청 자체의 처리 결과. 예: 200, 202, 500
- **업무 상태**: 문서 분석 작업의 상태. 예: `PARSING`, `DONE`, `ERROR`

이번 계약에서는 다음 조합이 가능하다.

| 상황 | HTTP | 본문 또는 결과 |
|---|---:|---|
| 작업 접수 성공 | 202 | UUID와 timeout |
| 아직 처리 중 | 200 | `{"status":"PARSING"}` |
| 파싱 작업 실패 | 200 | `{"status":"ERROR",...}` |
| 처리 완료 | 200 | ZIP 바이너리 |
| 없는 UUID 등 일반 오류 | 500 | 오류 JSON |

일반적인 REST API 관습과 다르게 보일 수 있지만, 여기서는 농협 예제 계약을 우선한다.

### 3.4 multipart/form-data

파일과 일반 문자열을 한 HTTP 요청에 같이 넣는 형식이다.

```text
src_file = 원본 PDF 파일
option   = Base64 인코딩된 JSON 문자열
```

FastAPI가 이 형식을 읽기 위해 `python-multipart` 패키지가 필요하다.

### 3.5 Base64

Base64는 바이너리나 특수문자가 섞인 데이터를 안전한 문자열 문자 집합으로 바꾸는 인코딩이다. 암호화가 아니며 누구나 다시 디코딩할 수 있다.

예를 들어 JSON 객체 `{}`의 Base64 값은 `e30=`이다. option에 비밀키가 들어 있다면 Base64로 보낸다고 안전해지는 것이 아니다.

### 3.6 UUID

UUID는 요청별 작업을 구분하는 식별자다. 현재 코드는 32자리 16진수 UUID를 만든다.

주의할 점은 작업 ID가 두 개라는 것이다.

- **KL/Custom Parser UUID**: KL이 우리 결과 API를 조회할 때 사용
- **ETL task_id/file_path**: Custom Parser가 ETL 상태를 조회할 때 사용

서로 다른 시스템의 ID이므로 혼용하면 안 된다.

### 3.7 비동기 처리와 폴링

OCR은 오래 걸릴 수 있다. 최초 요청 연결을 계속 열어 두는 대신 다음처럼 처리한다.

1. 서버가 작업을 접수하고 UUID를 즉시 반환한다.
2. 실제 파싱은 백그라운드에서 계속된다.
3. 호출자는 UUID로 결과 API를 반복 호출한다.

이 반복 조회가 **폴링(polling)**이다. 너무 자주 호출하면 서버 부하가 커지므로 간격과 전체 timeout이 필요하다.

### 3.8 MIME type과 ZIP

MIME type은 응답 데이터가 어떤 형식인지 알려 주는 HTTP 헤더 값이다. 완료 응답은 원본 예제에 맞춰 `application/x-zip-compressed`를 사용한다.

ZIP 내부에는 계약상 허용된 결과 파일만 루트에 있어야 한다.

```text
광고.pdf_hrc.jsonl     필수 본문
광고.pdf_hrc.json      필수 INFO
광고.pdf_img.zip       실제 image item이 있을 때만
doc_data.json          Doc Data를 실제 변경할 때만
```

---

## 4. Python 프로그램 실행에 필요한 기본 개념

### 4.1 Python 3.11

농협 실행 환경이 Python 3.11이라고 전달받았으므로, 로컬 테스트도 최종적으로 같은 버전에서 해야 한다. 다른 버전에서 테스트가 통과해도 3.11에서 문법이나 패키지 호환 문제가 날 수 있다.

### 4.2 모듈, 패키지와 import

- `.py` 파일 하나는 Python 모듈이다.
- `service/`처럼 여러 모듈을 묶은 디렉터리는 Python 패키지다.
- `__init__.py`는 해당 폴더를 패키지로 인식시키는 전통적인 표시다.

예:

```python
from service.etl_client import EtlClient
```

현재 실행 스크립트가 `app_custom_parser`로 이동한 뒤 실행하므로 그 아래의 `service`를 import할 수 있다.

### 4.3 pip

`pip`는 Python 패키지를 설치하는 도구다. 인터넷이 되는 환경에서는 보통 PyPI에서 패키지를 내려받지만, 농협 폐쇄망에서는 인터넷 다운로드를 기대하면 안 된다.

### 4.4 requirements.txt

필요한 패키지와 버전을 기록하는 파일이다.

```text
python-multipart==0.0.17
```

`==`는 정확히 그 버전을 쓰겠다는 의미다. 재현성을 높이지만, 플랫폼 기본 패키지와 호환되는지도 확인해야 한다.

### 4.5 wheel과 `.whl`

Wheel은 Python 패키지를 설치하기 좋게 포장한 배포 파일이며 확장자가 `.whl`이다.

```text
python_multipart-0.0.17-py3-none-any.whl
```

이 이름은 대략 다음 의미다.

- `python_multipart`: 패키지 이름
- `0.0.17`: 버전
- `py3`: Python 3용
- `none-any`: 특정 운영체제나 CPU에 종속된 컴파일 바이너리가 없는 범용 wheel

농협 폐쇄망에서는 필요한 wheel을 미리 가져가야 한다. C/C++ 확장 패키지는 운영체제, CPU, Python 버전에 맞는 wheel이 필요할 수 있다.

### 4.6 wheelhouse

여러 wheel을 모아 둔 로컬 패키지 저장소를 보통 wheelhouse라고 부른다. 현재 `server/flow/whl/`이 그 역할을 한다.

설치 명령의 주요 옵션은 다음과 같다.

```bash
python -m pip install --no-index --no-deps --target custom_libs --find-links whl -r requirements.txt
```

- `--no-index`: 인터넷 패키지 저장소를 보지 않는다.
- `--no-deps`: 의존 패키지를 자동으로 추가 다운로드하지 않는다.
- `--find-links whl`: 이 폴더에서 wheel을 찾는다.
- `--target custom_libs`: 시스템 전체가 아니라 지정 폴더에 설치한다.
- `-r requirements.txt`: 명세 파일의 패키지를 설치한다.

### 4.7 SHA-256과 SHA256SUMS

SHA-256은 파일 내용을 대표하는 해시값이다. wheel이 전달 중 손상되거나 다른 파일로 바뀌지 않았는지 확인하는 데 쓴다.

해시가 같다고 패키지가 안전하다는 사실까지 보장하는 것은 아니다. 우리가 승인한 원본 파일과 동일하다는 것만 확인한다.

### 4.8 `custom_libs`와 `PYTHONPATH`

`pip --target`으로 설치한 라이브러리는 Python의 기본 검색 경로 밖에 있을 수 있다. `PYTHONPATH`에 `custom_libs`를 추가하면 Python이 그 폴더에서도 모듈을 찾는다.

---

## 5. `.sh` 파일과 Linux 셸의 기본 개념

### 5.1 `.sh` 파일

`.sh`는 셸 명령을 순서대로 적어 둔 스크립트다. 농협 플랫폼은 Linux 컨테이너 환경으로 보이므로 Windows PowerShell이 아니라 Bash 또는 POSIX shell 문법을 사용한다.

### 5.2 shebang

파일 첫 줄의 다음 표시는 어떤 프로그램으로 스크립트를 실행할지 뜻한다.

```bash
#!/bin/bash
```

또는:

```bash
#!/usr/bin/env sh
```

`bash` 전용 문법을 쓴다면 첫 형식처럼 Bash를 지정해야 한다.

### 5.3 환경변수와 `export`

환경변수는 실행 환경이 프로그램에 전달하는 설정값이다.

```bash
export FLOW_APP_NAME="app_custom_parser"
```

`export`하면 이 셸에서 실행한 Gunicorn과 Python 자식 프로세스도 값을 볼 수 있다. URL, workspace ID, 포트, 임시 경로처럼 환경마다 다른 값은 코드에 하드코딩하지 않고 환경변수로 주입하는 것이 일반적이다.

### 5.4 주요 플랫폼 경로

- `PATH_SOURCE`: 업로드된 소스 위치
- `PATH_TEMP`: 요청별 작업 파일을 둘 공유 임시 경로
- `PATH_MODEL`: 플랫폼 모델 경로
- `FLOW_APP_DIR`: 플랫폼이 별도로 지정한 앱 기준 디렉터리
- `CUSTOM_LIBS`: 추가 wheel 설치 위치

이 값들은 농협 플랫폼 실행 골격에 속하므로 공식 템플릿 없이 임의로 바꾸지 않는다.

### 5.5 실행 권한과 줄바꿈

Linux에서 `.sh`를 직접 실행하려면 실행 권한 비트가 필요하다. Git의 executable bit가 유지되는지도 확인해야 한다.

또한 Windows의 CRLF 줄바꿈이 셸에서 `^M` 오류를 만들 수 있다. `.gitattributes`로 `.sh`를 LF로 고정하고 `bash -n`으로 문법을 검사하는 것이 좋다.

### 5.6 `run-application.sh`

서버 실행 진입점이다. 주요 역할은 다음과 같다.

1. 플랫폼 경로 결정
2. 로그 설정 준비
3. `app_custom_parser` 디렉터리로 이동
4. `custom_libs`를 `PYTHONPATH`에 추가
5. Gunicorn 실행

### 5.7 `setup-application.sh`

배포 전에 실행 환경과 wheel을 확인하고, 폐쇄망 방식으로 필요한 추가 패키지를 `custom_libs`에 설치한다.

### 5.8 `test-application.sh`

기동된 API에 샘플 파일을 보내고, UUID를 받은 뒤 완료될 때까지 폴링하고, ZIP 계약을 검사하는 통합 테스트 스크립트다.

---

## 6. FastAPI, ASGI, Uvicorn, Gunicorn

이 네 용어는 같은 것이 아니다.

### 6.1 FastAPI

Python 함수로 HTTP API를 정의하는 웹 프레임워크다.

```python
app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "OK"}
```

FastAPI는 URL과 Python 함수를 연결하고, 요청 데이터를 읽고, 응답 JSON을 만드는 일을 돕는다.

### 6.2 ASGI

ASGI는 Python 비동기 웹 애플리케이션과 웹 서버가 통신하는 표준 인터페이스다. FastAPI 앱은 ASGI 애플리케이션이다.

### 6.3 Uvicorn

Uvicorn은 FastAPI 같은 ASGI 앱을 실제 네트워크 포트에서 실행하는 서버다.

### 6.4 Gunicorn

Gunicorn은 여러 worker 프로세스를 관리하는 프로세스 관리자 역할의 웹 서버다. 현재는 Uvicorn worker를 사용한다.

```text
Gunicorn master
  ├─ Uvicorn worker 1 -> FastAPI app
  ├─ Uvicorn worker 2 -> FastAPI app
  └─ ...
```

`gunicorn main:app`은 현재 디렉터리의 `main.py`에서 `app` 객체를 찾아 실행하라는 뜻이다.

### 6.5 worker

worker는 실제 요청을 처리하는 프로세스다. 여러 worker를 두면 동시에 여러 요청을 받을 수 있다. 그러나 각 프로세스의 메모리는 서로 공유되지 않는다.

그래서 작업 상태를 Python 전역 딕셔너리에만 저장하면 다른 worker가 볼 수 없다. 현재 코드가 공유 경로의 `genaikl.status` 파일을 쓰는 이유다.

### 6.6 BackgroundTasks와 subprocess

- FastAPI `BackgroundTasks`: HTTP 응답을 보낸 뒤 같은 서버 worker에서 후속 함수를 실행하게 한다.
- `subprocess`: 별도 Python 프로세스를 실행한다.

현재 코드는 BackgroundTask가 별도 parser subprocess를 시작하고 기다린다. OCR 작업을 웹 요청 처리와 격리하고 timeout을 적용할 수 있다.

단, worker가 강제 재시작되면 그 BackgroundTask도 영향을 받을 수 있다. 농협 플랫폼 운영 정책과 실제 장시간 작업 안정성은 현장 부하 테스트가 필요하다.

---

## 7. 컨테이너, 소스 등록과 마운트

### 7.1 컨테이너

컨테이너는 애플리케이션을 정해진 운영체제·라이브러리 환경 안에서 실행하는 단위다. Docker 이미지로 만드는 경우가 많다.

현재 이해로는 우리가 독자 Docker 이미지를 만들어 외부 서버로 운영하는 것이 아니라, 농협 플랫폼의 기존 실행 이미지에 Custom Parser 소스를 등록한다.

### 7.2 소스 업로드 또는 마운트

플랫폼은 등록한 소스 폴더를 컨테이너 내부 경로에 보이게 해야 한다. 이 동작을 넓게는 마운트라고 설명할 수 있다.

```text
업로드된 server/flow
  -> 컨테이너의 /project/work/flow 또는 /infer-model/.../flow
```

이것은 ETLwithLLM 3장의 `custom_extension` 마운트와는 다른 통합 방식이다. 현재 구현은 KL Custom Parser 소스로 실행되고, 내부에서 ETLwithLLM 공개 HTTP API를 호출한다.

### 7.3 왜 `run-application.sh`를 보존하는가

플랫폼은 약속된 경로와 환경변수로 이 스크립트를 실행할 가능성이 높다. 소스 내부 Python 로직이 맞아도 실행 스크립트가 플랫폼 계약과 다르면 서버가 아예 뜨지 않는다.

---

## 8. 현재 폴더의 파일별 역할

```text
custom-parser/
├─ README.md
├─ docs/
├─ tests/
└─ server/flow/
   ├─ run-application.sh
   ├─ setup-application.sh
   ├─ test-application.sh
   ├─ verify-result.py
   ├─ requirements.txt
   ├─ platform-requirements.txt
   ├─ verify_wheels.py
   ├─ whl/
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

### 루트

- `README.md`: 저장소 목적, 실행 흐름, 현재 범위와 미확정 사항
- `.gitignore`: Git에 올리지 않을 로컬·민감·생성 파일
- `.gitattributes`: 셸 줄바꿈과 텍스트 파일 처리 규칙
- `docs/`: 두 원본 자료 분석과 통합 설계
- `tests/`: 네트워크 없이 실행하는 단위·계약 테스트

### `server/flow`

- `run-application.sh`: 농협 플랫폼 서버 기동 진입점
- `setup-application.sh`: Python 3.11·기본 패키지·wheel 확인 및 오프라인 설치
- `test-application.sh`: 실제 실행 서버를 대상으로 전체 API 흐름 검사
- `verify-result.py`: 다운로드한 결과 ZIP의 이름과 HRC 기본 구조 검사
- `requirements.txt`: 함께 설치할 추가 패키지
- `platform-requirements.txt`: 플랫폼 이미지에 이미 있어야 하는 패키지 참고 버전
- `verify_wheels.py`: wheel의 SHA-256 검사
- `whl/`: 폐쇄망에 함께 가져갈 wheel과 해시 목록

`test-application.sh`는 Python 패키지 외에도 운영체제 명령인 `curl`, `jq`, `unzip`을
사용한다. 이 도구들이 농협 등록 이미지에 있는지 확인해야 하며, 없으면 테스트 스크립트를
Python 표준 라이브러리 기반으로 바꾸거나 도구 제공 방식을 협의해야 한다.

### `app_custom_parser`

- `main.py`: KL이 호출하는 FastAPI API, 파일 저장, UUID, 상태 조회, ZIP 반환
- `gunicorn_config.py`: 포트, worker 수, timeout, 로그 등 서버 프로세스 설정

### `service`

- `config.py`: option과 환경변수에서 ETL 설정을 읽고 검증
- `etl_client.py`: ETLwithLLM HTTP 호출과 내부 폴링
- `etl_adapter.py`: Default JSON을 안정적인 내부 모델로 변환
- `document_model.py`: Page, Region 등 내부 데이터 구조
- `hrc_exporter.py`: 내부 문서를 HRC JSONL·INFO JSON으로 출력
- `result_contract.py`: 허용 결과만 검사하고 ZIP 생성
- `status.py`: `genaikl.status` 원자적 읽기·쓰기
- `parsing_service.py`: 실제 `parse(work_dir, img_dir, file_path, option)` 진입점과 전체 조립

---

## 9. 파일 한 건의 정확한 실행 순서

### 9.1 서버 기동

```text
농협 플랫폼
  -> run-application.sh
  -> app_custom_parser 디렉터리로 이동
  -> gunicorn main:app --config gunicorn_config.py
  -> FastAPI가 포트에서 요청 대기
```

### 9.2 KL 요청 접수

```text
KL POST /parsing
  -> main.py가 src_file과 option 수신
  -> option Base64 디코딩
  -> 안전한 파일명 검사
  -> UUID 작업 디렉터리 생성
  -> 원본 파일 스트리밍 저장
  -> genaikl.status = PARSING
  -> parser subprocess 예약
  -> HTTP 202 + UUID 반환
```

파일을 한 번에 메모리에 올리지 않고 일정 크기씩 쓰는 것을 스트리밍이라고 한다.

### 9.3 별도 parser 프로세스

```text
main.py BackgroundTask
  -> python -m service.parsing_service ...
  -> option을 표준입력(stdin)으로 전달
  -> parse(...)
```

option을 파일로 저장하거나 명령행 인자로 노출하지 않아 URL이나 향후 민감값이 작업 파일·프로세스 목록에 남는 범위를 줄였다.

### 9.4 ETLwithLLM 호출

```text
EtlConfig.from_sources()
  -> URL, author, ws_id, prj_config 결정

EtlClient.start()
  -> POST /api/v1/etl/auto/start

EtlClient.wait_until_done()
  -> GET /api/v1/file/info 반복
  -> 000/001 대기, 002 완료, 999 오류

EtlClient.list_results()
  -> GET /api/v1/file/result/list

EtlClient.get_result_document()
  -> GET /api/v1/file/result/doc
```

### 9.5 변환과 결과 생성

```text
ETL Default JSON
  -> etl_adapter.convert_default_json()
  -> NormalizedDocument(Page, Region)
  -> hrc_exporter.export_hrc()
  -> 광고.pdf_hrc.jsonl
  -> 광고.pdf_hrc.json
  -> result_contract.collect_result_files()
  -> status DONE
```

중간 모델을 두는 이유는 ETL 응답을 읽는 코드와 KL HRC를 쓰는 코드를 분리하기 위해서다. 나중에 광고 후처리를 추가하더라도 ETL 응답 원문을 여기저기 직접 참조하지 않게 된다.

### 9.6 KL 결과 조회

```text
KL GET /parsing/result/{uuid}
  -> PARSING이면 상태 JSON
  -> ERROR이면 오류 JSON 후 작업 폴더 삭제
  -> DONE이면 허용 파일 검사
  -> ZIP을 메모리에 만든 뒤 작업 폴더 삭제
  -> ZIP 반환
```

결과를 한 번 반환한 뒤 같은 UUID를 다시 조회하면 원본 예제 동작에 맞춰 500이 된다. 즉 현재 결과 조회는 일회성이다.

---

## 10. 설정값이 들어오는 위치와 우선순위

현재 ETL 설정 우선순위는 다음과 같다.

```text
option.etl
  > option.parser_info.prop
  > 환경변수
```

주요 값:

- `base_url`: ETL 서버 주소. 원본 KL의 `prop.url`도 별칭으로 수용
- `author`: ETL 분석 요청 작성자
- `ws_id`: 농협이 만든 ETL workspace 식별자
- `prj_config`: `extract_type`, 표 변환 등 분석 설정
- 연결 timeout, 전체 분석 timeout, 폴링 간격

`parser_info.prop.key`는 일반 OCR 공급자 정보 예제에 있지만 ETLwithLLM 가이드에는 어느 HTTP 헤더로 전달할지 근거가 없다. 따라서 현재 임의로 Authorization 헤더에 넣지 않는다. 실제 농협 ETL 인증 규격을 받으면 그때 구현한다.

---

## 11. ETL 요청과 Default JSON

### 11.1 분석 요청

ETL 요청은 `multipart/form-data`이며 대략 다음 두 필드를 보낸다.

- `upfiles`: 원본 파일
- `tr_data`: JSON을 문자열로 직렬화한 값

```json
{
  "author": "provided-author",
  "ws_id": "provided-workspace-id",
  "res_type": ["default"],
  "prj_config": {
    "extract_type": "dla",
    "table_to_struct": "html"
  },
  "meta_info": {}
}
```

### 11.2 `extract_type`

가이드에서 확인된 공개 값은 다음과 같다.

- `all`: 전체 추출 경로
- `dla`: DLA 기반 분석
- `parser`: parser 기반 추출

정확한 내부 실행 차이와 어떤 문서 형식에 어떤 값을 쓸지는 실제 농협 workspace 설정과 결과를 비교해야 한다. 현재 구현은 `dla`를 기본으로 사용하며 `customize`는 거부한다.

### 11.3 상태 코드

- `000`: 대기 또는 초기 상태
- `001`: 처리 중
- `002`: 완료
- `999`: 오류

이 값은 HTTP 200/500 같은 상태 코드가 아니라 ETL 응답 JSON 안의 `chunk_status`다.

### 11.4 Default JSON

Default JSON은 대략 다음 계층이다.

```text
문서
  └─ pages[]
      ├─ pageId
      ├─ width, height
      └─ paragraphs[]
          ├─ paragraphId
          ├─ type
          ├─ contents
          ├─ bbox
          ├─ confidence
          ├─ lines
          └─ cells
```

`bbox`는 영역을 감싸는 다각형 좌표다. 현재 어댑터는 원본 polygon을 보존하고, 편의를 위해 `[left, top, right, bottom]` 직사각형도 계산한다.

---

## 12. HRC 변환에서 확정된 것과 미확정인 것

### 12.1 현재 구현한 보수적 변환

- ETL `Title`이고 `section_level`이 1~4이면 `h1`~`h4`
- ETL `Table`이면 `table`
- 그 외 내용이 있는 영역은 `text`
- 제목에는 원본 예제에 맞춰 `page`를 넣지 않음
- `text`, `table`, `image`에만 `page` 사용
- 빈 문구는 출력하지 않음
- 실제 crop 이미지가 없는 Figure는 OCR 문구를 `text`로 보존
- 미확정 `cust_meta`를 만들지 않음
- 비표준 `doc_data_update`를 받지 않음

### 12.2 아직 현장 확인이 필요한 것

- ETL `pageId`가 0부터인지 1부터인지
- HRC `page`가 어떤 번호 기준을 요구하는지
- ETL width/height 픽셀을 HRC INFO에 그대로 넣어도 되는지
- PDF point, mm, pixel 사이 변환이 필요한지
- Figure 실제 이미지 파일을 어떤 API나 결과에서 얻는지
- `cust_attr1~10`, `cust_sattr1~5`의 프로젝트별 의미
- `doc_data.json`에서 실제로 변경할 필드
- KL이 빈 문서, 추가 필드, Unicode 파일명을 어떻게 검증하는지

이 항목을 모르면서 임의 값을 넣으면 문법적으로는 유효해도 VectorDB에 잘못된 의미가 적재될 수 있다.

### 12.3 `cust_attr`와 `cust_sattr`

현재 자료로 확인된 차이만 기억한다.

- `cust_attr1~10`: 조회용, 임베딩에는 포함되지 않는 필드
- `cust_sattr1~5`: 검색·조회에 사용되고 임베딩에도 포함되는 필드

번호별 의미는 우리 프로젝트와 심의 Retrieval 방식에 맞춰 합의해야 한다. 현재는 출력하지 않는 것이 의도된 안전한 상태다.

### 12.4 `doc_data.json`

KL이 보낸 Doc Data 중 VectorDB 쪽에 반영할 값을 Custom Parser가 실제로 변경해야 할 때만 만드는 조건부 결과다.

이 파일은 원본 업무 시스템 파일이나 원본 DB 레코드를 수정하는 기능이 아니다. KL이 이후 적재에 사용하는 Doc Data의 변경 요청으로 이해한다.

---

## 13. 지켜야 할 외부 계약과 바꿔도 되는 내부 구현

### 13.1 공식 확인 없이 바꾸면 안 되는 부분

- 플랫폼의 `run-application.sh` 외곽 골격과 경로 규칙
- `gunicorn_config.py`의 플랫폼 환경 감지·포트·로그 설정
- `POST /parsing` 경로와 multipart 필드명 `src_file`, `option`
- HTTP 202 응답의 `result`, `body.uuid`, `body.timeout`
- `GET /parsing/result/{uuid}` 경로
- `PARSING`, `ERROR`, 완료 ZIP 응답 형태
- `parse(work_dir, img_dir, file_path, option)` 이름과 인자 순서
- 확장자를 포함한 결과 파일명
- HRC 허용 item과 필수 필드
- 결과 ZIP에 허용된 파일 종류

### 13.2 필요에 따라 바꿀 수 있는 내부 구현

- ETL HTTP 클라이언트의 내부 코드
- Default JSON의 검증과 중간 모델
- 읽기 순서·영역 조립 로직
- 광고 상품군·템플릿·라벨링 로직
- 테스트 구조
- 내부 함수와 파일 분리 방식. 단, 최종 업로드 폴더 제약을 만족해야 함

### 13.3 예제의 오류와 미구현 부분

예제가 계약의 근거라고 해서 명백한 Python 문법 오류나 샘플용 하드코딩까지 그대로 유지할 필요는 없다. `DO NOT EDIT`로 표시된 플랫폼 외곽은 보존하고, `parse()` 같은 프로젝트 구현 영역의 미구현·오류는 올바르게 구현한다.

---

## 14. 직접 검증하는 방법

검증은 네 단계로 나눈다. 앞 단계가 통과했다고 다음 단계까지 증명되는 것은 아니다.

### 14.1 1단계: 정적 대조

코드를 실행하지 않고 농협 원본과 비교한다.

확인 목록:

- `run-application.sh`의 `DO NOT EDIT` 영역이 원본과 같은가?
- `gunicorn_config.py`의 플랫폼 설정이 원본과 같은가?
- `main.py`의 엔드포인트, 필드명, 상태 코드, MIME이 같은가?
- 결과 조회 UUID가 정확히 32자리 16진수인지 검사한 뒤 작업 경로를 만드는가?
- `parse()`의 이름과 네 인자가 유지됐는가?
- 결과 파일명에 원본 확장자가 포함되는가?
- ZIP 안에 허용 파일 외 디버그 JSON이나 로그가 들어가지 않는가?

유용한 명령:

```bash
git diff --no-index 원본/run-application.sh 현재/run-application.sh
git diff --no-index 원본/gunicorn_config.py 현재/gunicorn_config.py
bash -n server/flow/run-application.sh
bash -n server/flow/setup-application.sh
bash -n server/flow/test-application.sh
```

### 14.2 2단계: 로컬 단위·계약 테스트

반드시 Python 3.11에서 실행한다.

```bash
python --version
python -m unittest discover -s tests -v
```

확인해야 할 결과:

- 전체 테스트 수가 예상과 같은가?
- 실패뿐 아니라 `skipped`도 0인가?
- ETL mock 흐름이 `start -> info -> list -> doc` 순서인가?
- `extract_type=dla`, `res_type=["default"]`가 실제 요청에 들어가는가?
- HRC heading에 `page`가 없는가?
- 미확정 `cust_meta`가 없는가?
- 결과 파일명이 `광고.pdf_hrc.*`인가?
- option이 파일이나 명령행에 남지 않는가?

### 14.3 3단계: 로컬 서버 통합 테스트

농협 플랫폼과 같은 기본 패키지가 있는 Linux/Python 3.11 환경에서 수행한다.

```bash
server/flow/setup-application.sh
server/flow/run-application.sh
server/flow/test-application.sh sample.pdf BASE64_OPTION
```

이 단계에서는 FastAPI import, Gunicorn 기동, 포트, multipart 수신, 백그라운드 subprocess, 폴링, ZIP 다운로드까지 실제로 확인한다.

ETL 주소가 없다면 mock ETL HTTP 서버를 따로 띄워 전송되는 multipart와 API 순서를 확인해야 한다. Python 객체를 주입한 단위 테스트만으로 실제 HTTP multipart 구현까지 증명되지는 않는다.

### 14.4 4단계: 농협 현장 통합 테스트

최종적으로만 확인 가능한 항목이다.

1. 최신 등록 템플릿에 소스 업로드
2. 플랫폼이 `run-application.sh`를 정상 실행하는지 확인
3. `/health` 확인
4. KL에서 실제 문서를 `/parsing`으로 전송
5. Custom Parser 컨테이너에서 ETL URL 접근 확인
6. 실제 `author`, `ws_id`, 신청된 `prj_config`로 분석 요청
7. 상태 000/001/002 확인
8. Default JSON 원본 보관
9. HRC ZIP 수용 확인
10. KL 적재 및 VectorDB 반영 확인
11. page 번호·INFO 단위 확인
12. 합의한 `cust_meta`를 넣은 뒤 필터·의미 검색 확인

### 14.5 결과를 눈으로 확인하는 최소 방법

ZIP을 열고 다음을 직접 확인한다.

- 파일명이 입력 파일명과 정확히 연결되는가?
- JSONL을 한 줄씩 JSON 파싱할 수 있는가?
- 원본 문서의 모든 중요한 문구가 빠짐없이 있는가?
- 제목과 본문 순서가 사람이 읽는 순서와 비슷한가?
- 표가 HTML 구조를 유지하는가?
- 페이지 번호가 원본 페이지와 맞는가?
- INFO JSON의 페이지 크기가 KL 화면·검색 근거 좌표와 일치하는가?
- 결과 ZIP에 원본 파일, 상태 파일, ETL 원본 응답, 로그가 섞이지 않았는가?

---

## 15. 테스트 종류를 구분해야 하는 이유

### 단위 테스트

함수 하나나 작은 모듈을 격리해 검사한다. 빠르지만 실제 네트워크와 플랫폼을 증명하지 않는다.

### 계약 테스트

입출력 이름, HTTP 상태, JSON 구조, 파일명처럼 외부 시스템과 약속한 형식을 검사한다.

### mock 테스트

실제 ETL 대신 가짜 응답을 사용한다. 우리 흐름과 오류 처리는 검사할 수 있지만 실제 ETL 응답이 가정과 같은지는 증명하지 못한다.

### 통합 테스트

FastAPI, subprocess, HTTP 전송, ETL 또는 KL처럼 여러 구성요소를 실제로 연결한다.

### 회귀 테스트

이미 맞았던 결과가 코드 수정 후 깨지지 않았는지 같은 입력·기대 결과로 반복 검사한다.

“15개 테스트 통과”는 좋은 근거지만, 실제 농협 ETL·KL 통합 성공과 같은 의미는 아니다.

---

## 16. 보안과 운영 관점

### 16.1 비밀정보

다음 값은 Git, 로그, 샘플 option에 넣지 않는다.

- 실제 내부 IP와 URL
- API key와 접근 토큰
- 비밀번호
- 실제 `author`, `ws_id` 중 보안상 공개하면 안 되는 값
- 개인정보가 포함된 문서

### 16.2 option 전달

현재 option은 Base64 디코딩 후 subprocess의 표준입력으로 전달하며 별도 `option.json`을 만들지 않는다. 다만 프로세스 메모리와 애플리케이션 로그까지 완전히 비밀 저장소가 되는 것은 아니다. 예외 메시지에 전체 option을 출력하지 않아야 한다.

### 16.3 작업 디렉터리

원본 문서와 생성 결과가 UUID 폴더에 임시 저장된다. 완료·오류 결과 조회 후 삭제하며, KL이 조회하지 않은 작업은 보존 기간이 지난 뒤 새 요청 시 정리한다.

결과 조회 URL의 UUID는 외부 입력이다. 이를 검증하지 않고 `PATH_TEMP`와 바로 조합한 뒤
`shutil.rmtree()`를 호출하면 `..` 같은 값으로 의도한 작업 폴더 밖을 가리키는 경로 조작
위험이 생긴다. 따라서 삭제 전 UUID를 32자리 소문자 16진수로 검증하고, 최종 resolve된
경로가 `PATH_TEMP` 바로 아래인지 다시 확인해야 한다. 이 검증은 농협의 정상 UUID 계약을
바꾸지 않는 방어 로직이다.

운영에서는 다음도 확인해야 한다.

- 디스크 용량 제한
- 동시에 큰 문서가 들어올 때 사용량
- 삭제 실패 로그
- 개인정보 보존 기간
- pod 재시작 시 남은 작업 처리

### 16.4 로그

플랫폼 로그 설정은 원본 실행 스크립트와 Gunicorn 설정을 따른다. ETL 응답 전체나 문서 내용, 비밀키를 로그에 남기지 않는 것이 원칙이다.

---

## 17. 현재 1차 버전에 없는 기능

다음은 누락이라기보다 아직 범위를 확정하지 않아 의도적으로 넣지 않은 기능이다.

- 광고 문구의 고급 읽기 순서 보정
- 여러 DLA 영역의 광고 의미 단위 조립
- 상품군 분류
- 광고 템플릿 선택
- 구분값 라벨링
- 농협 내부 VLM 호출
- Figure crop 및 `_img.zip`
- 확정 `cust_meta`
- `doc_data.json` 변경
- VectorDB 직접 적재
- Retrieval과 광고 심의 실행
- ETL 로그인·workspace 생성
- 근거 없는 `prop.key` 인증 헤더 사용

최종 요구가 “ETL 결과를 HRC로만 변환”인지 “광고 심의용 라벨링까지 수행”인지에 따라 2차 구현 범위가 달라진다.

---

## 18. 다른 사람에게 설명할 때의 1분 요약

다음처럼 설명할 수 있다.

> 농협 Knowledge Lake가 문서를 저희 Custom Parser의 `/parsing` API로 보내면, 저희 코드는 바로 UUID를 돌려주고 별도 프로세스에서 ETLwithLLM 분석 API를 호출합니다. ETL 상태를 폴링해 완료되면 Default JSON을 받아 제목·본문·표 형태의 KL HRC JSONL과 문서 INFO JSON으로 변환합니다. KL은 UUID로 결과를 폴링하다 ZIP을 받아 이후 VectorDB 적재를 수행합니다. 현재 버전은 농협 DLA/OCR 결과를 HRC로 안전하게 전달하는 최소 버전이고, 광고 템플릿·라벨링, `cust_meta`, 이미지 crop은 실제 KL·Retrieval 규격을 확인한 뒤 확장할 예정입니다. 서버는 저희가 외부에서 운영하는 것이 아니라 농협 플랫폼이 등록된 FastAPI 소스를 Gunicorn으로 실행합니다.

---

## 19. 자주 헷갈리는 질문

### Q. 농협에 FastAPI 서버가 이미 있으니 우리는 함수만 주면 되는가?

플랫폼의 실행 환경은 있지만, KL이 호출할 FastAPI 앱 코드와 실행 스크립트는 등록 소스에 포함된다. 농협 플랫폼이 우리 코드를 실행해 서버를 띄우는 구조다.

### Q. 이 저장소를 Docker 이미지로 만들어 전달해야 하는가?

현재 미팅 이해로는 소스코드 제공형이다. 독자 Docker 이미지 전달이 필요하다고 확정된 근거는 없다. 최신 등록 템플릿을 우선한다.

### Q. `custom_extension.transform()`을 사용하는가?

현재 방식에서는 사용하지 않는다. Custom Parser의 `parse()`에서 ETLwithLLM 공개 API를 호출한다.

### Q. `kl_parser`가 ETL API를 호출하는가?

현재 새 저장소에서는 과거 `kl_parser`라는 이름 대신 `main.py`가 KL 통신, `parsing_service.py`와 `etl_client.py`가 ETL 연동을 담당하도록 역할을 나눴다.

### Q. 왜 기존 광고 파싱 결과 JSON을 그대로 반환하지 않는가?

KL Custom Parser 결과 계약은 HRC JSONL·INFO JSON 중심이다. 광고용 sidecar는 별도 업무 산출물이며 KL 결과 ZIP에 임의로 섞지 않는다.

### Q. 왜 `cust_meta`가 아직 없는가?

번호별 의미와 Retrieval 사용법이 확정되지 않았기 때문이다. 잘못 넣으면 검색 품질과 적재 의미를 망칠 수 있어 현장 확인 전에는 생략한다.

### Q. 테스트가 모두 통과하면 완성인가?

아니다. 로컬 테스트는 우리 코드가 가정대로 동작한다는 뜻이다. 실제 ETL 응답, 플랫폼 경로, HRC 수용, VectorDB 적재는 농협 환경에서 따로 확인해야 한다.

---

## 20. 최종 체크 포인트

다른 사람에게 전달하거나 농협에 등록하기 전 최소한 다음 질문에 답할 수 있어야 한다.

- 누가 `/parsing`을 호출하는가?
- 누가 ETLwithLLM을 호출하는가?
- 두 종류의 작업 ID는 무엇인가?
- `run-application.sh`, `main.py`, `parse()` 세 진입점의 차이는 무엇인가?
- FastAPI, Uvicorn, Gunicorn의 역할은 각각 무엇인가?
- wheel을 왜 함께 가져가며 `--no-index`는 왜 쓰는가?
- Default JSON과 HRC JSONL은 어떻게 다른가?
- 결과 파일명과 ZIP 허용 목록은 무엇인가?
- 무엇이 공식 계약이고 무엇이 아직 가정인가?
- 로컬 mock 테스트로 증명되지 않는 것은 무엇인가?
- 실제 농협 환경에서 어떤 순서로 확인해야 하는가?

이 질문에 설명할 수 있으면 현재 `custom-parser` 폴더의 목적과 실행 구조를 이해한 것이다.
