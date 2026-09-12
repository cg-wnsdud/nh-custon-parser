# 4. 구현 및 검증 체크리스트

## 4.1 근거 수준 구분

### 자료에서 직접 확인된 내용

- KL Custom Parser는 `src_file`과 `option`을 multipart로 받는다.
- 장시간 파싱은 `POST /parsing`에서 HTTP 202, UUID, timeout을 반환한다.
- KL은 `GET /parsing/result/{uuid}`를 폴링한다.
- 실제 프로젝트 파싱 로직은 예제 `parsing_service.py`의 `parse()`에 구현한다.
- 결과 본문은 확장자를 포함한 `원본파일명_hrc.jsonl`이다.
- 결과 INFO는 확장자를 포함한 `원본파일명_hrc.json`이다.
- 이미지가 있으면 확장자를 포함한 `원본파일명_img.zip`을 사용한다.
- 결과 파일들을 ZIP으로 묶어 반환한다.
- ETL 분석 요청은 `POST /api/v1/etl/auto/start`다.
- 요청 multipart 키는 `tr_data`, `upfiles`다.
- 공개 설정 키는 `prj_config.extract_type`이고 값은 `all`, `dla`, `parser`다.
- ETL 상태는 `/api/v1/file/info`에서 `chunk_status`로 확인한다.
- 완료 코드는 `002`, 오류 코드는 `999`다.
- 결과는 목록 조회 후 내용 조회하거나 by-type API로 조회할 수 있다.
- Default JSON은 page와 paragraph 구조이며 polygon bbox, type, contents, confidence 등을 가진다.

### 미팅에서 확인됐으나 최신 템플릿이 필요한 내용

- 농협 플랫폼에 소스코드 제공 방식으로 등록한다.
- Python 3.11 환경을 기준으로 한다.
- 최종 전달 코드는 계층 구조 없이 한 폴더에 둔다.
- 농협 측이 workspace를 생성하고 ETL URL, `author`, `ws_id`를 제공한다.
- 로그인, 인증 토큰 발급, workspace 생성은 Custom Parser 구현 범위가 아니다.
- VLM을 사용할 수 없을 수 있다.
- HRC 적재 후 할당된 VectorDB 컬렉션을 Retrieval API로 조회한다.

### 아직 확정되지 않은 내용

- “한 폴더”가 업로드 번들 하나를 뜻하는지 모든 Python 파일의 완전 평면화를 뜻하는지
- 기존 `run-application.sh`와 디렉터리 제약을 어떻게 동시에 만족하는지
- 제공된 ETL URL·`author`·`ws_id`가 option인지 환경변수인지
- 운영 timeout·폴링 주기·요청 크기 제한
- Default JSON 결과 파일의 정확한 선택 규칙
- Figure crop 이미지 획득 방식
- ETL 페이지 크기와 HRC INFO 페이지 크기의 단위 변환
- ETL `pageId`와 HRC `page`의 번호 기준
- `cust_attr1~10`, `cust_sattr1~5`의 프로젝트별 의미
- 파서가 실제로 계산해야 할 Doc Data 변경 규칙
- 오류 상태의 HTTP 코드와 오류 결과 보존 시간
- Retrieval API의 URL, 인증, 검색·필터 파라미터
- 농협 내부 VLM의 모델·주소·호출 스키마

### 이번 구현에서 확정한 내용

- `_hrc.jsonl`과 `_hrc.json`은 필수 결과다.
- `_img.zip`은 실제 image 참조가 있을 때, `doc_data.json`은 실제 변경할 때만 포함한다.
- 그 외 sidecar, ETL 원본 응답, 로그는 결과 ZIP에 포함하지 않는다.
- heading에는 원본 예제와 같이 `page`를 출력하지 않는다.
- 미확정 `cust_meta`와 `doc_data.json`은 기본 exporter에서 출력하지 않는다.
- ETL API 구현 범위는 가이드 28쪽 1.16 분석 요청부터 1.20 결과 조회까지다.
- ETL 요청은 `res_type=["default"]`, `extract_type=dla`를 기본으로 한다.

체크 표기의 의미는 다음과 같다.

- `[x]`: 소스 구현 또는 로컬 코어 계약 테스트 완료
- `[ ]`: Python 3.11 플랫폼 또는 실제 농협 서비스에서 확인해야 완료

## 4.2 구현 단계

### 단계 0. 원본 보존

- [x] 전달받은 Custom Parser 예제를 수정하지 않고 참조용으로 보존
- [x] ETLwithLLM API 가이드 버전과 파일 해시 기록
  - v1.1.0 SHA-256:
    `E8E33DEC88D64B150891E2CD141A9284562E64590A9F2A8A092E5AB84E6C9C9A`
- [ ] 농협 최신 등록 템플릿 수령 시 별도 `references/` 또는 사내 문서 위치에 보존
- [ ] 비밀정보가 포함된 신청서는 Git에 올리지 않음

### 단계 1. 최소 KL 등록 검증본

목적은 ETL 연동이 아니라 플랫폼 실행 계약부터 확인하는 것이다.

- [x] Python 3.11.15 격리 환경에서 FastAPI 앱 import 성공
- [ ] `run-application.sh`로 Gunicorn 실행 성공
- [x] `/health` 구현, 플랫폼 기동 후 HTTP 확인 필요
- [x] `POST /parsing`이 multipart `src_file`, `option`을 수신하는 계약 테스트
- [x] `option` Base64 디코딩 구현 및 단위 테스트
- [x] UUID별 작업 디렉터리 생성 구현
- [x] HTTP 202 + 정확한 응답 구조 구현
- [x] `parse()`가 HRC JSONL/INFO JSON 생성
- [x] 결과 조회 중 `PARSING` 반환 구현
- [x] 완료 시 ZIP 반환 구현
- [x] ZIP 내부 허용 파일 검사 및 단위 테스트
- [ ] 농협 플랫폼에 소스 등록 후 같은 결과 확인

플랫폼 외곽 복원과 HRC 보수화 후 Python 3.11.15 자동 테스트 15개가 통과했고
skip/failure는 없다. `/health`,
`POST /parsing`의 202,
UUID와 정수 timeout, 결과 API의 `PARSING`/`ERROR`/ZIP, ETL mock 전체 흐름,
Default JSON wrapper와 polygon, HRC 파일명·heading, ZIP 허용 목록을 검사한다.

최소 HRC 예:

```jsonl
{"item":"text","value":"sample.pdf 파일을 입력으로 받았습니다.","page":1}
```

### 단계 2. ETLwithLLM 클라이언트

- [x] URL·`author`·`ws_id`를 option 또는 환경변수로 외부 주입
- [x] `POST /api/v1/etl/auto/start`
- [x] `tr_data`를 JSON 문자열로 전달
- [x] `upfiles`에 원본 파일 스트리밍 전달
- [x] 숫자/숫자 문자열 `result.code` 검증
- [x] 단일 파일 기준 `task_ids`, `file_paths` 배열 검증
- [x] 상태 API 폴링
- [x] `000`, `001`, `002`, `999` 처리
- [x] 알 수 없는 상태 오류 처리
- [x] HTTP 연결 timeout과 전체 분석 timeout 분리
- [x] 폴링 backoff와 최대 간격 적용
- [x] 결과 파일 목록 조회
- [x] Default JSON 결과 선택 및 모호한 후보 거부
- [x] 결과 내용 조회
- [x] 로그인·인증·workspace 생성 코드 미포함

### 단계 3. Default JSON 스키마와 중간 모델

- [x] `pdfName`, `pageLen`, `pages` 검증
- [x] page의 `pageId`, `width`, `height`, `paragraphs` 검증
- [x] paragraph의 `paragraphId`, `type`, `bbox`, `contents`, `confidence` 검증
- [x] 선택 필드가 없어도 안전하게 처리
- [x] polygon bbox 원본 보존
- [x] rect 계산
- [x] lines 원문 보존 및 contents fallback
- [x] table rows/cols/cells 보존
- [x] 문서에 나온 direct/default/doc_result wrapper 호환
- [x] 경고를 수집하되 텍스트가 가능한 한 유실되지 않게 처리

### 단계 4. HRC exporter

- [x] JSONL 각 줄이 독립적인 JSON 객체인지 검사
- [x] 허용 `item`만 출력
- [x] 모든 item에 `value` 존재
- [x] heading에서 `page` 제외
- [ ] ETL `pageId`와 HRC `page`의 번호 기준 확정
- [x] table의 `type_property.title` 존재
- [ ] image 참조와 `_img.zip` 실제 파일 일치
- [ ] image width/height/ratio 단위 확인
- [x] INFO JSON 파일 정보 생성
- [ ] INFO JSON 페이지 크기 단위 확인 및 필요한 변환 구현
- [x] 결과 파일 UTF-8 인코딩과 원자적 쓰기
- [x] ZIP 내부에 절대경로나 하위 디렉터리가 들어가지 않음
- [x] 빈 결과 문서는 `ERROR` 처리
- [x] Figure는 실제 이미지가 없으면 OCR contents를 `text`로 보존

### 단계 5. 광고 후처리

- [ ] ETL 원문 텍스트 보존을 먼저 검증
- [ ] 읽기 순서 기준 정의
- [ ] 인접 영역 조립 기준 정의
- [ ] 상품군 규칙 적용
- [ ] 템플릿 선택 규칙 적용
- [ ] 구분값 라벨링 규칙 적용
- [ ] 미분류 상태를 명시적으로 보존
- [ ] VLM 없이 전체 파이프라인 완료 가능
- [ ] 내부 VLM이 있을 때만 선택적으로 호출
- [ ] VLM 오류 시 원문 손실 없이 기본 모드로 복귀

### 단계 6. `cust_meta`와 Retrieval

- [ ] Retrieval API 명세 수령
- [ ] 정확 조회용 필드와 의미 검색용 필드 구분
- [ ] `cust_attr1`~`cust_attr10` 프로젝트 매핑 확정
- [ ] `cust_sattr1`~`cust_sattr5` 프로젝트 매핑 확정
- [x] 미확정 상태에서는 기본 HRC에 `cust_meta`를 출력하지 않음
- [ ] `sattr`가 임베딩·검색 결과에 미치는 영향 확인
- [ ] 문서 ID·페이지·영역 근거로 원문을 다시 찾을 수 있는지 확인
- [ ] 실제 KL 적재 후 필터 조회 테스트
- [ ] 실제 KL 적재 후 의미 검색 테스트
- [ ] 심의 단계에서 필요한 결과가 조회되는지 검증

## 4.3 단위·계약·현장 테스트

### 단위 테스트

- [ ] 정상 Default JSON 한 페이지
- [ ] 여러 페이지
- [ ] 빈 paragraphs
- [ ] Text/Title/List-item/Table/Figure/Equation/PageHF/Unknown
- [ ] polygon bbox
- [ ] 잘못된 bbox
- [ ] 표 cells 포함/미포함
- [ ] 낮은 confidence
- [ ] 한글 파일명
- [ ] JSONL 줄별 파싱
- [ ] HRC 허용 item 검사

### ETL mock 계약 테스트

- [ ] 분석 요청 성공
- [ ] `result.code != 0`
- [ ] task/file path 없음
- [ ] 상태 `000 -> 001 -> 002`
- [ ] 상태 `999`
- [ ] 알 수 없는 상태
- [ ] HTTP 500 후 재시도
- [ ] 연결 timeout
- [ ] 전체 timeout
- [ ] 결과 목록 0개
- [ ] Default JSON 후보 여러 개
- [ ] 손상된 결과 JSON

### KL API 계약 테스트

- [ ] 최초 요청 202
- [ ] UUID와 timeout 타입 검증
- [ ] 잘못된 Base64 option
- [ ] 파일 미첨부
- [ ] 진행 중 응답
- [ ] 완료 ZIP
- [ ] 파싱 오류 응답
- [ ] 존재하지 않는 UUID
- [x] 원본 예제와 같이 결과 반환 후 작업 폴더 삭제, 동일 UUID 재조회는 HTTP 500
- [ ] 여러 요청 동시 실행

### 현장 통합 테스트

- [ ] 농협 Custom Parser 소스 등록 성공
- [ ] 플랫폼이 `run-application.sh` 실행
- [ ] `/health` 확인
- [ ] KL이 `/parsing` 호출
- [ ] 플랫폼에서 ETLwithLLM 주소 접근 가능
- [ ] 실제 PDF로 `extract_type=dla` 요청
- [ ] 상태 폴링 완료
- [ ] Default JSON 수신
- [ ] HRC ZIP 반환
- [ ] KL이 JSONL 수용
- [ ] VectorDB 적재 완료
- [ ] `cust_attr` 필터 조회
- [ ] `cust_sattr` 검색·조회
- [ ] 오류 로그 위치와 운영자 확인 방식 파악

## 4.4 최소 완료 기준과 확장 완료 기준

### 1차 최소 완료

```text
KL 입력
  -> Custom Parser
  -> ETLwithLLM DLA/OCR
  -> Default JSON
  -> 모든 OCR 텍스트가 보존된 HRC JSONL
  -> KL 적재 성공
```

다음이 충족되면 1차 완료로 본다.

- 등록 성공
- 비동기 폴링 성공
- 실제 농협 ETL 결과 수신
- 문서별 HRC JSONL/INFO JSON 생성
- KL 결과 ZIP 수용
- VectorDB 적재 확인

### 2차 광고 후처리 완료

- 주요 광고 문구 누락 없음
- 상품군·템플릿·구분값 결과가 정의된 정확도 기준 충족
- VLM 미사용 모드 동작
- 선택적 농협 VLM 연동
- 심의 Retrieval 흐름에서 필요한 문구와 메타 조회 가능

## 4.5 최종 전달물

농협 측에 전달할 등록본:

- [ ] 현장 검증을 마친 최종 Custom Parser 소스코드
- [x] 원본 플랫폼 골격을 복원한 `run-application.sh`
- [x] `setup-application.sh`
- [x] 원본 플랫폼 골격을 복원한 `gunicorn_config.py`
- [x] 의존성 명세
- [x] 예제에서 요구한 `python-multipart` 폐쇄망 wheel과 SHA-256 목록
  - Python 3.11에서 `--no-index --no-deps` 설치 및 `multipart==0.0.17` import 확인
- [ ] 테스트 원본 파일
- [x] 비식별 합성 ETL 입력 fixture와 기대 HRC 계약 테스트
- [x] 호출·검증 방법 README
- [x] 설정값 목록
- [x] 완료 ZIP까지 폴링·검증하는 `test-application.sh`
- [ ] 지원 확장자 목록
- [ ] 알려진 제한사항

우리 내부에 별도로 보관할 자료:

- [ ] ETL 요청/응답 원본 샘플
- [ ] 비밀정보가 제거된 실패 로그
- [ ] Default JSON 골든 픽스처
- [ ] HRC 기대 결과
- [ ] 필드 매핑표
- [ ] 현장 검증 결과
- [ ] 농협 답변과 결정 기록

API Key, 비밀번호, 실제 내부 IP, 접근 토큰, 개인정보가 포함된 입력 문서는 Git에 커밋하지 않는다.

## 4.6 농협 측에 우선 확인할 최소 질문

다음 네 묶음을 확인해야 농협 전달본을 최종 확정할 수 있다.

1. **등록 구조**
   - 소스코드 제공형 등록 시 실제 업로드할 최신 템플릿과 디렉터리 구조를 받을 수 있는지
   - 기존 `run-application.sh`·`main.py`·`parse()` 계약을 그대로 사용하면 되는지
   - “한 폴더”의 정확한 범위가 무엇인지

2. **ETL workspace 설정**
   - 농협이 생성한 workspace의 URL, `author`, `ws_id`, 허용 `prj_config`, timeout을
     option과 환경변수 중 어떤 방식으로 전달하는지
   - `option.parser_info.prop`로 들어오는지 별도 환경 설정인지

3. **결과·적재 계약**
   - INFO 페이지 크기 단위와 `page` 번호 기준
   - 심의 조회 조건에 맞는 `cust_attr`/`cust_sattr` 번호별 의미
   - 파서가 계산해야 하는 `doc_data.json` 변경 항목
   - Retrieval API 규격과 실제 조회 검증 절차

4. **모델·후처리 범위**
   - 농협 내부 VLM을 사용할 수 있는지
   - 1차 결과를 DLA Default JSON의 HRC 변환까지만 제공하면 되는지, 광고 템플릿·라벨링까지 Custom Parser에서 수행해야 하는지

## 4.7 착수 순서 요약

```text
현재 예제 구조 구현 및 mock 계약 테스트
  -> 최신 등록 템플릿 확인
  -> 최소 HRC를 반환하는 parse() 등록
  -> KL 호출/폴링/ZIP 검증
  -> ETLwithLLM mock 연동
  -> 현장 ETL 연동
  -> Default JSON -> HRC 변환
  -> KL VectorDB 적재 확인
  -> cust_meta/Retrieval 현장 검증
  -> 광고 후처리 고도화
  -> 선택적 VLM 연동
```

ETL 분석 API 호출과 기본 HRC 변환 코드는 분리해 구현했다. 다음 핵심 단계는 최신 등록
템플릿과 실제 workspace 값을 받아 Python 3.11 플랫폼에서 KL 계약과 ETL 응답을 검증하는
것이다. 광고 후처리는 이 현장 검증 이후에 붙인다.
