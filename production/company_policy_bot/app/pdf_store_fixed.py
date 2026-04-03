from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader
from rank_bm25 import BM25Okapi


logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
WHITESPACE_PATTERN = re.compile(r"\s+")


KEYWORD_HINTS: dict[str, tuple[str, ...]] = {
    "연차": ("연차", "연차휴가", "연차유급휴가", "휴가"),
    "휴가": ("휴가", "연차", "연차휴가", "연차유급휴가"),
    "수습": ("수습", "수습기간", "시용"),
    "수습기간": ("수습기간", "수습", "시용"),
    "시용": ("시용", "수습", "수습기간"),
    "출장": ("출장", "출장비", "여비", "숙박비", "업무경비"),
    "출장비": ("출장비", "출장", "여비", "숙박비"),
    "경비": ("경비", "업무경비", "실비", "교통비"),
    "업무경비": ("업무경비", "경비", "실비", "교통비"),
    "연장근무": ("연장근무", "초과근무", "시간외근무", "연장근로"),
    "초과근무": ("초과근무", "연장근무", "시간외근무", "연장근로"),
    "퇴직": ("퇴직", "퇴직금", "퇴직급여"),
    "징계": ("징계", "해고", "표창"),
    "근로시간": ("근로시간", "소정근로시간", "휴게"),
}

DIRECT_PRIORITY_TERMS: dict[str, tuple[str, ...]] = {
    "연차": ("연차유급휴가", "연차휴가", "연차", "15일", "3년 이상", "25일", "제40조", "제41조"),
    "휴가": ("연차유급휴가", "연차휴가", "휴가", "15일", "3년 이상", "25일", "제40조", "제41조"),
    "수습": ("수습기간", "수습", "시용", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "수습기간": ("수습기간", "수습", "시용", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "시용": ("시용", "수습", "수습기간", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "출장": ("출장", "출장비지급규정", "출장비", "여비", "숙박비", "일비", "교통비", "실비"),
    "출장비": ("출장비지급규정", "출장비", "출장", "여비", "숙박비", "일비", "실비"),
    "경비": ("업무경비처리규정", "업무경비", "경비", "실비", "교통비", "정산"),
    "업무경비": ("업무경비처리규정", "업무경비", "경비", "실비", "교통비", "정산"),
    "연장근무": ("연장근무", "연장근무 지침", "연장근무 업무처리지침", "초과근무", "시간외근무", "수당"),
    "초과근무": ("초과근무", "연장근무", "시간외근무", "연장근로", "수당"),
    "퇴직": ("퇴직급여", "퇴직금", "퇴직"),
    "징계": ("징계", "해고"),
    "근로시간": ("근로시간", "소정근로시간"),
}

SPECIALIZED_FILTERS: dict[str, tuple[str, ...]] = {
    "연차": ("연차유급휴가", "연차휴가", "15일", "3년 이상", "25일", "제40조", "제41조"),
    "휴가": ("연차유급휴가", "연차휴가", "15일", "3년 이상", "25일", "제40조", "제41조"),
    "수습": ("수습기간", "수습", "시용", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "수습기간": ("수습기간", "수습", "시용", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "시용": ("시용", "수습", "수습기간", "3개월", "제9조", "수습 평가", "본 채용", "채용 취소", "근속년수", "시용된 날"),
    "출장": ("출장비지급규정", "출장", "출장비", "여비", "숙박비", "실비"),
    "출장비": ("출장비지급규정", "출장비", "출장", "여비", "숙박비", "실비"),
    "경비": ("업무경비처리규정", "업무경비", "경비", "실비", "교통비", "정산"),
    "업무경비": ("업무경비처리규정", "업무경비", "경비", "실비", "교통비", "정산"),
    "연장근무": ("연장근무 업무처리지침", "연장근무 지침", "연장근무", "초과근무", "시간외근무", "수당"),
    "초과근무": ("초과근무", "연장근무", "시간외근무", "연장근로", "수당"),
    "퇴직": ("퇴직급여", "퇴직금", "퇴직"),
    "징계": ("징계", "해고"),
    "근로시간": ("근로시간", "소정근로시간"),
}

GENERAL_TERMS = (
    "근로계약",
    "명확히 제시",
    "서면",
    "취업규칙을 제시하거나 교부",
)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_name: str
    page_number: int
    content: str


def normalize_text(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


class PdfKnowledgeBase:
    def __init__(self, pdf_root: str, chunk_size: int = 1200, chunk_overlap: int = 200) -> None:
        self.pdf_root = Path(pdf_root)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._chunks: list[Chunk] = []
        self._tokenized_chunks: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._fingerprint: tuple[tuple[str, int, int], ...] = ()

    def refresh(self) -> None:
        self.pdf_root.mkdir(parents=True, exist_ok=True)
        pdf_paths = self._pdf_paths()
        chunks = list(self._load_chunks(pdf_paths))
        tokenized = [tokenize(chunk.content) for chunk in chunks]

        self._chunks = chunks
        self._tokenized_chunks = tokenized
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self._fingerprint = self._build_fingerprint(pdf_paths)
        logger.info("Loaded %s chunks from %s PDF files", len(chunks), len(pdf_paths))

    def refresh_if_needed(self) -> None:
        self.pdf_root.mkdir(parents=True, exist_ok=True)
        pdf_paths = self._pdf_paths()
        fingerprint = self._build_fingerprint(pdf_paths)
        if fingerprint != self._fingerprint:
            self.refresh()

    def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        if not self._bm25:
            return []

        tokenized_query = tokenize(query)
        if not tokenized_query:
            return []

        topic_keys = self._topic_keys(tokenized_query)
        expanded_query = self._expand_query_tokens(tokenized_query, topic_keys)
        scores = self._bm25.get_scores(expanded_query)
        ranking_scores = [
            self._ranking_score(self._chunks[idx], scores[idx], expanded_query, topic_keys)
            for idx in range(len(scores))
        ]
        ranked_indices = sorted(
            range(len(scores)),
            key=lambda idx: ranking_scores[idx],
            reverse=True,
        )

        ranked_indices = self._prioritize_direct_matches(ranked_indices, expanded_query, topic_keys)
        ranked_indices = self._filter_to_specialized_matches(ranked_indices, expanded_query, topic_keys)

        target_count = max(top_k, min(len(ranked_indices), len(topic_keys) + 1))

        results: list[Chunk] = []
        seen_chunk_ids: set[str] = set()
        seen_sources: set[str] = set()

        # For multi-policy questions, prefer pulling from different source documents first.
        if len(topic_keys) >= 2:
            for idx in ranked_indices:
                if ranking_scores[idx] <= 0:
                    continue
                chunk = self._chunks[idx]
                if chunk.source_name in seen_sources:
                    continue
                results.append(chunk)
                seen_chunk_ids.add(chunk.chunk_id)
                seen_sources.add(chunk.source_name)
                if len(results) >= target_count:
                    return results

        for idx in ranked_indices:
            if ranking_scores[idx] <= 0:
                continue
            chunk = self._chunks[idx]
            if chunk.chunk_id in seen_chunk_ids:
                continue
            results.append(chunk)
            seen_chunk_ids.add(chunk.chunk_id)
            if len(results) >= target_count:
                break
        return results

    def _ranking_score(
        self,
        chunk: Chunk,
        bm25_score: float,
        query_tokens: list[str],
        topic_keys: tuple[str, ...],
    ) -> float:
        content_lower = chunk.content.lower()
        unique_tokens = set(query_tokens)
        coverage = sum(1 for token in unique_tokens if token in content_lower)
        exact_hits = sum(content_lower.count(token) for token in unique_tokens)
        hint_bonus = 0.0
        direct_bonus = 0.0
        general_penalty = 0.0
        specialized_bonus = 0.0

        for token in unique_tokens:
            for hint in KEYWORD_HINTS.get(token, ()): 
                if hint in content_lower:
                    hint_bonus += 2.0
            for term in DIRECT_PRIORITY_TERMS.get(token, ()): 
                if term.lower() in content_lower:
                    direct_bonus += 8.0
            for term in SPECIALIZED_FILTERS.get(token, ()): 
                if term.lower() in content_lower:
                    specialized_bonus += 4.0

        for topic_key in topic_keys:
            for hint in KEYWORD_HINTS.get(topic_key, ()): 
                if hint in content_lower:
                    hint_bonus += 2.0
            for term in DIRECT_PRIORITY_TERMS.get(topic_key, ()): 
                if term.lower() in content_lower:
                    direct_bonus += 8.0
            for term in SPECIALIZED_FILTERS.get(topic_key, ()): 
                if term.lower() in content_lower:
                    specialized_bonus += 4.0

        has_direct_term = direct_bonus > 0
        if not has_direct_term and any(term in content_lower for term in GENERAL_TERMS):
            general_penalty = 8.0

        return bm25_score + (coverage * 2.5) + (exact_hits * 0.5) + hint_bonus + direct_bonus + specialized_bonus - general_penalty

    def _prioritize_direct_matches(self, ranked_indices: list[int], query_tokens: list[str], topic_keys: tuple[str, ...]) -> list[int]:
        priority_terms = self._priority_terms(query_tokens, topic_keys)
        if not priority_terms:
            return ranked_indices

        direct_match_indices: list[int] = []
        other_indices: list[int] = []
        for idx in ranked_indices:
            content_lower = self._chunks[idx].content.lower()
            if any(term.lower() in content_lower for term in priority_terms):
                direct_match_indices.append(idx)
            else:
                other_indices.append(idx)

        if direct_match_indices:
            return direct_match_indices + other_indices
        return ranked_indices

    def _filter_to_specialized_matches(self, ranked_indices: list[int], query_tokens: list[str], topic_keys: tuple[str, ...]) -> list[int]:
        specialized_terms = self._specialized_terms(query_tokens, topic_keys)
        if not specialized_terms:
            return ranked_indices

        specialized_indices = [
            idx for idx in ranked_indices if any(term.lower() in self._chunks[idx].content.lower() for term in specialized_terms)
        ]
        if specialized_indices:
            return specialized_indices
        return ranked_indices

    def _priority_terms(self, query_tokens: list[str], topic_keys: tuple[str, ...]) -> tuple[str, ...]:
        ordered_terms: list[str] = []
        for token in query_tokens:
            for term in DIRECT_PRIORITY_TERMS.get(token, ()): 
                if term not in ordered_terms:
                    ordered_terms.append(term)
        for topic_key in topic_keys:
            for term in DIRECT_PRIORITY_TERMS.get(topic_key, ()): 
                if term not in ordered_terms:
                    ordered_terms.append(term)
        return tuple(ordered_terms)

    def _specialized_terms(self, query_tokens: list[str], topic_keys: tuple[str, ...]) -> tuple[str, ...]:
        ordered_terms: list[str] = []
        for token in query_tokens:
            for term in SPECIALIZED_FILTERS.get(token, ()): 
                if term not in ordered_terms:
                    ordered_terms.append(term)
        for topic_key in topic_keys:
            for term in SPECIALIZED_FILTERS.get(topic_key, ()): 
                if term not in ordered_terms:
                    ordered_terms.append(term)
        return tuple(ordered_terms)

    def _expand_query_tokens(self, query_tokens: list[str], topic_keys: tuple[str, ...]) -> list[str]:
        expanded: list[str] = list(query_tokens)
        for token in query_tokens:
            for hint in KEYWORD_HINTS.get(token, ()): 
                hint_lower = hint.lower()
                if hint_lower not in expanded:
                    expanded.append(hint_lower)
            for term in DIRECT_PRIORITY_TERMS.get(token, ()): 
                term_lower = term.lower()
                if term_lower not in expanded:
                    expanded.append(term_lower)
        for topic_key in topic_keys:
            if topic_key not in expanded:
                expanded.append(topic_key)
            for hint in KEYWORD_HINTS.get(topic_key, ()): 
                hint_lower = hint.lower()
                if hint_lower not in expanded:
                    expanded.append(hint_lower)
            for term in DIRECT_PRIORITY_TERMS.get(topic_key, ()): 
                term_lower = term.lower()
                if term_lower not in expanded:
                    expanded.append(term_lower)
        return expanded

    def _topic_keys(self, query_tokens: list[str]) -> tuple[str, ...]:
        matched_keys: list[str] = []
        known_keys = set(KEYWORD_HINTS) | set(DIRECT_PRIORITY_TERMS) | set(SPECIALIZED_FILTERS)
        for token in query_tokens:
            for key in known_keys:
                if key in token or token in key:
                    if key not in matched_keys:
                        matched_keys.append(key)
        return tuple(matched_keys)

    def _load_chunks(self, pdf_paths: Iterable[Path]) -> Iterable[Chunk]:
        for pdf_path in pdf_paths:
            try:
                reader = PdfReader(str(pdf_path))
            except Exception:
                logger.exception("Failed to open PDF: %s", pdf_path)
                continue

            loaded_pages = 0
            for page_index, page in enumerate(reader.pages, start=1):
                try:
                    page_text = normalize_text(page.extract_text() or "")
                except Exception:
                    logger.exception("Failed to extract text from PDF %s page %s", pdf_path.name, page_index)
                    continue
                if not page_text:
                    continue
                loaded_pages += 1
                for chunk_index, chunk_text in enumerate(self._chunk_text(page_text), start=1):
                    yield Chunk(
                        chunk_id=f"{pdf_path.stem}-p{page_index}-c{chunk_index}",
                        source_name=pdf_path.name,
                        page_number=page_index,
                        content=chunk_text,
                    )

            logger.info("Indexed PDF %s pages_with_text=%s", pdf_path.name, loaded_pages)

    def _chunk_text(self, text: str) -> Iterable[str]:
        if len(text) <= self.chunk_size:
            yield text
            return

        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            yield text[start:end]
            if end >= len(text):
                break
            start = max(0, end - self.chunk_overlap)

    def _pdf_paths(self) -> list[Path]:
        pdf_paths = sorted(
            [path for path in self.pdf_root.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"],
            key=lambda path: path.name.lower(),
        )
        return pdf_paths

    def _build_fingerprint(self, pdf_paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (path.name, int(path.stat().st_mtime), path.stat().size) for path in pdf_paths
        )
