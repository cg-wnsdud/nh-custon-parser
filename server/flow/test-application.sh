#!/bin/bash

# 파싱 요청
export ENV_UUID=$(curl -X POST 127.0.0.1:9101/parsing -F "src_file=@/project/work/flow/dummy.txt" -F "option=e30=" | jq -r '.body.uuid')
echo $ENV_UUID

# 응답 대기 (파싱이 오래 걸릴 경우 sleep 시간을 늘려주세요)
sleep 3

# 파싱 결과 조회
curl -X GET 127.0.0.1:9101/parsing/result/${ENV_UUID} \
  -o /project/work/output.zip

# 결과 확인
unzip -l /project/work/output.zip

# 결과 삭제
rm /project/work/output.zip