"""영문공시 대상 판정 공통 규칙.

Streamlit 앱(kospi_engdiscl.py)과 30분 자동 수집기(kind_collector.py)가
같은 기준으로 판정·중복제거하도록 화면과 무관한 함수만 모아 둔다.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent


def now_kst() -> datetime:
    return datetime.now(KST).replace(microsecond=0)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(value)).strip()


def fmt_dt(value: Optional[str]) -> str:
    if not value:
        return "-"
    try:
        dt = pd.to_datetime(value)
        dt = dt.tz_localize(KST) if getattr(dt, "tzinfo", None) is None else dt.tz_convert(KST)
        return dt.strftime("%Y.%m.%d %H:%M")
    except Exception:
        return str(value)


def iso_dt(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    try:
        dt = pd.to_datetime(text)
        if pd.isna(dt):
            return None
        dt = dt.tz_localize(KST) if getattr(dt, "tzinfo", None) is None else dt.tz_convert(KST)
        return dt.isoformat()
    except Exception:
        return None


def kst_date(value: Any):
    return pd.to_datetime(value).tz_convert(KST).date()


def normalize_code(value: Any) -> str:
    text = clean_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text


# 기준자료의 외국법인 회사코드는 종목코드와 별도 체계이다.
# KIND 원문에서 종목코드를 확인한 대응만 사용한다.
FOREIGN_STOCK_CODES = {
    "USA11": "950140",  # 잉글우드랩
    "USA12": "950160",  # 코오롱티슈진
    "HKG21": "900290",  # GRT
}


def normalize_stock_code(value: Any) -> str:
    code = clean_text(value).upper()
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if len(code) == 7 and code.startswith("A"):
        code = code[1:]
    if code.isdigit() and len(code) <= 6:
        code = code.zfill(6)
    return code if re.fullmatch(r"[0-9]{6}|[0-9]{4}[A-Z][0-9]", code) else ""


def company_code_to_stock_code(value: Any) -> str:
    code = clean_text(value).upper()
    if code.endswith(".0") and code[:-2].isdigit():
        code = code[:-2]
    if code in FOREIGN_STOCK_CODES:
        return FOREIGN_STOCK_CODES[code]
    # 기존 로더가 회사코드를 여섯 자리로 패딩한 경우도 지원한다.
    if code.isdigit() and len(code) <= 6 and len(str(int(code))) <= 5:
        return str(int(code)).zfill(5) + "0"
    if re.fullmatch(r"[0-9]{4}[A-Z]", code):
        return code + "0"
    return ""


def row_stock_code(row: Dict[str, Any]) -> str:
    raw = clean_text(row.get("종목코드"))
    return normalize_stock_code(raw) if raw else company_code_to_stock_code(row.get("회사코드"))


def reference_stock_codes(company: pd.DataFrame) -> set:
    targets = set()
    for row in company.to_dict("records"):
        explicit = clean_text(row.get("종목코드"))
        code = normalize_stock_code(explicit) if explicit else company_code_to_stock_code(row.get("회사코드"))
        if not code:
            raise ValueError("대상법인 기준자료에서 종목코드 대응을 확인할 수 없습니다: "
                             f"{clean_text(row.get('회사명'))}. 해당 행에 종목코드 열을 추가해주세요.")
        targets.add(code)
    return targets


def normalize_company_name(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\(주\)|㈜|주식회사", "", text)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def empty_state() -> Dict[str, Any]:
    return {
        "cutoff": None,
        "rows": [],
        "latest_batch": [],
        "link_cache": {},
        "last_upload": None,
        "upload_history": [],
    }


# ---------------------------------------------------------------------
# 기준자료
# ---------------------------------------------------------------------
def read_csv_flexible(source) -> pd.DataFrame:
    """KIND/사내 엑셀 저장 CSV에서 흔한 인코딩을 순서대로 시도한다."""
    for encoding in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            if hasattr(source, "seek"):
                source.seek(0)
            return pd.read_csv(source, dtype=str, encoding=encoding).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def reference_path(filename: str, root: Path = ROOT) -> Path:
    """루트에 CSV가 있는 경우와 config 폴더를 모두 지원한다. 둘 다 있으면 루트 우선."""
    root_path = root / filename
    return root_path if root_path.exists() else root / "config" / filename


def read_reference_csv(path: Path) -> pd.DataFrame:
    return read_csv_flexible(path) if path.exists() else pd.DataFrame()


def load_reference_data(market: str, root: Path = ROOT):
    company = read_reference_csv(reference_path(f"{market}_company.csv", root))
    fmt = read_reference_csv(reference_path(f"{market}_format.csv", root))
    if company.empty or "회사코드" not in company or "회사명" not in company:
        raise ValueError(f"{market}_company.csv의 회사코드·회사명 열을 확인해주세요.")
    if fmt.empty or "서식명" not in fmt:
        raise ValueError(f"{market}_format.csv의 서식명 열을 확인해주세요.")
    company["회사코드"] = company["회사코드"].map(normalize_code)
    reference_stock_codes(company)  # 알 수 없는 코드가 있으면 명시적으로 알린다.
    return fmt, company


# ---------------------------------------------------------------------
# 행 식별·병합
# ---------------------------------------------------------------------
def row_key(row: Dict[str, Any]) -> str:
    if row.get("접수번호"):
        return f"acpt:{row['접수번호']}"
    return "|".join(
        str(row.get(k, ""))
        for k in ("공시시각", "회사코드", "종목코드", "회사명", "공시제목", "제출인")
    )


def content_key(row: Dict[str, Any]) -> str:
    """접수번호 유무·코드 표기와 무관하게 같은 공시를 알아보는 보조 키.

    KIND 화면 수집 행(접수번호 있음)과 엑셀 업로드 행(접수번호 없음)이
    같은 공시를 두 번 누적하지 않도록 쓴다.
    """
    return "|".join((
        clean_text(row.get("공시시각")),
        normalize_company_name(row.get("회사명")),
        re.sub(r"\s+", "", clean_text(row.get("공시제목"))),
    ))


def merge_rows(state: Dict[str, Any], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """기존에 없는 행만 state['rows']에 추가하고 추가된 행을 돌려준다.

    이미 있는 행(보조 키 일치)에 접수번호·상세URL이 비어 있으면 채운다.
    채울 때 행 식별키가 바뀌므로 기존 링크 캐시도 새 키로 옮긴다.
    """
    rows = state.setdefault("rows", [])
    by_key = {row_key(r): r for r in rows}
    by_content = {content_key(r): r for r in rows}
    cache = state.setdefault("link_cache", {})
    new_rows = []
    for row in incoming:
        existing = by_key.get(row_key(row)) or by_content.get(content_key(row))
        if existing is not None:
            if row.get("접수번호") and not existing.get("접수번호"):
                old_key = row_key(existing)
                existing["접수번호"] = row["접수번호"]
                if not existing.get("상세URL") and row.get("상세URL"):
                    existing["상세URL"] = row["상세URL"]
                    existing["링크상태"] = row.get("링크상태", "KIND 접수번호 링크")
                if old_key in cache:
                    cache[row_key(existing)] = cache.pop(old_key)
                by_key[row_key(existing)] = existing
            continue
        rows.append(row)
        by_key[row_key(row)] = row
        by_content[content_key(row)] = row
        new_rows.append(row)
    return new_rows


def prune_rows(state: Dict[str, Any], keep_codes: set, keep_days: int = 14,
               today=None) -> int:
    """오래된 비대상 법인 행을 정리해 누적 파일 크기를 관리한다.

    최근 keep_days일의 행은 모두 남긴다(대상서식 변경 시 다시 판정 가능).
    그보다 오래된 행은 대상법인(코스피·코스닥 기준자료) 공시만 남긴다.
    """
    today = today or now_kst().date()
    limit = today - timedelta(days=keep_days)
    before = len(state.get("rows", []))
    state["rows"] = [
        r for r in state.get("rows", [])
        if kst_date(r["공시시각"]) >= limit or row_stock_code(r) in keep_codes
    ]
    return before - len(state["rows"])


# ---------------------------------------------------------------------
# 필터링
# ---------------------------------------------------------------------
def filter_market(rows: Iterable[Dict[str, Any]], fmt: pd.DataFrame, company: pd.DataFrame):
    rows = list(rows)
    if not rows or fmt.empty or company.empty:
        return pd.DataFrame()

    form_col = "서식명" if "서식명" in fmt.columns else fmt.columns[0]
    target_forms = [clean_text(x) for x in fmt[form_col].tolist() if clean_text(x)]
    target_stock_codes = reference_stock_codes(company)

    matched = []
    for row in rows:
        title = clean_text(row.get("공시제목"))
        stock_code = row_stock_code(row)

        if title.startswith(("추가상장", "변경상장")):
            continue
        if "종속회사의 주요경영사항" in title:
            continue

        form_match = any(form in title for form in target_forms)
        # 법인명·제출인명은 판별에 사용하지 않는다.
        company_match = bool(stock_code) and stock_code in target_stock_codes
        if form_match and company_match:
            row = dict(row)
            row["종목코드"] = stock_code
            row["공시시각표시"] = fmt_dt(row.get("공시시각"))
            matched.append(row)

    result = pd.DataFrame(matched)
    return result.sort_values("공시시각") if not result.empty else result
