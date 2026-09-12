#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE_URL=${BASE_URL:-http://127.0.0.1:9101}
SOURCE_FILE=${1:-/project/work/flow/dummy.txt}
OPTION=${2:-e30=}
OUTPUT_ZIP=${OUTPUT_ZIP:-/project/work/output.zip}
POLL_SECONDS=${POLL_SECONDS:-3}
MAX_POLLS=${MAX_POLLS:-200}

# 원본 예제와 동일한 최초 요청 및 UUID 추출
ENV_UUID=$(curl --fail --silent --show-error \
  -X POST "$BASE_URL/parsing" \
  -F "src_file=@$SOURCE_FILE" \
  -F "option=$OPTION" | jq -er '.body.uuid')
echo "$ENV_UUID"

# PARSING 상태를 반복 조회하고 완료 ZIP 또는 ERROR를 판별
poll_count=0
while [ "$poll_count" -lt "$MAX_POLLS" ]; do
  curl --fail --silent --show-error \
    -X GET "$BASE_URL/parsing/result/$ENV_UUID" \
    -o "$OUTPUT_ZIP"

  if unzip -t "$OUTPUT_ZIP" >/dev/null 2>&1; then
    break
  fi

  status=$(jq -er '.status // empty' "$OUTPUT_ZIP" 2>/dev/null || true)
  if [ "$status" = "PARSING" ]; then
    poll_count=$((poll_count + 1))
    sleep "$POLL_SECONDS"
    continue
  fi
  if [ "$status" = "ERROR" ]; then
    jq . "$OUTPUT_ZIP" >&2
    rm -f "$OUTPUT_ZIP"
    exit 1
  fi

  echo "Unexpected result response" >&2
  cat "$OUTPUT_ZIP" >&2
  rm -f "$OUTPUT_ZIP"
  exit 1
done

if ! unzip -t "$OUTPUT_ZIP" >/dev/null 2>&1; then
  echo "Parsing did not complete within MAX_POLLS=$MAX_POLLS" >&2
  rm -f "$OUTPUT_ZIP"
  exit 1
fi

unzip -l "$OUTPUT_ZIP"
python "$SCRIPT_DIR/verify-result.py" "$OUTPUT_ZIP" "$(basename "$SOURCE_FILE")"
rm -f "$OUTPUT_ZIP"

