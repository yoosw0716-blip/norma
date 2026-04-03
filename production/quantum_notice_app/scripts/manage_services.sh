#!/bin/bash
set -e

ACTION=$1

# 이 스크립트가 있는 디렉토리
SCRIPT_DIR=$(dirname "$0")

if [ "$ACTION" == "stop" ]; then
    echo "Stopping services for the weekend..."
    # Ollama 서비스 중지
    systemctl stop ollama.service || echo "Failed to stop ollama.service, maybe it was not running."
    # company-policy-bot 서비스 중지
    systemctl stop company-policy-bot.service || echo "Failed to stop company-policy-bot.service, maybe it was not running."
    # quantum-notice 타이머 중지
    systemctl stop quantum-notice.timer || echo "Failed to stop quantum-notice.timer, maybe it was not running."
    echo "Services stopped. You can now use Stable Diffusion."

elif [ "$ACTION" == "start" ]; then
    echo "Starting services for the weekday..."
    # Ollama 서비스 시작
    systemctl start ollama.service || echo "Failed to start ollama.service. Please check if it is installed."
    # company-policy-bot 서비스 시작
    systemctl start company-policy-bot.service
    # quantum-notice 타이머 시작
    systemctl start quantum-notice.timer
    echo "Services started for the weekday."
else
    echo "Usage: $0 {start|stop}"
    exit 1
fi
