# NH Knowledge Lake Custom Parser 전달본

이 폴더의 파일을 농협 템플릿의 `app_custom_parser/service/`에 하위 폴더 없이 배치합니다.
- `parsing_service.py`: `parse()` 진입점과 전체 처리 실행
- `etl_config.py`: ETL 접속값·분석 옵션 해석 및 검증
- `etl_client.py`: 분석 요청, 상태 폴링, Default JSON 조회
- `etl_adapter.py` / `document_model.py`: ETL JSON 검증 및 공통 내부 구조 변환
- `hrc_exporter.py` / `result_contract.py`: HRC JSONL·INFO 생성 및 결과 검증
- `vlm_client.py`: VLM(OpenAI 호환) 호출 - 현재는 사용 가능 여부 확인용
- `README.md`: 배치 및 설정 안내

etlwithllm api 호출시 필수인 환경변수 `ETL_BASE_URL`, `ETL_AUTHOR`, `ETL_WS_ID`를 설정해야 합니다.
`run-application.sh`의 `# CUSTOM 영역` 주석 아래에 다음 세 줄을 추가하는 방법으로 구현했습니다.

```bash
# ===================================================
# CUSTOM 영역
# ===================================================
export ETL_BASE_URL="http://{ETL 서버 IP}:{포트}"
export ETL_AUTHOR="{author}"
export ETL_WS_ID="{workspace ID}"

if [ -z "$FLOW_APP_DIR" ]; then          # ← 기존 내용 (수정 없음)
    export CUSTOM_LIBS=$PATH_SOURCE/custom_libs
```

배포 환경에서 컨테이너·Pod 환경변수로 설정하셔도 동일하게 동작합니다. 파싱은 별도 프로세스에서 실행되지만 기동 프로세스의 환경변수를 그대로 물려받습니다.

필수값이 없으면 ETL을 호출하지 않고 `Missing ETL configuration: ...` 오류를 기록합니다.
HTTP 호출은 `requests`를 사용하며, 플랫폼 이미지에 포함된 버전(2.34.2)을 확인해 구현하였습니다.

## VLM 호출 (테스트)

HRC 생성 직전에 VLM을 한 번 호출해 농협 환경에서 사용 가능한지 확인합니다.
**아래 값을 설정하지 않으면 호출하지 않고 그대로 넘어가며, 호출이 실패해도 파싱은 정상 완료됩니다.**

| 환경변수 | 내용 | 기본값 |
|---|---|---|
| `VLM_BASE_URL` | OpenAI 호환 엔드포인트, `/v1` 까지 | 미설정 시 VLM 단계 건너뜀 |
| `VLM_MODEL` | 모델명 (예: `gemma-3-27b-it`) | 미설정 시 VLM 단계 건너뜀 |
| `VLM_API_KEY` | API 키. 불필요한 환경이면 생략 | 없음 |
| `VLM_TIMEOUT_SECONDS` | 호출 타임아웃 | 60 |
| `VLM_PROMPT_CHARS` | 프롬프트에 넣을 문서 발췌 길이 | 1200 |

```bash
export VLM_BASE_URL="http://{VLM 서버}:{포트}/v1"
export VLM_MODEL="{모델명}"
export VLM_API_KEY="{API 키}"          # 필요한 경우
```

호출 방식은 `POST {VLM_BASE_URL}/chat/completions` 이며 요청 본문은 OpenAI 호환 형식입니다.
현재 단계에서는 **응답을 HRC 결과에 반영하지 않고** 확인용으로만 사용하며,
작업 디렉터리에 `{원본파일명}_vlm.json` 으로 남깁니다. 이 파일은 결과 ZIP에 포함되지 않습니다.
