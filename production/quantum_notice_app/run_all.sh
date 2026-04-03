#!/bin/bash

# 에러가 발생하면 즉시 중단
set -e

# 이 스크립트가 있는 디렉토리로 이동
cd "$(dirname "$0")"

echo "===== 1. 양자 공고 수집 시작 ====="
# 가상환경 내 python3 실행 파일을 직접 지정
# systemd의 WorkingDirectory가 /home/norma/quantum_notice_app 이므로 경로를 이렇게 지정
NOTICE_WEBHOOK_URL="" /home/norma/anaconda3/envs/quantum_env/bin/python quantum_notice_app.py --env-file .env run

echo ""
echo "===== 2. 상세 브리핑 생성 및 전송 시작 ====="
# 가상환경 내 python3 실행 파일을 직접 지정
/home/norma/anaconda3/envs/quantum_env/bin/python generate_quantum_briefing.py --env-file .env --slack

echo ""
echo "===== 모든 작업 완료 ====="
