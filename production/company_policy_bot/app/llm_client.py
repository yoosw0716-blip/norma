from __future__ import annotations
import logging
import os
import re
import requests
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ChatResult:
    content: str
    finish_reason: str

THINKING_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
LEADING_REASONING_MARKERS = ("okay, let's see", "let's see", "the user is asking", "looking at", "looking at page", "based on page", "let me read again", "but wait", "wait,")
ENGLISH_SUMMARY_MARKERS = ("mentions that", "according to page", "according to the document", "and another is", "the first document", "the second document", "document 1", "document 2")
KOREAN_SENTENCE_PATTERN = re.compile(r"[^.!?\n]*[가-힣][^.!?\n]*[.!?]?")
FILENAME_PREFIX_PATTERN = re.compile(r"^[\s\S]*?\.pdf\b", re.IGNORECASE)

class OpenClawClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 300) -> None:
        self.base_url = base_url.replace("/v1", "").rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024, temperature: float = 0.0) -> ChatResult:
        try:
            body = self._post_chat(messages=messages, max_tokens=max_tokens, temperature=temperature)
            choice, message = self._extract_choice(body)
            raw_content = (message.get("content") or "").strip()
            content = self._sanitize_content(raw_content)
            if content:
                return ChatResult(content=content, finish_reason=str(choice.get("finish_reason") or "stop"))
        except Exception as e:
            logger.error(f"Local SLM call failed: {e}")
        return ChatResult(content="모델 응답에 실패했습니다.", finish_reason="error")

    def refine_transcript_locally(self, raw_text: str) -> str:
        system_prompt = "당신은 회의록 전사 전문가입니다. STT 텍스트에서 오타를 수정하고 문맥을 다듬으세요. 절대 요약하거나 삭제하지 마세요."
        user_prompt = f"""다음 STT 텍스트에서 오타와 비문을 교정하세요. 특히 아래 규칙을 반드시 따르세요.
[강제 교정 규칙]
- '재미나이' -> 'Gemini'
- '클러드' -> 'Claude'
- '바이코딩' -> 'Vibe Coding'
- '권리 속도', '권리' -> '걸릴 속도' (속도와 관련된 문맥일 경우)
- '3만 원', '3만원만' -> '30만 원' (비즈니스 계정 결제 문맥일 경우)
- '노릇', '노르웨이' -> '노르마' (회사명)

[STT 원문]
{raw_text}"""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        result = self.chat(messages, max_tokens=4096, temperature=0.0)
        return result.content if result.finish_reason != "error" else raw_text

    def policy_chat(self, messages: list[dict[str, str]], max_tokens: int) -> ChatResult:
        return self.chat(messages, max_tokens=max_tokens, temperature=0.0)

    def summarize_audio_text(self, transcript: str) -> ChatResult:
        system_prompt = (
            "당신은 IT/AI 기업의 시니어 프로젝트 매니저이자 최고 수준의 회의록 작성 비서입니다. "
            "주어진 녹취록을 바탕으로 정보 밀도가 높은 공식 회의록을 작성해야 합니다. "
            "문체는 반드시 '-함', '-임', '-예정임', '-필요함'과 같은 명사형 종결어미만 사용해야 하며, "
            "'~강조되었다', '~의견이 있었다', '~논의되었다' 같은 서술형 어미는 엄격히 금지합니다. "
            "LLM, SLM, AI 에이전트, 추론 모델, GPU, 배포, API, SaaS 등 실제 IT/AI 실무 용어를 자연스럽게 반영하세요. "
            "날짜와 연도 표현은 현재 시점인 2026년 기준으로 보정하고, 녹취록에 명확한 단서가 있으면 그 정보를 우선 반영하세요. "
            "불필요한 수식 없이 핵심 사실, 결정 사항, 담당자, 일정만 추출해 정보 밀도를 극대화하세요. "
            "출력은 반드시 사용자가 제공한 마크다운 템플릿 구조를 그대로 따르세요."
        )
        user_prompt = f"""다음 녹취록을 분석하여 아래의 지정된 마크다운 템플릿에 맞게 회의록을 작성하세요.

[회의록 템플릿]
📝 회의록: [회의의 가장 핵심적인 주제 1~2단어]

📅 일시: [오늘 날짜: 2026년 4월 3일(금) 혹은 녹취록 기반 보정]
👥 참석자: [녹취록에서 파악된 참석자 이름/직급 나열]

---
💡 한 줄 요약
> [회의 전체의 가장 핵심적인 결론을 1문장으로 요약]

🗣️ 주요 논의 사항
- [주제 1 소제목]
  - [핵심 내용 1]
  - [핵심 내용 2]
- [주제 2 소제목]
  - [핵심 내용 1]

🤝 협의 사항
- [최종적으로 합의되거나 결정된 원칙, 방향성 (액션 아이템과 내용 중복 금지)]

🚀 액션 아이템
- [ ] (담당자명) [구체적인 작업 내용] - [기한, 없으면 미정]

[녹취록]
{transcript}"""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        return self.chat(messages, max_tokens=4096, temperature=0.3)

    def _post_chat(self, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens}
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _extract_choice(self, body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        message = body.get("message", {})
        choice = {"finish_reason": body.get("done_reason", "stop")}
        return choice, message

    def _sanitize_content(self, content: str) -> str:
        if not content: return ""
        cleaned = THINKING_BLOCK_PATTERN.sub("", content).strip()
        if any(cleaned.lower().startswith(m) for m in LEADING_REASONING_MARKERS): return ""
        if FILENAME_PREFIX_PATTERN.match(cleaned): return ""
        if any(m in cleaned.lower() for m in ENGLISH_SUMMARY_MARKERS): return ""
        return cleaned.strip()

class GeminiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"

    def classify_intent(self, question: str) -> str:
        prompt = f"질문을 'policy' 또는 'general'로 분류하세요. 단어 하나로만 응답하세요.\n\n질문: \"{question}\""
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.0, "maxOutputTokens": 10}}
        try:
            response = requests.post(self.url, json=payload, timeout=30)
            result = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip().lower()
            return "policy" if any(k in result for k in ["policy", "정책", "규정"]) else "general"
        except: return "general"

    def general_chat(self, question: str) -> ChatResult:
        payload = {"contents": [{"role": "user", "parts": [{"text": question}]}]}
        try:
            response = requests.post(self.url, json=payload, timeout=60)
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            return ChatResult(content=text, finish_reason="stop")
        except Exception as e:
            return ChatResult(content=f"Gemini API 오류: {e}", finish_reason="error")

class LocalSTTClient:
    def __init__(self, model_size: str = "large-v3", device: str = "cuda", compute_type: str = "float16") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, file_path: str, progress_callback=None, initial_prompt=None) -> str:
        try:
            model = self._get_model()
            segments, info = model.transcribe(file_path, beam_size=5, language="ko", initial_prompt=initial_prompt)
            full_text = []
            for segment in segments:
                full_text.append(segment.text)
                if progress_callback and info.duration > 0:
                    progress = min(100, int((segment.end / info.duration) * 100))
                    progress_callback(progress)
            return " ".join(full_text).strip()
        except Exception as e:
            logger.exception("STT failed")
            raise e
