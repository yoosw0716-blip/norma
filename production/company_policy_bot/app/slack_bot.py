from __future__ import annotations
import logging
import os
import re
import tempfile
import threading
import time
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from app.config import Settings
from app.llm_client import ChatResult, OpenClawClient, GeminiClient, LocalSTTClient
from app.pdf_store import Chunk, PdfKnowledgeBase
from app.prompting import build_messages
from app.quantum_notice_store import QuantumNoticeStore

logger = logging.getLogger(__name__)
MENTION_PATTERN = re.compile(r"<@[^>]+>")
POLICY_KEYWORDS = ["회사규정", "정책", "취업규칙", "연차", "휴가", "급여", "복리후생", "인사", "징계", "복무", "퇴직", "병가", "육아휴직", "휴직", "수습", "수습기간", "시용"]
GENERAL_PATTERN = re.compile(r"^(안녕|하이|헬로|반가워|고마워|감사|도와줘|도움|땡큐|이름이|넌 누구|봇|뭐해|잘가|수고했어)\b", re.IGNORECASE)
QUANTUM_NOTICE_KEYWORDS = ("양자공고", "양자과제", "양자사업", "양자내성암호", "pqc")

class CompanyPolicyBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kb = PdfKnowledgeBase(pdf_root=settings.pdf_root, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
        self.openclaw_client = OpenClawClient(base_url=settings.openclaw_base_url, api_key=settings.openclaw_api_key, model=settings.openclaw_model)
        self.gemini_client = GeminiClient(api_key=settings.gemini_api_key)
        self.stt_client = LocalSTTClient(model_size="large-v3", device="cuda", compute_type="float16")
        self.quantum_notice_store = QuantumNoticeStore(settings.quantum_notice_db_path)
        self.app = App(token=settings.slack_bot_token)
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.app.event("app_mention")(self.handle_app_mention)
        self.app.event("message")(self.handle_message_events)
        self.app.event("file_shared")(self.handle_file_shared)

    def handle_app_mention(self, event: dict, say) -> None:
        if "files" in event: self._handle_files(event, say)
        else:
            q = self._extract_question(event)
            if q: self._handle_message(event, say)

    def handle_message_events(self, event: dict, say) -> None:
        if event.get("bot_id") or event.get("channel_type") != "im": return
        if "files" in event: self._handle_files(event, say)
        else: self._handle_message(event, say)

    def handle_file_shared(self, event: dict, logger) -> None:
        logger.info("Ignoring file_shared event for file_id=%s", event.get("file_id"))

    def _handle_files(self, event: dict, say) -> None:
        files = event.get("files", [])
        audio_files = [f for f in files if f.get("mimetype", "").startswith("audio/")]
        if not audio_files: return

        initial_res = say("⏳ 녹음 파일을 확인했습니다. 회의록을 정리하고 있습니다. 완료되면 결과를 스레드로 보내드릴게요. (0%)")
        channel_id = event["channel"]
        message_ts = initial_res["ts"]
        stt_hints = "클로드코드(Claude Code), 재미나이(Gemini) CLI, OpenAI 코덱스, 바이브코딩(Vibecoding), 성택, 노르마(회사명), 비즈니스 계정, 30만 원, 결제 승인."

        def _process_audio_in_background(file_info: dict, say_func):
            file_url = file_info.get("url_private_download")
            if not file_url: return

            local_path = ""
            state = {"last_p": 0}

            def _update_progress_text(text: str) -> None:
                try:
                    self.app.client.chat_update(channel=channel_id, ts=message_ts, text=text)
                except Exception:
                    logger.exception("Failed to update progress message")

            def _upd(p):
                if p >= state["last_p"] + 10 or p >= 100:
                    state["last_p"] = (p // 10) * 10
                    bar = "▓" * (p // 10) + "░" * (10 - (p // 10))
                    txt = f"⏳ 회의록을 정리하는 중입니다... [{bar}] {p}%"
                    _update_progress_text(txt)

            try:
                local_path = self._download_slack_file(file_url)
                transcript = self.stt_client.transcribe(local_path, progress_callback=_upd, initial_prompt=stt_hints)
                if not transcript: return
                
                # 2. Local Refinement
                refined = self.openclaw_client.refine_transcript_locally(transcript)
                
                # 3. Local Summary
                result = self.openclaw_client.summarize_audio_text(refined)
                say_func(text=f"📋 *[로컬 회의록 정리 결과]*\n\n{result.content}", thread_ts=message_ts)
                _update_progress_text("✅ 회의록 정리가 완료되었습니다. 결과는 스레드에서 확인해주세요. (100%)")
            except Exception as e:
                logger.exception("Audio failed")
                say_func(f"오디오 처리 중 오류 발생: {e}")
                _update_progress_text("⚠️ 회의록 정리 중 오류가 발생했습니다. 스레드를 확인해주세요.")
            finally:
                if local_path and os.path.exists(local_path): os.remove(local_path)

        for f in audio_files:
            threading.Thread(target=_process_audio_in_background, args=(f, say), daemon=True).start()

    def _download_slack_file(self, url: str) -> str:
        headers = {"Authorization": f"Bearer {self.settings.slack_bot_token}"}
        resp = requests.get(url, headers=headers, stream=True)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tmp:
            for chunk in resp.iter_content(8192):
                if chunk: tmp.write(chunk)
            return tmp.name

    def _handle_message(self, event: dict, say) -> None:
        q = self._extract_question(event)
        if not q: return
        intent = "policy" if any(k in q for k in POLICY_KEYWORDS) else self.gemini_client.classify_intent(q)
        if intent == "policy": self._answer_policy_question(q, say)
        else: self._answer_general_question(event, q, say)

    def _answer_policy_question(self, q: str, say) -> None:
        say("로컬 문서를 검색하여 규정을 확인하고 있습니다.")
        self.kb.refresh_if_needed()
        ctx = self.kb.search(q, top_k=self.settings.top_k)
        if not ctx:
            say("근거를 찾지 못했습니다.")
            return
        try:
            res = self.openclaw_client.policy_chat(build_messages(q, ctx), self.settings.max_completion_tokens)
            refs = sorted(list(set([f"{c.source_name} p.{c.page_number}" for c in ctx])))
            say(text=f"{res.content.strip()}\n\n참고: {', '.join(refs)}")
        except Exception as e: say(f"오류 발생: {e}")

    def _answer_general_question(self, event: dict, q: str, say) -> None:
        try:
            res = self.gemini_client.general_chat(q)
            ans = res.content.strip()
            if event.get("channel_type") != "im": ans = f"<@{event.get('user')}> 님, {ans}"
            say(text=ans)
        except Exception as e: say(f"오류 발생: {e}")

    def _extract_question(self, event: dict) -> str:
        return MENTION_PATTERN.sub("", event.get("text", "")).strip()

    def _looks_like_quantum_notice_question(self, q: str) -> bool:
        return any(k in re.sub(r"\s+", "", q).lower() for k in QUANTUM_NOTICE_KEYWORDS)

    def start(self) -> None:
        self.kb.refresh()
        logger.info("Bot starting up (Prod GPU Mode)")
        SocketModeHandler(self.app, self.settings.slack_app_token).start()
