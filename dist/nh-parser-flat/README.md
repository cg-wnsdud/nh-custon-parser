# NH Knowledge Lake Custom Parser 전달본

이 폴더의 파일을 농협 템플릿의 `app_custom_parser/service/`에 하위 폴더 없이 배치합니다.
- `parsing_service.py`: `parse()` 진입점과 전체 처리 실행
- `etl_config.py`: ETL 접속값·분석 옵션 해석 및 검증
- `etl_client.py`: 분석 요청, 상태 폴링, Default JSON 조회
- `etl_adapter.py` / `document_model.py`: ETL JSON 검증 및 공통 내부 구조 변환
- `hrc_exporter.py` / `result_contract.py`: HRC JSONL·INFO 생성 및 결과 검증
- `README.md`: 배치 및 설정 안내

etlwithllm api 호출시 필수인 환경변수 `ETL_BASE_URL`, `ETL_AUTHOR`, `ETL_WS_ID`를 설정해야 합니다.
`run-application.sh`의 `# CUSTOM 영역` 주석 아래에 다음 세 줄을 추가하시면 됩니다.

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

선택적으로 `ETL_PRJ_CONFIG`와 `ETL_ANALYSIS_TIMEOUT_SECONDS`를 설정할 수 있으며, 분석 기본값은 `dla`·`html`, 대기시간은 540초입니다.
필수값이 없으면 ETL을 호출하지 않고 `Missing ETL configuration: ...` 오류를 기록합니다.
HTTP 호출은 `requests`를 사용하며, 플랫폼 이미지에 포함된 버전(2.34.2)을 그대로 사용하므로 추가 설치가 필요 없습니다.
