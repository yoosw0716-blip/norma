from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.llm_client import GeminiClient

logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    "bizinfo": "중기부/기업마당",
    "iris": "IRIS",
    "iitp": "IITP",
    "kait": "KAIT",
    "kisa": "KISA",
    "nia": "NIA",
    "ntis": "NTIS",
    "unist": "UNIST",
    "nrf": "NRF",
    "g2b": "나라장터",
}

SOURCE_ALIASES = {
    "kisa": "kisa",
    "iitp": "iitp",
    "kait": "kait",
    "nia": "nia",
    "iris": "iris",
    "ntis": "ntis",
    "unist": "unist",
    "nrf": "nrf",
    "나라장터": "g2b",
    "g2b": "g2b",
    "중기부": "bizinfo",
    "기업마당": "bizinfo",
}

NOISE_TOKENS = (
    "양자공고",
    "양자 공고",
    "양자과제",
    "양자 과제",
    "양자사업",
    "양자 사업",
    "양자관련",
    "양자 관련",
    "양자컴퓨터",
    "양자 컴퓨터",
    "양자컴퓨팅",
    "양자 컴퓨팅",
    "공고",
    "과제",
    "사업",
    "검색",
    "찾아줘",
    "찾아 줘",
    "보여줘",
    "보여 줘",
    "알려줘",
    "알려 줘",
    "조회",
    "최근",
    "현재",
    "접수중",
    "접수 중",
    "접수",
    "있어",
    "있어?",
    "있나요",
    "있나요?",
    "뭐",
    "뭐야",
    "뭐있어",
    "뭐 있어",
    "인",
)


@dataclass(frozen=True)
class QuantumNotice:
    source: str
    title: str
    url: str
    pub_date: str
    deadline_end: str


class QuantumNoticeStore:
    def __init__(self, db_path: str, max_results: int = 5) -> None:
        self.db_path = Path(db_path)
        self.max_results = max_results

    def is_available(self) -> bool:
        return self.db_path.exists()

    def search_with_llm(self, question: str, gemini_client: Optional['GeminiClient'] = None) -> list[QuantumNotice]:
        if not self.is_available():
            return []

        # 1. 의도 분석 (LLM 활용)
        intent = self._analyze_intent_llm(question, gemini_client)
        
        source = intent.get("source")
        keyword = intent.get("keyword")
        
        # 키워드 정제: '공고', '과제' 등 검색에 방해되는 일반 명사 제거
        if keyword:
            keyword = re.sub(r'(공고|과제|사업|모집|지원|최근|알려줘|보여줘|찾아줘|양자공고|뭐있어)', '', keyword).strip()
            if not keyword or keyword == "양자":
                keyword = "양자"

        days = intent.get("days", 30)
        return self._execute_search(source, keyword, days)

    def _execute_search(self, source: Optional[str], keyword: Optional[str], days: int) -> list[QuantumNotice]:
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        since_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        query = """
            SELECT source, title, url, pub_date, deadline_end
            FROM notices
            WHERE (deadline_end >= ? OR deadline_end = '' OR deadline_end IS NULL)
              AND pub_date >= ?
        """
        params: list[object] = [today_str, since_date]

        if source:
            query += " AND source = ?"
            params.append(source)

        if keyword:
            query += " AND (title LIKE ? OR source LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        query += " ORDER BY deadline_end ASC, pub_date DESC LIMIT ?"
        params.append(self.max_results)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
            
            results = [QuantumNotice(*row) for row in rows]
            
            # 결과가 없고 검색 기간이 짧으면 기간을 120일로 늘려 다시 검색 (마감 공고 포함 여부와 관계없이)
            if not results and days <= 30:
                return self._execute_search(source, keyword, 120)
                
            return results
        except Exception as e:
            logger.exception("Quantum notice search failed")
            return []

    def format_answer_with_llm(self, question: str, gemini_client: 'GeminiClient') -> str:
        notices = self.search_with_llm(question, gemini_client)
        
        if not notices:
            return f"죄송합니다. 현재 '{question}' 질문과 관련된 진행 중인 양자 공고를 찾지 못했습니다."

        # 2. 결과 요약 (LLM 활용)
        return self._summarize_results_llm(question, notices, gemini_client)

    def _analyze_intent_llm(self, question: str, gemini_client: Optional['GeminiClient']) -> dict:
        default_intent = {
            "source": self._extract_source(question),
            "keyword": self._extract_keyword(question),
            "days": 30
        }
        
        if not gemini_client:
            return default_intent

        prompt = f"""사용자의 질문을 분석하여 양자 공고 검색 조건을 JSON 형식으로 추출하세요.
질문: "{question}"

가능한 소스 리스트: {list(SOURCE_ALIASES.keys())}

추출할 JSON 필드:
- source: 위 리스트 중 하나 (없으면 null)
- keyword: 핵심 검색어 (없으면 null)
- days: 며칠 전부터 검색할지 숫자 (기본값 30, 질문에 '최근 일주일' 등이 있으면 7 등으로 설정)

응답은 오직 JSON 형식으로만 하세요. 예: {{"source": "iris", "keyword": "암호", "days": 7}}"""

        try:
            res = gemini_client.general_chat(prompt)
            json_match = re.search(r'\{.*\}', res.content.replace('\n', ' '), re.DOTALL)
            if json_match:
                intent = json.loads(json_match.group())
                if intent.get("source"):
                    intent["source"] = SOURCE_ALIASES.get(intent["source"], intent["source"])
                return intent
        except Exception:
            logger.warning("LLM intent analysis failed, using defaults")
        
        return default_intent

    def _summarize_results_llm(self, question: str, notices: list[QuantumNotice], gemini_client: 'GeminiClient') -> str:
        notice_list_str = "\n".join([
            f"- [{SOURCE_LABELS.get(n.source, n.source)}] {n.title} (마감: {n.deadline_end or '확인요망'}) - {n.url}"
            for n in notices
        ])
        
        prompt = f"""사용자의 질문에 대해 검색된 양자 공고 리스트를 바탕으로 친절하고 정중하게 요약 답변을 작성하세요.
사용자 질문: "{question}"

검색된 공고 리스트:
{notice_list_str}

지침:
1. 답변은 한국어로 작성하세요.
2. 각 공고의 제목과 기관, 마감일, 링크를 포함하세요.
3. 가장 중요해 보이는 공고를 먼저 언급하거나 전체적인 흐름을 요약해주세요.
4. 마지막에는 "더 자세한 내용은 각 공고의 링크를 확인해주세요."라는 문구를 포함하세요."""

        try:
            res = gemini_client.general_chat(prompt)
            return res.content.strip()
        except Exception:
            lines = ["검색 결과입니다."]
            for n in notices:
                lines.append(f"• [{SOURCE_LABELS.get(n.source, n.source)}] {n.title} (마감: {n.deadline_end or '확인요망'})\n  {n.url}")
            return "\n".join(lines)

    def search(self, question: str) -> list[QuantumNotice]:
        return self.search_with_llm(question)

    def format_answer(self, question: str) -> str:
        notices = self.search(question)
        if not notices: return "현재 조건에 맞는 양자 공고가 없습니다."
        lines = ["현재 확인된 양자 공고입니다."]
        for idx, notice in enumerate(notices, 1):
            org = SOURCE_LABELS.get(notice.source, notice.source.upper())
            lines.append(f"{idx}. {notice.title} ({org})\n   {notice.url}")
        return "\n".join(lines)

    def _extract_source(self, question: str) -> str:
        lowered = question.lower()
        for alias, source in SOURCE_ALIASES.items():
            if alias.lower() in lowered:
                return source
        return ""

    def _extract_keyword(self, question: str) -> str:
        keyword = question
        for token in NOISE_TOKENS:
            keyword = keyword.replace(token, " ")
        for alias in SOURCE_ALIASES:
            keyword = keyword.replace(alias, " ")
        parts = []
        for part in keyword.split():
            cleaned = part.strip(" ?!.,")
            if len(cleaned) >= 2:
                parts.append(cleaned)
        return " ".join(parts[:3])
