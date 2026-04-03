#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
양자 과제 공고 수집 앱 (Ubuntu Server 최종 안정화 버전 - SyntaxError 수정)
- f-string 문법 오류 최종 수정 및 코드 안정성 확보
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser
from playwright.sync_api import sync_playwright


DEFAULT_DB_PATH = Path("data/quantum_notices.json")
SOURCE_LABELS = {
    "bizinfo": "중기부/기업마당", "iris": "IRIS", "iitp": "IITP", "kait": "KAIT",
    "kisa": "KISA", "nia": "NIA", "ntis": "NTIS", "unist": "UNIST", "nrf": "NRF", "g2b": "나라장터",
}

TECH_KEYWORDS = ["양자컴퓨팅", "양자컴퓨터", "양자통신", "양자암호", "양자센서", "양자내성암호", "양자내성", "양자정보", "양자기술", "pqc", "quantum", "양자", "암호자산"]
EXCLUDE_KEYWORDS = ["마이데이터", "위치정보", "개인정보", "양자 간", "양자 협의"]

@dataclass
class Notice:
    source: str
    title: str
    url: str
    pub_date: str
    deadline_end: str
    hash: str = ""

    def __post_init__(self):
        if not self.hash:
            raw = f"{self.source}|{self.title}|{self.url}".encode("utf-8")
            self.hash = hashlib.sha256(raw).hexdigest()

# -------------------------
# 유틸리티
# -------------------------

def now_str() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def normalize(text: str) -> str: return " ".join((text or "").split())

def load_env_file(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists(): return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip("'").strip('"')

def format_date_str(raw: str) -> str:
    try:
        clean = raw.replace(".","-").replace("/","-")
        parts = [p for p in clean.split("-") if p.strip()]
        if len(parts) >= 3:
            y = parts[0] if len(parts[0]) == 4 else "20"+parts[0]
            return f"{y}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    except: pass
    return ""

def extract_deadline_from_text(text: str) -> str:
    range_match = re.findall(
        r"20\d{2}[.\s/-]\s*\d{1,2}[.\s/-]\s*\d{1,2}\.?[^\d]*?[~∼-]\s*(?:\([^)]+\)\s*)?(20\d{2}[.\s/-]\s*\d{1,2}[.\s/-]\s*\d{1,2}\.?)", text)
    if range_match: return format_date_str(range_match[-1])
    all_dates = re.findall(r"20\d{2}[./]\s*\d{1,2}[./]\s*\d{1,2}\.?", text)
    if all_dates:
        formatted = [f for d in all_dates if (f := format_date_str(d))]
        return max(formatted) if formatted else ""
    return ""
def is_expired_notice(item: dict) -> bool:
    end = item.get("deadline_end", "")
    if not end: return False
    try:
        d = datetime.strptime(end, "%Y-%m-%d").date()
        return d < datetime.now().date()
    except: pass
    return False

def is_relevant(title: str, body: str, source: str) -> bool:
    t, b = title.lower(), body.lower()
    if any(k in t for k in EXCLUDE_KEYWORDS): return False
    if any(k in t for k in TECH_KEYWORDS): return True
    if any(k in b for k in TECH_KEYWORDS): return True
    return False

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0 Safari/537.36"})
    return s

def fetch_html(session: requests.Session, url: str, params: dict | None = None, use_pw: bool = False) -> str:
    try:
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        if resp.text:
            return resp.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
    return ""

def fetch_g2b_api() -> list[Notice]:
    api_key = os.getenv("G2B_API_KEY")
    if not api_key:
        logging.error("[오류] G2B_API_KEY 환경 변수가 설정되지 않았습니다.")
        return []

    notices = []
    endpoints = ["https://apis.data.go.kr/1230000/BidPublicInfoService05/getBidPblancListInfoThng03", "https://apis.data.go.kr/1230000/BidPublicInfoService05/getBidPblancListInfoServc03"]
    today = datetime.now().strftime("%Y%m%d")
    ago = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    for url in endpoints:
        # 공공데이터포털 특유의 서비스키 중복 인코딩 방지를 위해 URL에 직접 결합
        api_url = f"{url}?serviceKey={api_key}"
        # 테스트를 위해 검색어 제거 및 XML 형식으로 시도 (JSON 오류 방지용)
        params = {"numOfRows": "30", "pageNo": "1", "inqryDiv": "1", "inqryBgnDt": f"{(datetime.now() - timedelta(days=7)).strftime('%Y%m%d')}0000", "inqryEndDt": f"{today}2359"}
        
        resp = None

        try:
            resp = requests.get(api_url, params=params, timeout=20)
        except Exception as e:
            logging.error(f"[오류] G2B API 요청 중 예외 발생 ({url}): {e}")

        if resp is None:
            logging.error(f"[오류] G2B API 호출 실패 (응답 없음): {url}")
            continue

        # 상세 디버깅: 응답 내용 일부 출력
        debug_content = resp.text[:200].replace('\n', ' ')
        if resp.status_code != 200:
            logging.error(f"[오류] G2B API 호출 실패 (코드: {resp.status_code}, 내용: {debug_content})")
            continue
        
        logging.info(f"[디버그] G2B API 응답 성공 (URL: {url[:50]}...)")
        
        # XML 또는 JSON 파싱 시도
        try:
            # JSON인 경우
            if "json" in resp.headers.get("Content-Type", "").lower() or resp.text.strip().startswith("{"):
                data = resp.json()
                items = data.get("response", {}).get("body", {}).get("items", [])
            else:
                # XML인 경우 BeautifulSoup로 파싱
                item_soup = BeautifulSoup(resp.text, "xml")
                items = item_soup.find_all("item")
                
            if isinstance(items, dict): items = [items]
            
            for item in items:
                # XML과 JSON 항목 접근 방식 통합
                if hasattr(item, "find"): # BeautifulSoup Tag인 경우
                    title = item.find("bidNtceNm").get_text() if item.find("bidNtceNm") else ""
                    bid_no = item.find("bidNtceNo").get_text() if item.find("bidNtceNo") else ""
                    pub_date = item.find("bidNtceDt").get_text() if item.find("bidNtceDt") else now_str()
                    raw_date = item.find("bidClseDt").get_text() if item.find("bidClseDt") else ""
                else: # 딕셔너리인 경우
                    title = item.get("bidNtceNm")
                    bid_no = item.get("bidNtceNo")
                    pub_date = item.get("bidNtceDt", now_str())
                    raw_date = item.get("bidClseDt") or ""
                
                # 키워드 필터링 (코드 내에서 수동 수행)
                if not is_relevant(title, "", "g2b"): continue
                
                detail_url = f"https://www.g2b.go.kr/ep/tbid/tbidView.do?bidno={bid_no}"
                deadline = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) >= 8 else ""
                notices.append(Notice(source="g2b", title=title, url=detail_url, pub_date=pub_date[:10], deadline_end=deadline))
        except Exception as e:
            logging.error(f"[오류] G2B 데이터 파싱 중 오류: {e}")
    return notices

def extract_links(soup: BeautifulSoup, base_url: str, source: str) -> list[Notice]:
    results, seen = [], set()
    
    # 블로그/SNS 링크 제외 도메인
    EXCLUDE_DOMAINS = ["blog.naver.com", "youtube.com", "youtu.be", "facebook.com", "instagram.com"]
    
    # IITP는 사업공고 테이블(.board_list)을 직접 타겟
    if source == 'ntis':
        for a_tag in soup.select('a[onclick*="fn_view"]'):
            
            title = a_tag.get_text(strip=True)
            if "양자" not in title and "퀀텀" not in title and "quantum" not in title.lower():
                continue

            onclick_attr = a_tag.get('onclick', '')
            if "fn_view('" in onclick_attr:
                uid = onclick_attr.split("fn_view('")[1].split("')")[0]
                link = f"https://www.ntis.go.kr/rndgate/eg/un/ra/view.do?roRndUid={uid}&flag=rndList"
                if link not in seen:
                    seen.add(link)
                    date_str = ""
                    tr = a_tag.find_parent("tr")
                    if tr:
                        date_cell = tr.select_one("td:nth-of-type(6)")
                        if date_cell: date_str = date_cell.get_text(strip=True)
                    results.append(Notice(title=title, url=link, source=source, pub_date=date_str, deadline_end=""))
        return results

    if source == "iitp":
        target_table = soup.select_one(".board_list")
        if target_table: soup = target_table

    # 블로그/외부 SNS 링크 제외 추가
    for a in soup.find_all("a"):
        title = normalize(a.get_text())
        if len(title) < 4: continue
        href = (a.get("href") or "").strip()
        if not href or any(x in href for x in ["#", "javascript:", "mailto:"]): continue
        if any(domain in href for domain in EXCLUDE_DOMAINS): continue
        
        container = a.find_parent(["tr", "li", "div"]) or a.parent
        ctx = normalize(container.get_text(" ")) if container else ""
        if not is_relevant(title, ctx, source): continue
        
        full_url = urljoin(base_url, href)
        if full_url in seen: continue
        seen.add(full_url)
        
        d_end = extract_deadline_from_text(title + " " + ctx)
        results.append(Notice(source=source, title=title, url=full_url, pub_date=now_str()[:10], deadline_end=d_end))
    return results

def fetch_iris_playwright() -> list[Notice]:
    notices = []
    url = "https://www.iris.go.kr/contents/retrieveBsnsAncmList.do"
    
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            logging.info(f"[IRIS 전용] 페이지 접속 시도: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logging.error(f"[IRIS 전용] 초기 접속 실패 (Timeout): {e}")
                browser.close()
                return notices
            
            # 1. 검색어 입력창 대기 및 "양자" 입력
            try:
                page.wait_for_selector("#searchWord", timeout=20000)
                page.fill("#searchWord", "양자")
                # 2. 검색 버튼 클릭 (엔터 키 입력)
                page.keyboard.press("Enter")
                logging.info("[IRIS 전용] 검색어 입력 및 엔터 수행")
            except Exception as e:
                logging.error(f"[IRIS 전용] 검색어 입력 단계 실패: {e}")
                browser.close()
                return notices
            
            # 3. 검색 결과 로딩 대기
            try:
                page.wait_for_timeout(5000) # JS 렌더링을 위해 충분히 대기
                page.wait_for_selector(".board_list tbody tr", timeout=30000)
                logging.info("[IRIS 전용] 결과 테이블 감지 성공")
            except Exception as e:
                logging.error(f"[IRIS 전용] 결과 테이블 대기 중 실패 (Timeout): {e}")
                browser.close()
                return notices
            
            # 4. 결과 파싱
            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, "html.parser")
        tbody = soup.select_one(".board_list tbody")
        
        if not tbody or "검색결과가 없습니다" in tbody.get_text():
            logging.info("[IRIS 전용] 검색 결과가 없습니다.")
            return notices
            
        for row in tbody.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 5: continue
            
            title_cell = row.select_one(".subject a") or row.select_one("td:nth-child(3) a")
            if not title_cell: continue
            
            title = normalize(title_cell.get_text())
            if not is_relevant(title, "", "iris"): continue
            
            href = title_cell.get("href", "#")
            full_url = urljoin("https://www.iris.go.kr", href)
            
            # IRIS 공고일(5번째), 마감일(6번째)
            pub_date = cols[4].get_text(strip=True).replace(".", "-") if len(cols) > 4 else now_str()[:10]
            deadline = cols[5].get_text(strip=True).replace(".", "-") if len(cols) > 5 else ""
            
            notices.append(Notice(source="iris", title=title, url=full_url, pub_date=pub_date, deadline_end=deadline))
            
        logging.info(f"[IRIS 전용] 동적 크롤링 완료: {len(notices)}건 발견")
        
    except Exception as e:
        logging.error(f"[오류] IRIS 전용 크롤링 전체 로직 중 예외 발생: {e}")
        
    return notices

# -------------------------
# 소스별 수집
# -------------------------

def _paginated(s, src, base, url_fn, m, u, force_pw=False, extractor_fn: Callable = extract_links):
    res, seen = [], set()
    for p in range(1, m + 1):
        url, params = url_fn(p)
        html = ""
        if force_pw or u:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.goto(url + ("?" + urllib.parse.urlencode(params) if params else ""), wait_until="domcontentloaded", timeout=20000)
                    html = page.content()
                    browser.close()
            except Exception as e:
                logging.error(f"Playwright failed for {src} at page {p} ({url}): {e}")
        else:
            try:
                resp = s.get(url, params=params, timeout=15)
                resp.raise_for_status()
                html = resp.text
            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed for {src} at page {p} ({url}): {e}")

        if not html:
            logging.warning(f"No HTML content for {src} at page {p}, stopping pagination.")
            break
        
        soup = BeautifulSoup(html, "html.parser")
        rows = extractor_fn(soup, base, src)
        if not rows:
            logging.info(f"No new links found for {src} at page {p}, stopping pagination.")
            break
        
        for r in rows:
            if r.hash not in seen:
                seen.add(r.hash)
                res.append(r)
    return res

def _extract_iitp_links(soup: BeautifulSoup, base_url: str, source: str) -> list[Notice]:
    from urllib.parse import urljoin as _uj
    QKWS = ["양자컴퓨팅", "양자컴퓨터", "양자통신", "양자암호", "양자센서", "양자내성", "양자정보", "양자기술", "pqc", "quantum", "양자"]
    results = []
    
    target_table = soup.select_one(".board_list")
    if target_table:
        soup = target_table

    for a in soup.find_all("a", href=True):
        title = normalize(a.get_text().strip())
        href = a.get("href", "")
        if "view.do" not in href:
            continue
        if not any(k in title.lower() for k in QKWS):
            continue
        if "2025년" in title:
            continue
        
        full_url = "https://www.iitp.kr/web/lay1/program/S1T44C51/iris/" + href.split("?")[0] + "?id=" + href.split("id=")[1].split("&")[0] if "id=" in href else _uj("https://www.iitp.kr/web/lay1/program/S1T44C51/iris/", href)
        
        notice = Notice(source=source, title=title, url=full_url, pub_date=now_str()[:10], deadline_end="")
        results.append(notice)
    return results

def _extract_kisa_links(soup: BeautifulSoup, base_url: str, source: str) -> list[Notice]:
    results, seen = [], set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        for row in soup.select("table.tbl_board.notice tbody tr"):
            link_tag = row.select_one("td.sbj.txtL a")
            if not link_tag: continue
            title = normalize(link_tag.get_text())
            href = (link_tag.get("href") or "").strip()
            if not href or not title or len(title) < 4: continue
            if not is_relevant(title, "", source): continue
            full_url = urljoin(base_url, href)
            if full_url in seen: continue
            seen.add(full_url)
            deadline_end = ""
            try:
                page.goto(full_url, wait_until="networkidle", timeout=25000)
                detail_soup = BeautifulSoup(page.content(), "html.parser")
                th_tag = detail_soup.find("th", string=re.compile(r"접수기간|사업기간|신청기간|공고기간|기간|일시"))
                if th_tag and th_tag.find_next_sibling("td"):
                    deadline_end = extract_deadline_from_text(th_tag.find_next_sibling("td").get_text())
                if not deadline_end:
                    deadline_end = extract_deadline_from_text(detail_soup.get_text(" "))
            except Exception as e:
                logging.error(f"[KISA 상세조회 오류] {full_url}: {e}")
            results.append(Notice(source=source, title=title, url=full_url, pub_date=now_str()[:10], deadline_end=deadline_end))
        browser.close()
    return results

# -------------------------
# 데이터베이스
# -------------------------

def init_db(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            hash TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT, pub_date TEXT, deadline_end TEXT
        )
    """)
    conn.commit()

def get_existing_hashes(conn: sqlite3.Connection) -> set[str]:
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.execute("SELECT hash FROM notices")
    return {row[0] for row in cursor.fetchall()}

def upsert_notices(conn: sqlite3.Connection, notices: list[Notice]):
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    data = [(n.hash, n.source, n.title, n.url, n.pub_date, n.deadline_end) for n in notices]
    cursor.executemany("""
        INSERT INTO notices (hash, source, title, url, pub_date, deadline_end)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET
            deadline_end = excluded.deadline_end
        WHERE excluded.deadline_end > deadline_end OR deadline_end IS NULL
    """, data)
    conn.commit()

def get_active_notices_from_db(conn: sqlite3.Connection) -> list[dict]:
    conn.execute("PRAGMA journal_mode=WAL;")
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.execute("SELECT * FROM notices WHERE deadline_end >= ? OR deadline_end = '' OR deadline_end IS NULL", (today,))
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def send_webhook(url: str, notices: list[dict], new_hashes: set[str]):
    if not url: return
    now = now_str()
    targets = "IITP / KAIT / 중기부 / KISA / NIA / IRIS / NTIS / UNIST / NRF / 나라장터"
    if not notices:
        msg = f"*양자 관련 최근 공고 요약*\n수집 시각: {now}\n대상: {targets}\n[양자 공고] 최근 7일 이내 키워드 매칭 공고 없음"
    else:
        new_count = len([i for i in notices if i.get('hash') in new_hashes])
        lines = [f"*양자 관련 최근 공고 요약*\n수집 시각: {now}\n대상: {targets}\n🚀 *[양자 공고] 현재 접수 중인 공고 총 {len(notices)}건 (신규 {new_count}건)*\n"]
        for i in notices[:15]:
            badge = "🆕 " if i.get('hash') in new_hashes else "• "
            deadline = i.get('deadline_end') or "미확인"
            lines.append(f"{badge}*{i.get('title')}* ({SOURCE_LABELS.get(i.get('source'), i.get('source'))}) [마감: {deadline}]\n  <{i.get('url')}>")
        msg = "\n".join(lines)
    requests.post(url, json={"text": msg}, timeout=15)

def cmd_run(args):
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    session = build_session()
    existing_hashes = get_existing_hashes(conn)
    
    extractor_map = {"extract_links": extract_links, "_extract_iitp_links": _extract_iitp_links, "_extract_kisa_links": _extract_kisa_links}
    scrapers_config_path = Path("scrapers.json")
    if not scrapers_config_path.exists(): return 1
    scrapers = json.loads(scrapers_config_path.read_text(encoding="utf-8"))
    
    all_found = []
    logging.info("[수집] IRIS 전용 크롤링 호출...")
    iris_rows = fetch_iris_playwright()
    logging.info(f"[수집] IRIS: {len(iris_rows)}건")
    all_found.extend(iris_rows)

    with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
        future_to_scraper = {}
        for scraper_config in scrapers:
            name = scraper_config["name"]
            if name == "iris": continue
            def create_url_fn(config):
                def url_fn(p):
                    url = config["pagination_url_template"].format(page=p)
                    params = config.get("pagination_params")
                    if params:
                        processed = {k: v.format(page=p) if isinstance(v, str) and "{page}" in v else v for k, v in params.items()}
                        return url, processed
                    return url, None
                return url_fn
            url_fn = create_url_fn(scraper_config)
            extractor = extractor_map.get(scraper_config["extractor_fn"])
            if not extractor: continue
            future = executor.submit(_paginated, session, name, scraper_config["base_url"], url_fn, scraper_config.get("max_pages_override") or args.max_pages, args.use_playwright, scraper_config.get("force_playwright", False), extractor)
            future_to_scraper[future] = name
        for future in as_completed(future_to_scraper):
            try:
                rows = future.result()
                logging.info(f"[수집] {future_to_scraper[future]}: {len(rows)}건")
                all_found.extend(rows)
            except Exception as e: logging.error(f"[오류] {future_to_scraper[future]} 수집 중 예외 발생: {e}")
    
    logging.info("[수집] G2B(나라장터) API 호출...")
    g2b_rows = fetch_g2b_api()
    logging.info(f"[수집] G2B: {len(g2b_rows)}건")
    all_found.extend(g2b_rows)
    
    new_hashes = {n.hash for n in all_found if n.hash not in existing_hashes}
    if all_found: upsert_notices(conn, all_found)
    conn.close()
    return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--db", default="data/quantum_notices.db")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run")
    run_p.add_argument("--max-pages", type=int, default=2)
    run_p.add_argument("--use-playwright", action="store_true")
    args = parser.parse_args()
    load_env_file(args.env_file)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    if args.command == "run": sys.exit(cmd_run(args))
    else: sys.exit(1)

if __name__ == "__main__":
    main()
