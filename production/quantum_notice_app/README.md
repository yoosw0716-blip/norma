# Quantum Notice App (Python)

양자 관련 과제/사업 공고를 자동 수집하는 파이썬 앱입니다.

## 주요 기능
- NTIS, 기업마당, IRIS, UNIST, NRF, 나라장터, ETRI, KEITI, KEIT, KRISS 수집
- 페이지네이션(`--max-pages`)
- 필터 모드
  - 기본: 완화 필터(양자 키워드 중심)
  - 엄격: `--strict-filter` (양자+공고 키워드)
- 필요 시 Playwright fallback (`--use-playwright` 또는 `NOTICE_USE_PLAYWRIGHT=true`)
- 마감일 파싱(`YYYY-MM-DD`) 및 D-day 계산
- JSON 파일 누적 저장 + 중복 제거
- 신규/0건 모두 슬랙 웹훅 전송
- Gemini 기반 공고 브리핑 보강 지원
- 브리핑에서는 마감 지난 공고 자동 제외
- 유효 공고가 없으면 안내 메시지 전송

## 기본 실행
```bash
python quantum_notice_app.py --env-file .env run
```

## 수집 강화 실행(권장)
```bash
python quantum_notice_app.py --env-file .env run --max-pages 10
```

## 엄격 필터 실행
```bash
python quantum_notice_app.py --env-file .env run --max-pages 10 --strict-filter
```

## Playwright fallback 사용
```bash
pip install playwright
playwright install chromium
python quantum_notice_app.py --env-file .env run --max-pages 10 --use-playwright
```

## 조회
```bash
python quantum_notice_app.py --env-file .env list --days 30 --limit 20
```

## LLM 공고 브리핑 생성
`GEMINI_API_KEY`가 있으면 최근 공고 상위 항목부터 Gemini 보강을 적용하고, 없거나 실패하면 기존 규칙 기반 요약으로 자동 fallback 됩니다. 브리핑에서는 마감 지난 공고와 명백한 노이즈 제목을 제외하며, 남는 공고가 없으면 안내 메시지를 생성합니다.

```bash
python generate_quantum_briefing.py --env-file .env --db data/quantum_notices.json --slack
```

브리핑 전송 채널은 `.env`의 `BRIEFING_SLACK_CHANNEL`로 바꿀 수 있고, 실행 시 `--channel`로 덮어쓸 수 있습니다. 여러 채널은 쉼표 또는 줄바꿈으로 구분합니다.

## 환경변수 예시 (.env)
```env
NOTICE_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
BRIEFING_SLACK_CHANNEL=C07SEMKKVSN,C08ABCDEFGH
BRIEFING_LLM_MAX_ARTICLES=5
BRIEFING_DAYS=14
BRIEFING_MAX_ITEMS=10
NOTICE_USE_PLAYWRIGHT=false
TZ=Asia/Seoul
```

## 자동 실행 (Ubuntu + systemd)
- `deploy/systemd/quantum-notice.service`
- `deploy/systemd/quantum-notice.timer`

현재 타이머 예시: 매주 월/목 09:00
