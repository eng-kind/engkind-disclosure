"""KIND '오늘의 공시'를 30분마다 확인해 누적 상태 파일에 반영한다.

GitHub Actions(.github/workflows/kind_collect.yml)가 실행한다.

  python kind_collector.py fetch --out fetched.json [--date 2026-11-24] [--debug-dir debug]
  python kind_collector.py merge --fetched fetched.json --state STATE.json \
         --status STATUS.json [--seed initial_disclosures.json]
  python kind_collector.py parse --html saved_page.html --date 2026-11-24   # 저장한 화면 점검용

KIND 차단을 우회하지 않는다. 접속이 거부되면 원인을 상태 파일에 기록하고 멈춘다.
"""
import argparse
import json
import re
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from lxml import html as lxml_html

import engdiscl_rules as rules

KIND_BASE = "https://kind.krx.co.kr"
LIST_URL = f"{KIND_BASE}/disclosure/todaydisclosure.do"
MAIN_URL = f"{LIST_URL}?method=searchTodayDisclosureMain"
VIEWER_URL = f"{KIND_BASE}/common/disclsviewer.do?method=search&acptno={{acptno}}"
PAGE_SIZE = 100
MAX_PAGES = 40
PAGE_DELAY_SECONDS = 1.5
CONTACT = "engkind@krx.co.kr"
HEADERS = {
    # 정체를 숨기지 않는다. KRX IT에 허용을 요청할 때 이 값으로 식별할 수 있다.
    "User-Agent": f"Mozilla/5.0 (compatible; KRX-engkind-disclosure-monitor/1.0; +mailto:{CONTACT})",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": MAIN_URL,
}
EMPTY_MARKERS = ("조회된 결과가 없습니다", "공시내역이 없습니다", "공시 내역이 없습니다",
                 "검색결과가 없습니다", "결과가 없습니다")


class KindBlocked(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


# ---------------------------------------------------------------------
# 화면 해석
# ---------------------------------------------------------------------
def _onclick_arg(element, function_name: str) -> str:
    match = re.search(rf"{function_name}\(\s*'([^']*)'", element.get("onclick", "") + element.get("href", ""))
    return match.group(1).strip() if match else ""


def _market(td) -> str:
    alts = " ".join(td.xpath(".//img/@alt") + td.xpath(".//img/@src") + td.xpath(".//@class"))
    if "유가" in alts or "icn_t_yu" in alts:
        return "유가증권"
    if "코스닥" in alts or "icn_t_ko" in alts:
        return "코스닥"
    if "코넥스" in alts or "icn_t_kn" in alts:
        return "코넥스"
    return ""


def parse_list_page(page_html: str, date_str: str) -> List[Dict[str, Any]]:
    """KIND 오늘의 공시 목록 화면(HTML) 한 페이지를 앱의 행 형식으로 바꾼다."""
    doc = lxml_html.fromstring(page_html)
    rows = []
    for tr in doc.xpath("//tr[td]"):
        tds = tr.xpath("./td")
        title_idx = next((i for i, td in enumerate(tds)
                          if td.xpath(".//*[contains(@onclick,'openDisclsViewer') or contains(@href,'openDisclsViewer')]")), None)
        if title_idx is None:
            continue
        time_text = next((rules.clean_text(td.text_content()) for td in tds[:title_idx]
                          if re.fullmatch(r"\d{1,2}:\d{2}", rules.clean_text(td.text_content()))), "")
        if not time_text:
            continue
        title_a = tds[title_idx].xpath(".//*[contains(@onclick,'openDisclsViewer') or contains(@href,'openDisclsViewer')]")[0]
        acptno = re.sub(r"[^0-9]", "", _onclick_arg(title_a, "openDisclsViewer"))
        title_text = rules.clean_text(title_a.text_content())
        title_attr = rules.clean_text(title_a.get("title"))
        title = title_attr if len(title_attr) >= len(title_text) else title_text

        company_code, company_name, market = "", "", ""
        for td in tds[:title_idx]:
            links = td.xpath(".//*[contains(@onclick,'companysummary_open') or contains(@href,'companysummary_open')]")
            if links:
                company_code = _onclick_arg(links[0], "companysummary_open")
                company_name = rules.clean_text(links[0].text_content())
                market = _market(td)
                break
        submitter = rules.clean_text(tds[title_idx + 1].text_content()) if title_idx + 1 < len(tds) else ""
        disclosure_time = rules.iso_dt(f"{date_str} {time_text}")
        if not title or not disclosure_time or not re.fullmatch(r"[0-9]{14}", acptno):
            continue
        rows.append({
            "공시시각": disclosure_time,
            "회사코드": rules.normalize_code(company_code),
            "종목코드": "",
            "코드종류": "회사코드" if company_code else "",
            "회사명": company_name,
            "공시제목": title,
            "제출인": submitter,
            "상세URL": VIEWER_URL.format(acptno=acptno),
            "접수번호": acptno,
            "시장": market,
            "링크상태": "KIND 목록 링크",
        })
    return rows


def looks_like_list_page(page_html: str) -> bool:
    return "<table" in page_html.lower() or any(marker in page_html for marker in EMPTY_MARKERS)


# ---------------------------------------------------------------------
# KIND 조회
# ---------------------------------------------------------------------
def _post_page(session: requests.Session, date_str: str, page: int) -> str:
    data = {
        "method": "searchTodayDisclosureSub",
        "currentPageSize": str(PAGE_SIZE),
        "pageIndex": str(page),
        "orderMode": "0",
        "orderStat": "D",
        "marketType": "",
        "forward": "todaydisclosure_sub",
        "searchMode": "",
        "searchCodeType": "",
        "chose": "S",
        "todayFlag": "N",
        "repIsuSrtCd": "",
        "kosdaqSegment": "",
        "selDate": date_str,
        "searchCorpName": "",
        "copyUrl": "",
    }
    last_error = None
    for attempt in range(3):
        try:
            response = session.post(LIST_URL, data=data, timeout=(10, 40))
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code in (401, 403, 429):
            raise KindBlocked(f"KIND가 접속을 거부했습니다 (HTTP {response.status_code})",
                              response.status_code, response.text[:20000])
        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code != 200:
            raise KindBlocked(f"KIND 응답 오류 (HTTP {response.status_code})",
                              response.status_code, response.text[:20000])
        response.encoding = response.encoding or "utf-8"
        if response.encoding.lower() in ("iso-8859-1", "latin-1"):
            response.encoding = response.apparent_encoding or "utf-8"
        text = response.text
        if not looks_like_list_page(text):
            raise KindBlocked("KIND가 공시목록 대신 다른 화면을 보냈습니다 (차단·점검 화면일 수 있음)",
                              200, text[:20000])
        return text
    raise KindBlocked(f"KIND 연결 실패: {last_error}")


def should_have_rows(date_str: str) -> bool:
    """그날 공시가 0건이면 이상하다고 볼 수 있는 시점인지.

    새벽·주말·휴일에는 당일 공시가 0건일 수 있으므로 정상으로 본다.
    평일 오전 10시~오후 6시(한국시간)에 오늘 목록이 비어 있을 때만 오류로 본다.
    """
    now = rules.now_kst()
    return date_str == now.date().isoformat() and now.weekday() < 5 and 10 <= now.hour < 18


def fetch_date(session: requests.Session, date_str: str, debug_dir: Optional[Path],
               max_pages: int = MAX_PAGES) -> Tuple[List[Dict[str, Any]], int]:
    collected, seen = [], set()
    for page in range(1, max_pages + 1):
        page_html = _post_page(session, date_str, page)
        if debug_dir and page == 1:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"kind_{date_str}_p1.html").write_text(page_html, encoding="utf-8")
        rows = parse_list_page(page_html, date_str)
        fresh = [r for r in rows if r["접수번호"] not in seen]
        seen.update(r["접수번호"] for r in fresh)
        collected.extend(fresh)
        if len(rows) < PAGE_SIZE or not fresh:
            if page == 1 and not rows and should_have_rows(date_str):
                # 평일 장중인데 공시가 한 건도 읽히지 않는다 → 화면 구조가 바뀌었을 가능성
                raise KindBlocked("KIND 화면에서 공시 행을 찾지 못했습니다 (평일 장중 0건 — 화면 구조 변경 가능성)",
                                  200, page_html[:20000])
            return collected, page
        time.sleep(PAGE_DELAY_SECONDS)
    return collected, max_pages


def cmd_fetch(args) -> int:
    now = rules.now_kst()
    # (날짜, 읽을 최대 페이지 수)
    if args.date:
        plan = [(args.date, MAX_PAGES)]
    else:
        plan = [(now.date().isoformat(), MAX_PAGES)]
        if now.hour < 12:
            # 전날 마지막 확인 뒤(예: 23:55 확인 후 23:57)에 올라온 공시를 놓치지 않도록
            # 정오 전 실행에서는 전날 목록도 확인한다. 최신순이라 늦은 공시는 첫 페이지에 있다.
            plan.insert(0, ((now.date() - timedelta(days=1)).isoformat(), 1))
    dates = [d for d, _ in plan]
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    result = {"ok": False, "checked_at": now.isoformat(), "dates": dates,
              "rows": [], "pages": {}, "error": "", "http_status": None}
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        try:
            session.get(MAIN_URL, timeout=(10, 30))  # 일반 화면 접속과 같은 쿠키 확보
        except requests.RequestException:
            pass
        for date_str, max_pages in plan:
            rows, pages = fetch_date(session, date_str, debug_dir, max_pages)
            result["rows"].extend(rows)
            result["pages"][date_str] = pages
            time.sleep(PAGE_DELAY_SECONDS)
        result["ok"] = True
    except KindBlocked as exc:
        result["error"] = str(exc)
        result["http_status"] = exc.status
        if debug_dir and exc.body:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "kind_error_response.html").write_text(exc.body, encoding="utf-8")
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"KIND 확인 {'성공' if result['ok'] else '실패'}: {len(result['rows'])}건 {result['error']}")
    return 0 if result["ok"] else 2


# ---------------------------------------------------------------------
# 누적 반영
# ---------------------------------------------------------------------
def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def target_codes(app_dir: Path) -> set:
    codes = set()
    for market in ("kospi", "kosdaq"):
        _, company = rules.load_reference_data(market, app_dir)
        codes |= rules.reference_stock_codes(company)
    return codes


def cmd_merge(args) -> int:
    fetched = _load_json(Path(args.fetched), {"ok": False, "error": "조회 결과 파일 없음", "rows": []})
    state_path, status_path = Path(args.state), Path(args.status)

    if state_path.exists():
        state = _load_json(state_path, None)
    elif args.seed and Path(args.seed).exists():
        state = _load_json(Path(args.seed), None)
        print(f"초기 누적자료로 시작: {args.seed}")
    else:
        state = rules.empty_state()
    for key, default in rules.empty_state().items():
        state.setdefault(key, default)
    before = json.dumps(state, ensure_ascii=False, sort_keys=True)

    previous = _load_json(status_path, {})
    status = {
        "last_run": fetched.get("checked_at") or rules.now_kst().isoformat(),
        "ok": bool(fetched.get("ok")),
        "dates": fetched.get("dates", []),
        "fetched_rows": len(fetched.get("rows", [])),
        "new_rows": 0,
        "message": fetched.get("error", ""),
        "http_status": fetched.get("http_status"),
        "last_success": previous.get("last_success"),
        "consecutive_failures": 0 if fetched.get("ok") else int(previous.get("consecutive_failures", 0)) + 1,
    }

    if fetched.get("ok"):
        new_rows = rules.merge_rows(state, fetched.get("rows", []))
        if new_rows:
            state["latest_batch"] = new_rows
            latest = max(r["공시시각"] for r in new_rows)
            candidates = [c for c in (state.get("cutoff"), latest) if c]
            state["cutoff"] = max(candidates, key=lambda v: rules.pd.to_datetime(v))
        pruned = rules.prune_rows(state, target_codes(Path(args.app_dir)), args.keep_days)
        status.update(new_rows=len(new_rows), last_success=status["last_run"],
                      message=f"신규 {len(new_rows)}건" + (f", 오래된 비대상 {pruned}건 정리" if pruned else ""))

    changed = json.dumps(state, ensure_ascii=False, sort_keys=True) != before or not state_path.exists()
    if changed:
        write_json(state_path, state)
    write_json(status_path, status)
    print(f"반영: {status['message'] or '변경 없음'} (누적 {len(state['rows'])}건, 파일 {'변경' if changed else '유지'})")
    return 0


def cmd_parse(args) -> int:
    rows = parse_list_page(Path(args.html).read_text(encoding=args.encoding), args.date)
    print(json.dumps(rows[: args.show], ensure_ascii=False, indent=1))
    print(f"총 {len(rows)}건")
    return 0 if rows else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--out", required=True)
    p.add_argument("--date")
    p.add_argument("--debug-dir")
    p.set_defaults(func=cmd_fetch)
    m = sub.add_parser("merge")
    m.add_argument("--fetched", required=True)
    m.add_argument("--state", required=True)
    m.add_argument("--status", required=True)
    m.add_argument("--seed")
    m.add_argument("--app-dir", default=str(rules.ROOT))
    m.add_argument("--keep-days", type=int, default=14)
    m.set_defaults(func=cmd_merge)
    t = sub.add_parser("parse")
    t.add_argument("--html", required=True)
    t.add_argument("--date", required=True)
    t.add_argument("--encoding", default="utf-8")
    t.add_argument("--show", type=int, default=3)
    t.set_defaults(func=cmd_parse)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
