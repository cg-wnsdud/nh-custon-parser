# NH Knowledge Lake Custom Parser 전달본

이 폴더의 8개 파일을 농협 템플릿의 `app_custom_parser/service/`에 하위 폴더 없이 배치합니다.
- `parsing_service.py`: `parse()` 진입점과 전체 처리 실행
- `etl_config.py`: ETL 접속값·분석 옵션 해석 및 검증
- `etl_client.py`: 분석 요청, 상태 폴링, Default JSON 조회
- `etl_adapter.py` / `document_model.py`: ETL JSON 검증 및 공통 내부 구조 변환
- `hrc_exporter.py` / `result_contract.py`: HRC JSONL·INFO 생성 및 결과 검증
- `README.md`: 배치 및 설정 안내

실행 전에 필수 환경변수 `ETL_BASE_URL`, `ETL_AUTHOR`, `ETL_WS_ID`를 설정해야 합니다.
```bash
export ETL_BASE_URL="http://{ETL 서버 IP}:{포트}" ETL_AUTHOR="{author}" ETL_WS_ID="{workspace ID}"
```
선택적으로 `ETL_PRJ_CONFIG`와 `ETL_ANALYSIS_TIMEOUT_SECONDS`를 설정할 수 있으며, 분석 기본값은 `dla`·`html`, 대기시간은 540초입니다.
필수값이 없으면 ETL을 호출하지 않고 `Missing ETL configuration: ...` 오류를 기록합니다.
구현 모듈은 Python 3.11 표준 라이브러리만 사용하며 플랫폼 진입 파일과 패키지는 농협 템플릿 원본을 사용합니다.
