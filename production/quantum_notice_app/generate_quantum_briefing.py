#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quantum Notice Briefing Generator (Ubuntu Server 최적화 버전)
- [수정] 조회 기간을 14일에서 30일로 연장 (검증 강화)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
import google.generativeai as genai

import logging
import sqlite3

# quantum_notice_app.py와 공유하던 설정 및 함수들
SOURCE_LABELS = {
    "bizinfo": "중기부/기업마당", "iris": "IRIS", "iitp": "IITP", "kait": "KAIT",
    "kisa": "KISA", "nia": "NIA", "ntis": "NTIS", "unist": "UNIST", "nrf": "NRF", "g2b": "나라장터",
}
BRIEFING_TARGETS = "IITP / KAIT / 중기부 / KISA / NIA / IRIS / NTIS / UNIST / NRF / 나라장터"
def organization_label(source): return SOURCE_LABELS.get(source, source.upper())
def deadline_badge(d): return f"마감: {d}" if d else "마감: 미확인"
def load_env_file(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists(): return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip("'").strip('"')
# ---

DEFAULT_DB_FILE = Path("data/quantum_notices.db") # .db로 변경
DEFAULT_ENV_FILE = ".env"
LLM_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite") # 모델명 수정
LLM_MAX_ITEMS = int(os.getenv("BRIEFING_LLM_MAX_ARTICLES", "5"))
BRIEFING_DAYS = 30 # 기존 14일에서 30일로 상향
MAX_ITEMS = int(os.getenv("BRIEFING_MAX_ITEMS", "10"))

def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logging.warning("GEMINI_API_KEY가 설정되지 않아 LLM 요약 기능을 비활성화합니다.")
        return None
    try:
        genai.configure(api_key=api_key)
        client = genai.GenerativeModel(LLM_MODEL)
        return client
    except Exception as e:
        logging.error(f"Gemini 클라이언트 초기화 실패: {e}")
        return None

def clean_text(value: str) -> str:
    return " ".join((value or "").replace("<b>", "").replace("</b>", "").split())

def extract_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw: return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1: return None
    try: return json.loads(raw[start : end + 1])
    except json.JSONDecodeError: return None

def fallback_summary(row: dict) -> str:
    org = organization_label(row.get("source", ""))
    return f"{org}에서 게시한 공고입니다."

def fallback_task_type(row: dict) -> str:
    title = clean_text(row.get("title", "")).lower()
    if "양자내성" in title or "pqc" in title:
        return "양자내성암호"
    if "양자암호" in title or "암호" in title:
        return "양자암호"
    if "양자통신" in title or "통신" in title:
        return "양자통신"
    if "양자센서" in title or "센서" in title:
        return "양자센서"
    if "양자컴퓨팅" in title or "양자컴퓨터" in title or "컴퓨팅" in title:
        return "양자컴퓨팅"
    return "양자 기술 일반"

def enrich_notice_with_llm(client, row: dict):
    if client is None: return None
    source_text = f"기관: {organization_label(row.get('source'))}\n공고명: {row.get('title')}\n마감: {row.get('deadline_end')}\n링크: {row.get('url')}"
    prompt = f"다음 양자 기술 관련 공고를 읽고 JSON 객체 형식으로만 답하라. 다른 설명은 모두 제외한다. (task_type: 공고가 다루는 양자 과제 분야를 2~8글자로 요약, summary: 2문장 요약, impact: 산업적/기술적 의미, target: 추천 대상 기업/연구자)\n\n공고:\n{source_text}"
    try:
        response = client.generate_content(prompt)
        return extract_json_object(getattr(response, "text", ""))
    except Exception as e:
        logging.error(f"LLM 요약 생성 중 오류 발생: {e}")
        return None

def select_rows(db_path: Path, keep_days: int, max_items: int) -> list[dict]:
    """SQLite DB에서 브리핑할 공고를 선택합니다."""
    if not db_path.exists():
        logging.error(f"데이터베이스 파일({db_path})을 찾을 수 없습니다.")
        return []
    
    conn = sqlite3.connect(db_path)
    today_str = datetime.now().strftime("%Y-%m-%d")
    since_date = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")

    query = """
        SELECT * FROM notices 
        WHERE 
            (deadline_end >= ? OR deadline_end = '' OR deadline_end IS NULL)
            AND pub_date >= ?
        ORDER BY pub_date DESC
        LIMIT ?
    """
    try:
        cursor = conn.execute(query, (today_str, since_date, max_items))
        columns = [description[0] for description in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"데이터베이스 조회 오류: {e}")
        rows = []
    finally:
        conn.close()
        
    return rows

def generate_briefing(db_path: Path, keep_days: int, max_items: int) -> str:
    rows = select_rows(db_path, keep_days, max_items)
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    if not rows:
        return f"📅 *오늘의 양자 공고 브리핑 ({current_date})*\n대상: {BRIEFING_TARGETS}\n\n최근 {keep_days}일 기준 분석할 새로운 공고가 없습니다."

    client = get_gemini_client()
    lines = [f"📅 *오늘의 양자 공고 브리핑 ({current_date})*", f"대상: {BRIEFING_TARGETS}", "", "🚀 *주요 공고 요약*"]
    
    for idx, row in enumerate(rows, 1):
        enrichment = enrich_notice_with_llm(client, row) if idx <= LLM_MAX_ITEMS else None
        summary = enrichment.get("summary") if enrichment else fallback_summary(row)
        task_type = enrichment.get("task_type") if enrichment else fallback_task_type(row)
        lines.append(f"\n{idx}. *{row.get('title')}*")
        lines.append(f"• 기관: {row.get('organization') or organization_label(row.get('source'))} | {deadline_badge(row.get('deadline_end'))}")
        lines.append(f"• 과제 유형: {task_type or fallback_task_type(row)}")
        lines.append(f"• 요약: {summary}")
        lines.append(f"• 링크: <{row.get('url')}>")
        
    return "\n".join(lines)

def send_slack_briefing(url: str, message: str) -> bool:
    if not url: return False
    try:
        response = requests.post(url, json={"text": message}, timeout=20)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"슬랙 전송 실패: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--db", default=str(DEFAULT_DB_FILE))
    parser.add_argument("--days", type=int, default=BRIEFING_DAYS)
    parser.add_argument("--limit", type=int, default=MAX_ITEMS)
    parser.add_argument("-s", "--slack", action="store_true", help="Send the briefing to Slack.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    load_env_file(args.env_file)
    
    logging.info(f"브리핑 생성을 시작합니다 (최근 {args.days}일 데이터 분석)...")
    briefing = generate_briefing(Path(args.db), args.days, args.limit)
    
    if args.slack:
        webhook_urls = os.getenv("NOTICE_WEBHOOK_URL")
        if not webhook_urls:
            logging.error("NOTICE_WEBHOOK_URL이 설정되지 않아 슬랙 전송에 실패했습니다.")
        else:
            urls = [u.strip() for u in webhook_urls.replace('\n', ',').split(',') if u.strip()]
            success = False
            for url in urls:
                if send_slack_briefing(url, briefing):
                    success = True
            if success:
                logging.info(f"슬랙 브리핑 전송 완료 (총 {len(urls)}곳).")
            else:
                logging.error("슬랙 브리핑 전송 실패.")
    else:
        # 콘솔 출력의 경우, logging 대신 print를 사용하여 깔끔한 결과물만 보여줌
        print("\n" + "=" * 50 + "\n" + briefing + "\n" + "=" * 50)

if __name__ == "__main__":
    main()
