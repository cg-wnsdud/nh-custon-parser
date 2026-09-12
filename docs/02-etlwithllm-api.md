# 2. ETLwithLLM API 분석

## 2.1 이번 프로젝트에서 ETLwithLLM의 역할

ETLwithLLM은 KL Custom Parser 그 자체가 아니다. Custom Parser가 원본 PDF·이미지·문서를 넘겨 농협 내부 DLA/OCR 결과를 받기 위해 호출하는 **내부 분석 서비스**다.

```text
KL이 원본 파일을 Custom Parser에 전달
  -> Custom Parser가 동일한 원본 파일을 ETLwithLLM에 업로드
  -> ETLwithLLM이 OCR + 문서 레이아웃 분석
  -> Custom Parser가 Default JSON을 조회
```

농협 측이 workspace를 생성해 필요한 값을 제공하므로 로그인, 사용자 등록, workspace
생성은 이번 구현 범위가 아니다. API 가이드 28쪽의 1.16부터 1.20까지가 직접 구현할
범위이며, 필요한 API는 네 가지다.

| 순서 | API | 역할 |
|---:|---|---|
| 1 | `POST /api/v1/etl/auto/start` | 원본 파일 분석 요청 |
| 2 | `GET /api/v1/file/info?file_path=...` | 분석 상태 확인 |
| 3 | `GET /api/v1/file/result/list?docPath=...` | 생성된 결과 파일 목록 조회 |
| 4 | `GET /api/v1/file/result/doc?docResultPath=...` | 선택한 결과 파일 내용 조회 |

편의 API로 다음도 있다.

```http
GET /api/v1/file/result/json/type?doc_path=...&res_type=default
```

현장 서버가 이 API를 동일하게 지원하는지 확인되면 결과 목록과 파일 선택 단계를 줄일 수 있다. 최초 구현은 가이드의 기본 흐름인 목록 조회 후 내용 조회를 기준으로 한다.

## 2.2 분석 요청 API

### 요청

```http
POST /api/v1/etl/auto/start
Content-Type: multipart/form-data
Accept: application/json
```

multipart 필드:

| 키 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `tr_data` | JSON 문자열 | O | 분석 설정 |
| `upfiles` | 파일 목록 | O | 분석할 원본 파일 하나 이상 |

`tr_data`는 JSON 객체 자체가 아니라 multipart의 문자열 값으로 보낸다.

```json
{
  "author": "service-user",
  "ws_id": "workspace-id",
    "res_type": ["default"],
  "prj_config": {
    "extract_type": "dla"
  },
  "meta_info": {}
}
```

### `tr_data` 필드

| 필드 | 필수 | 기본값 | 의미 |
|---|---:|---|---|
| `author` | O | 없음 | 사용자 또는 서비스 계정명 |
| `ws_id` | O | 없음 | 워크스페이스 ID |
| `callback_url` | X | `null` | 완료 결과를 받을 콜백 URL |
| `res_type` | X | `default` | 생성하거나 돌려받을 결과 유형 |
| `prj_config` | X | 기본 설정 | DLA 분석 옵션 |
| `meta_info` | X | `null` | 결과에 포함할 부가 메타데이터 |

이번 Custom Parser에는 바깥쪽 KL 폴링이 이미 존재하므로 초기 구현에서는 ETL 콜백보다 **Custom Parser 내부 폴링**이 단순하다. `callback_url`은 사용하지 않아도 된다.

### `res_type`

| 값 | 생성 결과 |
|---|---|
| `default` | `[파일명].json`, DLA 기본 구조 |
| `pages` | `[파일명]_pages.json`, 전체 페이지 contents |
| `page_grouped` | `[파일명]_page_grouped.json`, 페이지별 그룹 |
| `figure` | crop 이미지 파일을 multipart로 전달 |
| `figure_base64` | crop 이미지를 binary 형태로 전달 |
| `chunk_data` | custom 결과용 chunk 파일 |

HRC 변환에 가장 많은 구조 정보가 필요한 현재 목적에는 `default`가 기준이다. `page_grouped`는 문장만 필요한 단순 처리에는 편하지만 bbox·유형·신뢰도·표 셀 같은 정보가 줄어들 수 있으므로 주 입력으로 삼지 않는다.

### `prj_config.extract_type`

공개 API의 정확한 키는 `extract_type`이다.

| 값 | 의미 | 이번 프로젝트 |
|---|---|---|
| `all` | DLA 파싱과 직접 파서를 모두 실행 | 두 결과가 모두 필요한 문서에 한해 검토 |
| `dla` | DLA/OCR 파싱 실행 | PDF·광고 문서의 우선 후보 |
| `parser` | HWPX·DOCX 직접 파싱 실행 | 직접 파서가 필요한 오피스 문서 후보 |

기본값은 `dla`다. 값을 생략할 수도 있지만 요청 의도를 명확히 하고 회귀 테스트가 가능하도록 초기 구현에서는 `"extract_type":"dla"`를 명시한다.

이 공개 API의 값에는 `customize`가 없다. 3장의 내부 `ExtractType.CUSTOMIZE`와 혼동하면 안 된다.

### 그 밖의 `prj_config`

| 키 | 선택값 | 기본값 | 의미 |
|---|---|---|---|
| `table_to_struct` | `html`, `md` | `html` | 표를 JSON에 저장하는 방식 |
| `tsr_model_name` | `tsr-vis`, `tsr-sem` | `tsr-vis` | 표 구조 인식 모델 |
| `n_columns` | `1`, `-1` | `-1` | 단순 순서 또는 정렬 알고리즘 |
| `rm_overlap_dla_flag` | bool | `true` | 겹치는 DLA 항목 제거 |
| `ocr_only` | bool | `false` | OCR만 사용할지 OCR+PDF reader를 사용할지 |
| `adjusting_process` | bool | `false` | 북마크 추출 사용 여부 |
| `merge_unknown_type` | bool | `true` | Unknown 유형 병합 여부 |
| `draw_viz` | bool | `true` | DLA 시각화 파일 생성 |
| `draw_tsr` | bool | `true` | TSR 시각화 파일 생성 |
| `draw_sort` | bool | `false` | 정렬 시각화 파일 생성 |
| `dla_score_th` | 0.0~1.0 | 0.5 | DLA confidence threshold |
| `str_score_th` | 0.0~1.0 | 0.5 | STR confidence threshold |
| `start_page` | 정수 | 0 | 분석 시작 페이지 |
| `end_page` | 정수 | -1 | 분석 끝 페이지 |

초기 등록 검증 단계에서는 기본값을 최대한 유지한다. 성능이나 결과 정확도를 확인하기 전에 임의로 threshold·병합 옵션을 조정하면 문제 원인 분리가 어려워진다.

`draw_viz`와 `draw_tsr`는 최종 HRC에 사용하지 않을 가능성이 높지만, 실제 결과 목록과 실행 비용을 측정한 뒤 비활성화한다.

### Python 요청 예시

다음은 구현 방향을 설명하기 위한 예시이며 실제 서버 URL, `author`, `ws_id`는 농협이
생성한 workspace 정보로 주입한다. Custom Parser는 로그인이나 workspace 생성 API를
호출하지 않는다.

```python
import json
import mimetypes
from pathlib import Path

import requests


def start_analysis(base_url: str, file_path: Path, author: str, ws_id: str) -> dict:
    tr_data = {
        "author": author,
        "ws_id": ws_id,
        "res_type": ["default"],
        "prj_config": {
            "extract_type": "dla",
            "table_to_struct": "html",
        },
        "meta_info": {},
    }

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    with file_path.open("rb") as stream:
        response = requests.post(
            f"{base_url}/api/v1/etl/auto/start",
            data={"tr_data": json.dumps(tr_data, ensure_ascii=False)},
            files={"upfiles": (file_path.name, stream, content_type)},
            timeout=(10, 60),
        )

    response.raise_for_status()
    payload = response.json()
    if payload.get("result", {}).get("code") != 0:
        raise RuntimeError(payload.get("result", {}).get("message", "ETL request failed"))
    return payload
```

한 문서 요청이면 일반적으로 응답 `data.task_ids[0]`과 `data.file_paths[0]`을 사용한다. 배열 길이와 입력 파일 수가 일치하는지 검증해야 한다.

### 분석 요청 응답

```json
{
  "result": {
    "code": 0,
    "message": "success"
  },
  "meta": null,
  "data": {
    "task_ids": ["worker-task-id"],
    "file_paths": ["sample.pdf/v1/sample.pdf"],
    "meta_info": {},
    "msg": "add tasks"
  }
}
```

`task_ids`는 ETL 내부 작업 ID이고 `file_paths`는 뒤의 상태·결과 API에 전달할 문서 경로다. KL Custom Parser의 UUID와 서로 다른 값이다.

## 2.3 분석 상태 확인 API

```http
GET /api/v1/file/info?file_path={file_path}
```

`file_path`에는 분석 요청 응답의 `data.file_paths` 값을 그대로 사용한다.

핵심 응답 필드:

| 필드 | 의미 |
|---|---|
| `chunk_status` | 전체 작업 상태 |
| `chunk_step` | 현재 처리 단계 |
| `file_path` | ETL 문서 경로 |
| `version_number` | 결과 버전 |

`chunk_status`:

| 코드 | 상태 | 처리 |
|---|---|---|
| `000` | `STATUS_INIT` | 잠시 후 재조회 |
| `001` | `STATUS_PROGRESS` | 잠시 후 재조회 |
| `002` | `STATUS_DONE` | 결과 조회로 진행 |
| `999` | `STATUS_ERROR` | Custom Parser 상태를 ERROR로 전환 |

`chunk_step`:

| 코드 | 단계 |
|---|---|
| `000` | 준비 |
| `001` | 파일 추출 |
| `002` | 파일 변환 |

`chunk_step=002`는 변환 단계라는 뜻이지, 3장의 사용자 정의 `custom_extension.transform()`이 우리 코드에 대해 호출됐다는 증거는 아니다.

### 폴링 코드 형태

```python
import time


def wait_until_done(base_url: str, file_path: str, timeout_seconds: int = 600) -> dict:
    deadline = time.monotonic() + timeout_seconds
    delay = 1.0

    while time.monotonic() < deadline:
        response = requests.get(
            f"{base_url}/api/v1/file/info",
            params={"file_path": file_path},
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("result", {}).get("code") != 0:
            raise RuntimeError(payload.get("result", {}).get("message", "ETL status failed"))

        datasource = payload.get("data", {}).get("datasource", [])
        if not datasource:
            raise RuntimeError("ETL status response has no datasource")

        status = datasource[0].get("chunk_status")
        if status == "002":
            return datasource[0]
        if status == "999":
            raise RuntimeError("ETL analysis reported STATUS_ERROR")
        if status not in {"000", "001"}:
            raise RuntimeError(f"Unknown ETL status: {status}")

        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)

    raise TimeoutError("ETL analysis timed out")
```

폴링 간격, 전체 timeout, 재시도 가능한 HTTP 상태는 농협 운영 기준에 맞춰 설정해야 한다. 연결 오류를 무한 재시도하면 KL의 바깥쪽 timeout까지 소모하므로 상한을 둔다.

## 2.4 결과 파일 목록 조회

```http
GET /api/v1/file/result/list?docPath={file_path}
```

`docPath`에는 최초 분석 요청에서 받은 `file_paths` 값을 사용한다.

응답 예시에는 다음과 같은 파일이 나온다.

```json
{
  "data": [
    {"file_name": "pipeline_log.log", "file_path": "sample.pdf/v1/pipeline_log.log"},
    {"file_name": "sample.json", "file_path": "sample.pdf/v1/sample.json"},
    {"file_name": "sample.pdf", "file_path": "sample.pdf/v1/sample.pdf"},
    {"file_name": "sample_edit.json", "file_path": "sample.pdf/v1/sample_edit.json"}
  ]
}
```

Default JSON을 선택하는 규칙을 파일명 추측만으로 고정하지 말고, 실제 농협 결과 1건을 받아 확인해야 한다. 후보가 여러 개면 다음 우선순위를 명시적으로 적용한다.

1. `res_type=default` by-type API 사용
2. 분석 요청 파일명과 대응하는 기본 `.json` 선택
3. `*_edit.json`, 로그, 원본 파일 제외
4. 후보가 0개 또는 2개 이상이면 오류로 처리하고 목록을 로그에 기록

## 2.5 결과 내용 조회

```http
GET /api/v1/file/result/doc?docResultPath={result_file_path}
```

`docResultPath`는 결과 목록 응답의 `file_path`다. 응답 본문 자체가 Default JSON 결과다.

```python
def get_result_document(base_url: str, result_path: str) -> dict:
    response = requests.get(
        f"{base_url}/api/v1/file/result/doc",
        params={"docResultPath": result_path},
        timeout=(10, 60),
    )
    response.raise_for_status()
    return response.json()
```

URL에 경로를 문자열로 직접 연결하지 않고 `params`를 사용해 인코딩해야 한다.

## 2.6 Default JSON 구조

최상위 구조:

```json
{
  "pdfName": "sample.pdf",
  "pageLen": 1,
  "pages": []
}
```

페이지:

```json
{
  "pageId": 1,
  "width": 1275,
  "height": 1650,
  "paragraphs": []
}
```

문단/영역:

```json
{
  "paragraphId": 10,
  "type": "Table",
  "bbox": [[149, 776], [1126, 776], [1126, 909], [149, 909]],
  "contents": "<table>...</table>",
  "confidence": 0.999,
  "lines": [],
  "parentId": [],
  "childId": [],
  "error_type": [],
  "rows": 3,
  "cols": 3,
  "cells": []
}
```

주요 `type`:

- `Title`
- `List-item`
- `Equation`
- `Figure`
- `Table`
- `PageHF`
- `Index`
- `Text`
- `Unknown`

`lines`는 표·이미지·수식 외 클래스에서 줄 단위 병합 결과를 제공할 수 있다.

```json
{
  "bbox": [[100, 100], [500, 100], [500, 130], [100, 130]],
  "contents": "한 줄의 OCR 결과"
}
```

표 영역에는 다음 추가 필드가 있을 수 있다.

- `rows`, `cols`
- `parentId`, `childId`
- `cells[]`
  - `bbox`
  - `contents`
  - `cellId`
  - `confidence`
  - `cell_info`: `[row_start, row_end, col_start, col_end]`

### 좌표 해석

가이드의 `bbox`는 다음처럼 네 꼭짓점 polygon이다.

```json
[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
```

단순 `[left, top, right, bottom]`으로 가정하면 안 된다. 내부 사각형 모델이 필요하면 다음처럼 변환할 수 있지만, 회전된 영역을 잃을 수 있음을 명시해야 한다.

```python
xs = [point[0] for point in bbox]
ys = [point[1] for point in bbox]
rect = [min(xs), min(ys), max(xs), max(ys)]
```

원본 polygon과 사각형 좌표를 모두 보존하는 중간 모델을 권장한다.

## 2.7 Callback 결과

콜백 사용 시 가이드의 결과 구조는 다음 개념이다.

```json
{
  "file_name": "document.pdf",
  "result_doc_path": ["/results/document_page1.png"],
  "task_result": {
    "result": "success",
    "doc_path": "/results/document.pdf",
    "processing_time": "1.92s"
  },
  "meta_info": {},
  "doc_result": {
    "pdfName": "document.pdf",
    "pageLen": 1,
    "pages": []
  }
}
```

`doc_result`의 하위 구조는 Default JSON과 같다. 현재 Custom Parser는 이미 KL에 비동기 결과 API를 제공해야 하므로, 초기 버전은 ETL 콜백 서버까지 추가하지 않고 폴링한다.

## 2.8 구현 범위 밖의 가이드 내용

이번 구현은 농협이 생성한 workspace를 사용해 1.16 분석 API부터 호출한다. 다음 내용은
Custom Parser의 책임이 아니므로 구현하지 않는다.

- 로그인, 사용자 등록, 토큰 또는 Cookie 발급
- workspace 생성·수정·삭제
- ETLwithLLM 컨테이너 내부 `custom_extension/implements` 마운트
- `ExtractType.CUSTOMIZE` 또는 사용자 정의 ETL 라우터
- ETL callback 수신 서버

선택한 구조는 `parse()`가 공개 분석 API를 호출하고, 조회한 Default JSON을 우리 코드에서
HRC로 변환하는 방식 하나다.

### KL option과 ETL 1.16 입력의 경계

KL 원본 가이드의 일반 OCR 공급자 설정은 `parser_info.prop.supplier`, `url`, `key`다.
따라서 구현은 `parser_info.prop.url`을 ETL base URL 후보로 인식한다. 반면 ETL 1.16의
필수 `author`, `ws_id`는 이 일반 KL 구조에 정의되어 있지 않으므로 농협이 제공하는
`option.etl`, `parser_info.prop` 확장값 또는 환경변수에서 받아야 한다.

`parser_info.prop.key`를 특정 HTTP 헤더에 넣는 규칙은 ETL 1.16 이후 문서에 없다. 농협이
별도 헤더 규격을 제공하기 전에는 `key`를 임의로 전송하지 않는다. 로그인, Cookie, workspace
생성도 이번 구현 범위가 아니다.

## 2.9 API 구현 시 지켜야 할 방어 조건

- HTTP 성공 여부뿐 아니라 응답 `result.code`도 확인한다.
- `task_ids`와 `file_paths`가 비어 있으면 즉시 오류 처리한다.
- 알 수 없는 `chunk_status`를 진행 중으로 간주하지 않는다.
- 전체 timeout과 개별 HTTP timeout을 분리한다.
- 서버 URL, `author`, `ws_id` 전체를 결과 ZIP이나 오류 응답에 노출하지 않는다.
- 원본 파일명으로 경로를 직접 조합할 때 traversal 문자를 제거한다.
- 결과 JSON은 사용 전에 필수 필드와 타입을 검증한다.
- Default JSON 원문은 결과 ZIP에 저장하지 않는다. 진단이 필요하면 개인정보를 제거한
  fixture를 내부 테스트 자료로 별도 보존한다.
- 운영 결과 ZIP에는 내부 진단 로그와 원본 ETL 응답을 무조건 포함하지 않는다.
- `callback_url`은 사용하지 않는다.

## 2.10 원본 PDF 렌더링 확인 참고 - 28쪽 이후

이 절은 원본 PDF가 이미지형 문서여서 28쪽 이후를 페이지 이미지로 렌더링해 표, 예제,
부록 스키마를 교차 확인한 결과다. 다시 해석해야 하는 요구사항이 아니라 구현 시 확인할
원본 근거와 문서 내부 차이를 기록한 참고 메모다.

### 1.16 분석 API

- 경로는 `POST /api/v1/etl/auto/start`다.
- `Content-Type`은 multipart/form-data다.
- `tr_data`는 JSON 객체가 아니라 JSON **문자열** 파트다.
- `upfiles`는 파일 파트이며 하나 이상의 파일을 받을 수 있다.
- `author`, `ws_id`는 필수다.
- `callback_url`은 선택이며 이번 구현에서는 보내지 않는다.
- `res_type` 표기는 문자열 또는 리스트를 허용하지만 Python 예제는
  `"res_type": ["default"]`를 사용한다. 구현도 예제와 같은 리스트를 사용한다.
- 공개 `prj_config.extract_type`은 `all`, `dla`, `parser`이며 기본값은 `dla`다.
- 초기 구현은 `extract_type=dla`, `table_to_struct=html`만 명시하고 나머지 옵션은 가이드
  기본값을 유지한다.

분석 시작 응답은 `data.task_ids[]`, `data.file_paths[]`를 준다. 한 파일씩 요청하는 현재
구현은 두 배열이 각각 정확히 한 요소인지 검사한다. `file_paths[0]`은 이후 상태와 결과
조회에 그대로 사용하며 KL이 발급한 바깥쪽 UUID와 섞지 않는다.

### 1.17 상태 조회

- 경로는 `GET /api/v1/file/info?file_path=...`다.
- `chunk_status=000`은 초기화, `001`은 처리 중, `002`는 완료, `999`는 오류다.
- `chunk_step=000/001/002`는 준비/추출/변환 단계 표시다.
- 완료되지 않은 알 수 없는 상태를 임의로 처리 중으로 간주하지 않는다.

### 1.18~1.20 결과 조회

- 결과 목록: `GET /api/v1/file/result/list?docPath=...`
- 결과 내용: `GET /api/v1/file/result/doc?docResultPath=...`
- 유형별 편의 조회:
  `GET /api/v1/file/result/json/type?doc_path=...&res_type=default`
- 기본 흐름은 목록 조회 후 원본 파일명과 대응하는 `.json` 한 개를 선택하고 내용 조회를
  수행한다. `*_edit.json`, 로그, 원본 파일은 Default JSON 후보에서 제외한다.
- 후보가 없거나 둘 이상으로 모호하면 추측하지 않고 오류로 처리한다.

### 표·예제 사이의 차이와 구현 대응

원본의 일부 표와 코드 예시는 다음 부분에서 표현이 일치하지 않는다.

1. `result.code`가 숫자 `0/-1` 예제와 문자열형 설명으로 혼재한다. 구현은 정수 또는 숫자
   문자열 `0`만 성공으로 정규화한다.
2. callback 예제의 `doc_result`가 Default JSON을 직접 담는 형태와
   `doc_result.default`로 한 번 더 감싼 형태가 모두 보인다. polling의 결과 내용 API는
   직접 Default JSON을 반환하는 것으로 설명되어 있으나 변환기는 두 wrapper 형태도
   명시적으로 허용한다.
3. 부록 스키마에는 본문 설명 외에 `section_level`, `list_hierarchy`,
   `warning_messages`, `n_cols` 같은 선택 필드가 나온다. 내부 정규화 모델은 알려진 선택
   필드를 보존하고, HRC가 직접 표현하지 않는 정보는 텍스트를 유실하지 않는 방향으로
   처리한다.
4. `bbox`는 `[left, top, right, bottom]`이 아니라 네 점 polygon이다. 내부 모델에는 원본
   polygon과 계산된 사각형을 함께 보존한다.

이 호환 처리는 문서에 나온 형태만 대상으로 한다. 실제 농협 ETL 응답이 이 범위를 벗어나면
자동 추측하지 않고 스키마 오류로 기록하며, 비식별화한 실제 응답으로 계약 테스트를 추가한다.
