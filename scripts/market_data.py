# -*- coding: utf-8 -*-
"""
market_data.py — 시세 수집 + 한국거래소 영업일(휴장일) 캘린더

구성
  1) fetch_ohlcv(code, start, end)  : 네이버 siseJson 일봉 수집
  2) fetch_krx_holidays(years)      : KRX 공식 휴장일 API 수집
  3) save_holidays / load_holidays  : data/holidays_kr.json 입출력
  4) is_business_day / next_business_day / prev_business_day
     business_days_between / add_business_days : 영업일 계산 헬퍼

주의
  - 네이버 응답은 "파이썬 리터럴 유사" 포맷이라 eval 을 절대 쓰지 않고
    ast.literal_eval(1차) → 정규식(2차 폴백) 으로만 파싱한다.
  - 휴장일 JSON 이 없으면 영업일 헬퍼는 '주말만 제외' 로 동작하며 경고를 남긴다.
"""

from __future__ import annotations

import ast
import json
import re
import time
import urllib.parse
import urllib.request
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

__all__ = [
    "fetch_ohlcv",
    "fetch_krx_holidays",
    "save_holidays",
    "load_holidays",
    "holiday_set",
    "short_session_set",
    "short_session_info",
    "covers_range",
    "coverage_ok",
    "HolidayCoverageError",
    "is_business_day",
    "next_business_day",
    "prev_business_day",
    "business_days_between",
    "add_business_days",
    "business_days_list",
]

# 영업일 계산 상한. 이 이상은 입력 실수로 본다(무한루프/조용한 폭주 방지).
MAX_BUSINESS_DAY_STEPS = 5000

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HOLIDAY_FILE = DATA_DIR / "holidays_kr.json"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------- 공통 유틸
def _to_date(d) -> date:
    """date / datetime / 'YYYY-MM-DD' / 'YYYYMMDD' 를 date 로 정규화."""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    s = str(d).strip()
    if re.fullmatch(r"\d{8}", s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(s)


def _ymd(d) -> str:
    return _to_date(d).strftime("%Y%m%d")


def _http(url: str, *, data: bytes | None = None, headers: dict | None = None,
          timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------ (A) 네이버 시세
_NAVER_SISE = "https://api.finance.naver.com/siseJson.naver"

# ["20260803", 248000, 249500, 238000, 239500, 27825493, 46.61]
_ROW_RE = re.compile(
    r'\[\s*["\'](\d{8})["\']\s*,\s*'
    r'(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)'
    r'(?:\s*,\s*(-?[\d.]+|None|null))?\s*\]'
)


def _num(x):
    f = float(x)
    return int(f) if f.is_integer() else f


def _parse_sise(text: str) -> list[dict]:
    """네이버 siseJson 본문 → [{date, open, high, low, close, volume, ...}]"""
    cleaned = text.strip().replace("null", "None")

    rows: list[list] | None = None
    try:  # 1차: ast.literal_eval (eval 아님 — 리터럴만 허용)
        parsed = ast.literal_eval(cleaned)
        if isinstance(parsed, (list, tuple)):
            rows = [list(r) for r in parsed if isinstance(r, (list, tuple))]
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        rows = None

    out: list[dict] = []
    if rows is not None:
        for r in rows:
            if not r or not isinstance(r[0], str):
                continue
            if not re.fullmatch(r"\d{8}", r[0].strip()):
                continue  # 헤더행('날짜','시가',...) 등
            d = r[0].strip()
            out.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "open": r[1], "high": r[2], "low": r[3], "close": r[4],
                "volume": r[5],
                "foreign_ratio": r[6] if len(r) > 6 else None,
            })
    else:  # 2차: 정규식 폴백
        for m in _ROW_RE.finditer(cleaned):
            d = m.group(1)
            fr = m.group(7)
            out.append({
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "open": _num(m.group(2)), "high": _num(m.group(3)),
                "low": _num(m.group(4)), "close": _num(m.group(5)),
                "volume": _num(m.group(6)),
                "foreign_ratio": (None if fr in (None, "None", "null") else float(fr)),
            })

    out.sort(key=lambda x: x["date"])
    return out


def fetch_ohlcv(code: str, start: str, end: str) -> list[dict]:
    """
    네이버 금융 일봉 OHLCV.

    code  : 6자리 종목코드 ('005930')
    start : 'YYYY-MM-DD' 또는 'YYYYMMDD'
    end   : 동일

    반환  : [{'date':'2026-08-03','open':248000,'high':249500,'low':238000,
              'close':239500,'volume':27825493,'foreign_ratio':46.61}, ...]
            날짜 오름차순. 휴장일은 애초에 응답에 없다.
    """
    code = str(code).strip().zfill(6)
    qs = urllib.parse.urlencode({
        "symbol": code,
        "requestType": 1,
        "startTime": _ymd(start),
        "endTime": _ymd(end),
        "timeframe": "day",
    })
    raw = _http(
        f"{_NAVER_SISE}?{qs}",
        headers={"User-Agent": _UA, "Referer": "https://finance.naver.com/"},
    )
    return _parse_sise(_decode(raw))


# ------------------------------------------------- (B) KRX 공식 휴장일 캘린더
_KRX_OTP = "http://open.krx.co.kr/contents/COM/GenerateOTP.jspx"
_KRX_DOWN = "http://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx"
_KRX_PAGE = "/contents/MKD/01/0110/01100305/MKD01100305.jsp"
_KRX_BLD = "MKD/01/0110/01100305/mkd01100305_01"
KRX_SOURCE = (
    "KRX open.krx.co.kr GenerateOTP.jspx + OPN99000001.jspx "
    "(bld=MKD/01/0110/01100305/mkd01100305_01, 유가증권시장 휴장일)"
)


def fetch_krx_holidays(years) -> list[dict]:
    """
    KRX 공식 '휴장일' 목록. 연도별 조회.
    반환: [{'date':'2026-09-24','weekday':'목요일','name':'추석','year':2026}, ...]
    """
    if isinstance(years, int):
        years = [years]
    hdr = {"User-Agent": _UA, "Referer": "http://open.krx.co.kr" + _KRX_PAGE}
    out: list[dict] = []
    for y in years:
        q = urllib.parse.urlencode({
            "bld": _KRX_BLD, "name": "form", "_": str(int(time.time() * 1000)),
        })
        otp = _decode(_http(f"{_KRX_OTP}?{q}", headers=hdr)).strip()
        body = urllib.parse.urlencode({
            "search_bas_yy": str(y), "gridTp": "KRX",
            "pagePath": _KRX_PAGE, "code": otp,
        }).encode()
        payload = json.loads(_decode(_http(_KRX_DOWN, data=body, headers=hdr)))
        for it in payload.get("block1", []):
            out.append({
                "date": it["calnd_dd"],
                "weekday": it.get("kr_dy_tp", ""),
                "name": it.get("holdy_nm", ""),
                "year": int(y),
            })
        time.sleep(0.4)  # KRX 예의상 간격
    out.sort(key=lambda x: x["date"])
    return out


def save_holidays(records: list[dict], *, source: str = KRX_SOURCE,
                  fetched: str | None = None, path: Path = HOLIDAY_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    dates = sorted({r["date"] for r in records})
    # 수동 관리 항목(매매시간 단축일)은 KRX 재수집으로 날아가면 안 된다 — 보존한다.
    prev_short = []
    if path.exists():
        try:
            prev_short = json.loads(path.read_text(encoding="utf-8")).get("short_sessions", [])
        except Exception:                                       # noqa: BLE001
            prev_short = []
    doc = {
        "source": source,
        "fetched": fetched or date.today().isoformat(),
        "covers": {"from": f"{min(r['year'] for r in records)}-01-01",
                   "to": f"{max(r['year'] for r in records)}-12-31"} if records else {},
        "note": ("KRX 공식 휴장일. 주말(토·일)은 포함되지 않음 — 영업일 계산 시 "
                 "주말은 별도로 제외한다. 근로자의날/임시공휴일/연말휴장일 포함."),
        "holidays": dates,
        "short_sessions": prev_short,
        "detail": records,
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


_HOLIDAY_CACHE: dict | None = None


def load_holidays(path: Path = HOLIDAY_FILE, *, reload: bool = False) -> dict:
    global _HOLIDAY_CACHE, _COVERS_CACHE
    if _HOLIDAY_CACHE is not None and not reload:
        return _HOLIDAY_CACHE
    _COVERS_CACHE = None
    if not path.exists():
        warnings.warn(f"휴장일 파일 없음: {path} — 주말만 제외하고 계산합니다.")
        _HOLIDAY_CACHE = {"source": None, "fetched": None, "holidays": [], "detail": []}
    else:
        _HOLIDAY_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _HOLIDAY_CACHE


def holiday_set(path: Path = HOLIDAY_FILE) -> set[date]:
    return {_to_date(s) for s in load_holidays(path).get("holidays", [])}


def short_session_set(path: Path = HOLIDAY_FILE) -> set[date]:
    """
    휴장은 아니지만 매매시간이 단축·순연되는 날(수능일 등).
    ★ 영업일 계산에는 절대 반영하지 않는다 — 표시용 각주 전용.
    """
    return {_to_date(r["date"]) for r in load_holidays(path).get("short_sessions", [])}


def short_session_info(d, path: Path = HOLIDAY_FILE) -> dict | None:
    """해당 날짜가 매매시간 단축일이면 그 레코드를, 아니면 None."""
    d = _to_date(d)
    for r in load_holidays(path).get("short_sessions", []):
        if _to_date(r["date"]) == d:
            return r
    return None


# ------------------------------------------------------- 휴장일 커버리지 가드
class HolidayCoverageError(RuntimeError):
    """휴장일 캘린더가 덮지 않는 날짜로 영업일 계산을 시도했다."""


# True 면 커버리지 밖 날짜에 예외를 던진다. False 면 warnings.warn 만.
STRICT_COVERAGE = True

_COVERS_CACHE: tuple[date | None, date | None] | None = None


def covers_range(path: Path = HOLIDAY_FILE) -> tuple[date | None, date | None]:
    """휴장일 캘린더가 실제로 덮는 구간 (from, to). 파일이 없으면 (None, None)."""
    global _COVERS_CACHE
    if _COVERS_CACHE is None:
        c = (load_holidays(path).get("covers") or {})
        _COVERS_CACHE = (
            _to_date(c["from"]) if c.get("from") else None,
            _to_date(c["to"]) if c.get("to") else None,
        )
    return _COVERS_CACHE


def coverage_ok(d, path: Path = HOLIDAY_FILE) -> bool:
    """d 가 휴장일 캘린더 커버리지 안이면 True (예외를 던지지 않는 판정용)."""
    lo, hi = covers_range(path)
    if lo is None or hi is None:
        return False
    return lo <= _to_date(d) <= hi


def _assert_covered(d, where: str) -> None:
    """
    ★ 커버리지 밖 날짜는 '주말만 제외' 로 조용히 계산돼 공휴일이 통째로 빠진다.
      → ETA 가 낙관 편향된다. 조용히 넘기지 않고 예외(또는 경고)를 낸다.
    """
    lo, hi = covers_range()
    if lo is None or hi is None:
        return                      # load_holidays 가 이미 '파일 없음' 경고를 냈다
    dd = _to_date(d)
    if lo <= dd <= hi:
        return
    msg = (f"{where}: {dd} 는 휴장일 캘린더 커버리지 [{lo} ~ {hi}] 밖이다. "
           f"공휴일 미반영(주말만 제외) 계산이 되어 결과가 낙관 편향된다. "
           f"`python scripts/market_data.py holidays <연도...>` 로 캘린더를 확장하라.")
    if STRICT_COVERAGE:
        raise HolidayCoverageError(msg)
    warnings.warn(msg)


# ------------------------------------------------------------ 영업일 헬퍼
def is_business_day(d, holidays: set[date] | None = None) -> bool:
    """한국 증시 영업일(거래일)이면 True. 토·일 및 KRX 휴장일 제외."""
    d = _to_date(d)
    _assert_covered(d, "is_business_day")
    if d.weekday() >= 5:          # 5=토, 6=일
        return False
    hs = holiday_set() if holidays is None else holidays
    return d not in hs


def next_business_day(d, holidays: set[date] | None = None, *,
                      inclusive: bool = False) -> date:
    """
    d 다음 영업일. inclusive=True 면 d 자신이 영업일일 때 d 를 그대로 반환.
    """
    hs = holiday_set() if holidays is None else holidays
    cur = _to_date(d)
    if not inclusive:
        cur += timedelta(days=1)
    for _ in range(400):
        if is_business_day(cur, hs):
            return cur
        cur += timedelta(days=1)
    raise RuntimeError("영업일을 400일 안에 찾지 못함 — 휴장일 데이터 확인 필요")


def prev_business_day(d, holidays: set[date] | None = None, *,
                      inclusive: bool = False) -> date:
    """d 직전 영업일. (KIND '신청일 = 매매일의 직전 영업일' 규칙에 사용)"""
    hs = holiday_set() if holidays is None else holidays
    cur = _to_date(d)
    if not inclusive:
        cur -= timedelta(days=1)
    for _ in range(400):
        if is_business_day(cur, hs):
            return cur
        cur -= timedelta(days=1)
    raise RuntimeError("영업일을 400일 안에 찾지 못함 — 휴장일 데이터 확인 필요")


def business_days_list(a, b, holidays: set[date] | None = None) -> list[date]:
    """닫힌 구간 [a, b] 안의 영업일 전체를 오름차순 리스트로."""
    hs = holiday_set() if holidays is None else holidays
    a, b = _to_date(a), _to_date(b)
    _assert_covered(a, "business_days_list(a)")
    _assert_covered(b, "business_days_list(b)")
    if a > b:
        return []
    out, cur = [], a
    while cur <= b:
        if is_business_day(cur, hs):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def business_days_between(a, b, holidays: set[date] | None = None, *,
                          inclusive: bool = True) -> int:
    """
    a 와 b 사이 영업일 수.
      inclusive=True  (기본) : 닫힌 구간 [a, b] — 양 끝 포함.  ex) 오늘~마감일 남은 거래일
      inclusive=False         : 반열린 구간 (a, b] — a 다음날부터 b 까지.
    b < a 이면 음수를 반환한다(방향 보존).

    ★ inclusive=False 에서 '제외되는 끝점'은 언제나 **원래의 a** 다.
      (swap 후의 a 를 기준으로 빼면 역방향에서 크기가 비대칭이 된다 — 과거 버그)
    """
    a0, b0 = _to_date(a), _to_date(b)
    hs = holiday_set() if holidays is None else holidays
    lo, hi, sign = (a0, b0, 1) if a0 <= b0 else (b0, a0, -1)
    n = len(business_days_list(lo, hi, hs))
    if not inclusive and n and is_business_day(a0, hs):
        n -= 1
    return sign * n


def add_business_days(d, n: int, holidays: set[date] | None = None) -> date:
    """d 로부터 영업일 n 만큼 이동한 날짜(n>0 앞으로, n<0 뒤로). n=0 이면 d 자신."""
    hs = holiday_set() if holidays is None else holidays
    cur = _to_date(d)
    _assert_covered(cur, "add_business_days(start)")
    if abs(int(n)) > MAX_BUSINESS_DAY_STEPS:
        raise ValueError(
            f"add_business_days: n={n} 이 상한 {MAX_BUSINESS_DAY_STEPS} 거래일을 넘는다 "
            f"— 페이스/잔여수량 계산이 폭주했을 가능성이 크다.")
    step = 1 if n >= 0 else -1
    left = abs(int(n))
    while left:
        cur += timedelta(days=step)
        if is_business_day(cur, hs):   # ← 커버리지 밖으로 나가면 여기서 예외
            left -= 1
    return cur


# ------------------------------------------------------------------- CLI
def _refresh_holidays(years=(2025, 2026, 2027)):
    recs = fetch_krx_holidays(list(years))
    p = save_holidays(recs)
    print(f"saved {len(recs)} holidays -> {p}")
    return recs


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "holidays":
        yrs = [int(x) for x in sys.argv[2:]] or [2025, 2026, 2027]
        _refresh_holidays(yrs)
    else:
        for c, nm in (("005930", "삼성전자"), ("000660", "SK하이닉스")):
            rows = fetch_ohlcv(c, "2026-08-01", "2026-09-01")
            print(f"\n== {nm} ({c})  {len(rows)}일")
            for r in rows:
                print(f"  {r['date']}  O{r['open']:>8,} H{r['high']:>8,} "
                      f"L{r['low']:>8,} C{r['close']:>8,}  V{r['volume']:>12,}")
