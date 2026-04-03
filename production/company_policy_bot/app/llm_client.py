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
            "당신은 IT/AI 기업의 시니어 프로젝트 매니저이자 최고 수준의 회의록 작성 비서입니다.\n"
            "주어진 녹취록을 공식 회의록으로 작성하되, 아래 원칙을 엄격히 지키세요.\n"
            "1. 문체: 서술형(강조되었다, 의견이 있었다 등) 금지. '-함', '-임' 등의 명사형 종결어미 사용.\n"
            "2. 간결성: 핵심만 추출하여 정보 밀도를 높임.\n"
            "3. 용어: 실제 IT 실무 용어(LLM, SLM, AI 에이전트 등)를 문맥에 맞게 자연스럽게 사용.\n"
            "4. 시간: 날짜는 현재 시점(2026년 기준)에 맞게 보정하여 작성."
        )
        user_prompt = f"""다음 녹취록을 분석하여 지정된 마크다운 템플릿에 맞게 회의록을 작성하세요.

[회의록 템플릿]
# 📝 회의록: [핵심 주제 단어]

**📅 일시**: 2026년 4월 3일 (금)
**👥 참석자**: [파악된 참석자]

---
## 💡 한 줄 요약
> [회의의 핵심 결론 1문장]

## 🗣️ 주요 논의 사항
- **[주제 1 소제목]**
  - [논의 내용 1]
  - [논의 내용 2]
- **[주제 2 소제목]**
  - [논의 내용 1]

## 🤝 협의 사항
- [결정/합의된 원칙 및 방향성 (액션 아이템과 중복 배제)]

## 🚀 액션 아이템
- [ ] (담당자) [구체적인 작업 내용] - [기한]

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
