# Company Policy Slack Bot

회사내규 PDF를 근거로 Slack에서 질의응답하는 봇입니다. 서버 주소는 `192.168.0.216`이고, 로컬 LLM은 같은 서버의 Ollama OpenAI 호환 API(`http://127.0.0.1:11434/v1`)를 사용합니다.

## 권장 운영 방식

이 봇은 DM에서만 회사 규정을 답하고, 공개/비공개 채널에서는 기존 OpenClaw 봇이 일반 질의를 처리하도록 분리하는 구성이 가장 깔끔합니다.

권장 설정:

```env
ALLOW_DIRECT_MESSAGES=true
ALLOW_CHANNEL_MENTIONS=false
```

이렇게 하면:
- 이 봇은 DM에서만 응답합니다.
- 공개 채널, 비공개 채널 멘션에는 응답하지 않습니다.
- 채널 질의는 기존 OpenClaw 봇이 맡게 되어 충돌이 줄어듭니다.

## 구성 개요

1. `data/pdfs` 폴더에 회사내규 PDF를 업로드합니다.
2. 봇이 PDF 텍스트를 읽어 페이지 단위로 청크를 만듭니다.
3. DM 질문이 오면 BM25로 관련 청크를 찾습니다.
4. 찾은 근거를 Ollama OpenAI 호환 API에 전달합니다.
5. Slack Socket Mode 봇이 DM으로 답변합니다.

## 권장 서버 경로

```text
/home/norma/company_policy_bot
```

## 환경 변수 예시

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
OPENCLAW_BASE_URL=http://127.0.0.1:11434/v1
OPENCLAW_API_KEY=
OPENCLAW_MODEL=qwen3-ko:latest
PDF_ROOT=/home/norma/company_policy_bot/data/pdfs
CHUNK_SIZE=1200
CHUNK_OVERLAP=200
TOP_K=3
MAX_COMPLETION_TOKENS=300
ALLOW_DIRECT_MESSAGES=true
ALLOW_CHANNEL_MENTIONS=false
ALLOWED_CHANNEL_IDS=
```

## 반영

서버에서 코드를 업데이트한 뒤 재시작합니다.

```bash
sudo systemctl restart company-policy-bot
sudo systemctl status company-policy-bot
journalctl -u company-policy-bot -f
```

시작 로그에 `allow_dm=True allow_channel_mentions=False`가 보이면 의도대로 적용된 것입니다.
