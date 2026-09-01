# -*- coding: utf-8 -*-
"""
dart_source.py — 자사주 대시보드용 DART OpenAPI 데이터 소스

담당 범위
  1) 자기주식 취득/처분/신탁 결정 공시 수집 (tsstkAqDecsn / tsstkDpDecsn /
     tsstkAqTrctrCnsDecsn / tsstkAqTrctrCcDecsn)
  2) 정정공시(기재정정) 탐지 — 진행 중 프로그램의 취득예정수량·기간이 바뀌었는지
  3) 발행주식총수 / 자기주식 보유수 (stockTotqySttus + 유상증자·소각 보정)
  4) 진행 중 프로그램 판별 + 거래일 기준 잔여일수 / 실질 마지막 매매 가능일

검증 근거는 _ref/DART_SPEC.md 참조. 모든 수치는 실제 API 응답에서 온 것.

CLI:
    python dart_source.py            # 스냅샷 생성 → data/dart_snapshot.json
    python dart_source.py --print    # 콘솔 요약만
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

import requests

# ---------------------------------------------------------------- 경로 / 상수

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "_dart_cache"

DART_BASE = "https://opendart.fss.or.kr/api"
_KEY_FILE = Path(r"C:\Users\pjy09\_stock_tools\_dart\config.json")
# 프로젝트 루트 .env (KEY=VALUE 한 줄씩). git 에 올리지 않는다.
_ENV_FILE = ROOT / ".env"
# ★ 시크릿을 소스에 박지 않는다. 키는 config.json → .env → 환경변수 순으로만 읽는다.
_KEY_FALLBACK = ""

# 회사 마스터
CORPS: dict[str, dict[str, str]] = {
    "005930": {"name": "삼성전자", "corp_code": "00126380", "isur_cd": "00593"},
    "000660": {"name": "SK하이닉스", "corp_code": "00164779", "isur_cd": "00066"},
}
CORP_BY_CODE = {v["corp_code"]: dict(v, ticker=k) for k, v in CORPS.items()}

# 자기주식 관련 주요사항보고서 엔드포인트
EP_ACQ = "tsstkAqDecsn"           # 자기주식 취득 결정
EP_DISP = "tsstkDpDecsn"          # 자기주식 처분 결정
EP_TRUST_SIGN = "tsstkAqTrctrCnsDecsn"   # 자기주식취득 신탁계약 체결 결정
EP_TRUST_CANCEL = "tsstkAqTrctrCcDecsn"  # 자기주식취득 신탁계약 해지 결정

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class DartError(RuntimeError):
    pass


def _load_key() -> str:
    """
    DART OpenAPI 인증키를 외부에서만 읽는다.
      1) C:\\Users\\pjy09\\_stock_tools\\_dart\\config.json  (crtfc_key 등)
      2) 프로젝트 루트 .env 의 DART_API_KEY
      3) 환경변수 DART_API_KEY
    셋 다 없으면 빈 문자열을 돌려주고, 실제 호출 시점(_get)에 명확한 예외를 던진다.
    """
    try:
        cfg = json.loads(_KEY_FILE.read_text(encoding="utf-8"))
        for k in ("crtfc_key", "api_key", "key", "dart_key"):
            if cfg.get(k):
                return str(cfg[k]).strip()
    except Exception:
        pass
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DART_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return (os.environ.get("DART_API_KEY") or _KEY_FALLBACK).strip()


def require_key() -> str:
    if not DART_KEY:
        raise DartError(
            "DART OpenAPI 인증키 없음. 다음 중 하나를 설정하라:\n"
            f"  1) {_KEY_FILE} 에 {{\"crtfc_key\": \"...\"}}\n"
            f"  2) {_ENV_FILE} 에 DART_API_KEY=...\n"
            "  3) 환경변수 DART_API_KEY=...\n"
            "(키를 소스에 하드코딩하지 않는다.)")
    return DART_KEY


DART_KEY = _load_key()


# ---------------------------------------------------------------- 저수준 유틸

def parse_num(v: Any) -> int | None:
    """'53,285,968' -> 53285968 ; '-' / '' / None -> None"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "0-"):
        return None
    m = re.match(r"^-?\d+$", s)
    return int(s) if m else None


def parse_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_kdate(v: Any) -> _dt.date | None:
    """'2026년 08월 24일' / '2026-08-24' / '20260824' -> date"""
    if not v:
        return None
    s = str(v).strip()
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", s)
    if m:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return _dt.date(*map(int, m.groups()))
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return _dt.date(*map(int, m.groups()))
    return None


def _iso(d: _dt.date | None) -> str | None:
    return d.isoformat() if d else None


def _get(endpoint: str, **params) -> dict:
    """DART OpenAPI GET. status 000 이면 dict, 013(무자료)이면 list=[] 로 정규화."""
    params = {"crtfc_key": require_key(), **params}
    url = f"{DART_BASE}/{endpoint}.json"
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=25, headers={"User-Agent": _UA})
            r.raise_for_status()
            j = r.json()
        except Exception as e:  # 네트워크/파싱 실패는 재시도
            last = e
            time.sleep(0.8 * (attempt + 1))
            continue
        st = j.get("status")
        if st == "000":
            return j
        if st == "013":                       # 조회된 데이타가 없습니다
            return {"status": "013", "message": j.get("message"), "list": []}
        raise DartError(f"{endpoint} status={st} msg={j.get('message')} params={params}")
    raise DartError(f"{endpoint} 요청 실패: {last}")


# ---------------------------------------------------------------- 원문(document)

_TAG_RE = re.compile(r"<[^>]+>")


def fetch_document_text(rcept_no: str, use_cache: bool = True) -> str:
    """공시 원문(zip 안의 XML)을 평문 텍스트로. 표 셀은 '|' 로 구분됨."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"doc_{rcept_no}.txt"
    if use_cache and cache.exists():
        return cache.read_text(encoding="utf-8")
    r = requests.get(f"{DART_BASE}/document.xml",
                     params={"crtfc_key": require_key(), "rcept_no": rcept_no},
                     timeout=40, headers={"User-Agent": _UA})
    r.raise_for_status()
    if r.content[:2] != b"PK":
        raise DartError(f"document.xml 응답이 zip 아님 rcept_no={rcept_no}: {r.text[:200]}")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read(z.namelist()[0])
    txt = None
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if txt is None:
        txt = raw.decode("utf-8", errors="replace")
    txt = _TAG_RE.sub("|", txt)
    txt = _html.unescape(txt)
    txt = re.sub(r"\|+", "|", txt)
    txt = re.sub(r"[ \t]+", " ", txt)
    parts = [p.strip() for p in txt.split("|") if p.strip()]
    out = "\n".join(parts)
    cache.write_text(out, encoding="utf-8")
    return out


def total_shares_from_acq_doc(rcept_no: str) -> int | None:
    """
    취득결정 원문 '11. 기타 투자판단에 참고할 사항' 의
        ③ 발행주식총수의 1% : 보통주 58,462,786주
    에서 결의일 시점 발행주식총수(보통주)를 역산. 1% 를 내림한 값이라 ±99 오차.
    stockTotqySttus 와 대조해 정확한 수를 확정하는 용도.
    """
    txt = fetch_document_text(rcept_no)
    flat = txt.replace("\n", " ")
    m = re.search(r"발행주식총수의\s*1%\s*[:：]?\s*보통주\s*([\d,]+)\s*주", flat)
    if not m:
        m = re.search(r"발행주식총수의\s*1%\s*[:：]?\s*([\d,]+)\s*주", flat)
    if not m:
        return None
    one_pct = parse_num(m.group(1))
    return one_pct * 100 if one_pct else None


def total_shares_from_cancel_doc(rcept_no: str) -> int | None:
    """
    거래소 '주식 소각 결정' 공시의 '2. 발행주식 총수 / 보통주식(주)' 값.
    회사가 직접 적은 **소각 전** 발행주식총수라서 정확한 앵커로 쓸 수 있다.
    (예: SK하이닉스 20260819800340 → 730,492,365)
    """
    txt = fetch_document_text(rcept_no)
    flat = re.sub(r"\s+", " ", txt.replace("\n", " "))
    m = re.search(r"2\.\s*발행주식\s*총수\s*보통주식\s*\(주\)\s*([\d,]+)", flat)
    return parse_num(m.group(1)) if m else None


# ---------------------------------------------------------------- 결정 공시 수집

def _norm_acq(it: dict) -> dict:
    bgd = parse_kdate(it.get("aqexpd_bgd"))
    edd = parse_kdate(it.get("aqexpd_edd"))
    return {
        "kind": "취득결정",
        "rcept_no": it.get("rcept_no"),
        "corp_code": it.get("corp_code"),
        "corp_name": it.get("corp_name"),
        "board_date": _iso(parse_kdate(it.get("aq_dd"))),          # 이사회 결의일
        "plan_qty_ostk": parse_num(it.get("aqpln_stk_ostk")),      # 취득예정 보통주(주)
        "plan_qty_estk": parse_num(it.get("aqpln_stk_estk")),      # 취득예정 기타주식(우선주)
        "plan_amt_ostk": parse_num(it.get("aqpln_prc_ostk")),      # 취득예정 금액(원)
        "plan_amt_estk": parse_num(it.get("aqpln_prc_estk")),
        "period_start": _iso(bgd),
        "period_end": _iso(edd),
        "hold_start": _iso(parse_kdate(it.get("hdexpd_bgd"))),
        "hold_end": _iso(parse_kdate(it.get("hdexpd_edd"))),
        "purpose": (it.get("aq_pp") or "").strip(),
        "method": (it.get("aq_mth") or "").strip(),
        "brokers": (it.get("cs_iv_bk") or "").strip(),
        # 취득 '전' 자기주식 보유현황
        "pre_hold_div_ostk": parse_num(it.get("aq_wtn_div_ostk")),      # 배당가능이익 범위 내 취득분(보통주)
        "pre_hold_div_ostk_rt": parse_float(it.get("aq_wtn_div_ostk_rt")),
        "pre_hold_div_estk": parse_num(it.get("aq_wtn_div_estk")),
        "pre_hold_div_estk_rt": parse_float(it.get("aq_wtn_div_estk_rt")),
        "pre_hold_etc_ostk": parse_num(it.get("eaq_ostk")),             # 기타취득분(보통주)
        "pre_hold_etc_ostk_rt": parse_float(it.get("eaq_ostk_rt")),
        "pre_hold_etc_estk": parse_num(it.get("eaq_estk")),
        "pre_hold_etc_estk_rt": parse_float(it.get("eaq_estk_rt")),
        "daily_limit_ostk": parse_num(it.get("d1_prodlm_ostk")),        # 1일 매수주문 수량한도
        "daily_limit_estk": parse_num(it.get("d1_prodlm_estk")),
        "outside_dir_attend": it.get("od_a_at_t"),
        "outside_dir_absent": it.get("od_a_at_b"),
        "_raw": it,
    }


def _norm_disp(it: dict) -> dict:
    return {
        "kind": "처분결정",
        "rcept_no": it.get("rcept_no"),
        "corp_code": it.get("corp_code"),
        "corp_name": it.get("corp_name"),
        "board_date": _iso(parse_kdate(it.get("dp_dd"))),
        "plan_qty_ostk": parse_num(it.get("dppln_stk_ostk")),
        "plan_qty_estk": parse_num(it.get("dppln_stk_estk")),
        "unit_price_ostk": parse_num(it.get("dpstk_prc_ostk")),
        "plan_amt_ostk": parse_num(it.get("dppln_prc_ostk")),
        "period_start": _iso(parse_kdate(it.get("dpprpd_bgd"))),
        "period_end": _iso(parse_kdate(it.get("dpprpd_edd"))),
        "purpose": (it.get("dp_pp") or "").strip(),
        "method_mkt": parse_num(it.get("dp_m_mkt")),
        "method_ovtm": parse_num(it.get("dp_m_ovtm")),
        "method_otc": parse_num(it.get("dp_m_otc")),
        "method_etc": parse_num(it.get("dp_m_etc")),
        "pre_hold_div_ostk": parse_num(it.get("aq_wtn_div_ostk")),
        "pre_hold_etc_ostk": parse_num(it.get("eaq_ostk")),
        "daily_limit_ostk": parse_num(it.get("d1_slodlm_ostk")),
        "_raw": it,
    }


def _fetch_decisions(endpoint: str, corp_code: str, bgn: str, end: str) -> list[dict]:
    j = _get(endpoint, corp_code=corp_code, bgn_de=bgn, end_de=end)
    return j.get("list", []) or []


def fetch_acq_decisions(corp_code: str, bgn: str = "20240101",
                        end: str | None = None) -> list[dict]:
    """자기주식 취득 결정. 정정공시가 있으면 API 는 '최신 정정본' 하나만 돌려준다."""
    end = end or _dt.date.today().strftime("%Y%m%d")
    rows = [_norm_acq(x) for x in _fetch_decisions(EP_ACQ, corp_code, bgn, end)]
    rows.sort(key=lambda r: (r["board_date"] or "", r["rcept_no"] or ""))
    return rows


def fetch_disp_decisions(corp_code: str, bgn: str = "20240101",
                         end: str | None = None) -> list[dict]:
    end = end or _dt.date.today().strftime("%Y%m%d")
    rows = [_norm_disp(x) for x in _fetch_decisions(EP_DISP, corp_code, bgn, end)]
    rows.sort(key=lambda r: (r["board_date"] or "", r["rcept_no"] or ""))
    return rows


def fetch_trust_contracts(corp_code: str, bgn: str = "20240101",
                          end: str | None = None) -> list[dict]:
    """자기주식취득 신탁계약 체결 결정. 삼성/하이닉스는 해당 기간 0건(status 013)."""
    end = end or _dt.date.today().strftime("%Y%m%d")
    return _fetch_decisions(EP_TRUST_SIGN, corp_code, bgn, end)


def fetch_trust_cancels(corp_code: str, bgn: str = "20240101",
                        end: str | None = None) -> list[dict]:
    """자기주식취득 신탁계약 해지 결정."""
    end = end or _dt.date.today().strftime("%Y%m%d")
    return _fetch_decisions(EP_TRUST_CANCEL, corp_code, bgn, end)


# ---------------------------------------------------------------- 공시목록 / 정정탐지

def fetch_disclosure_list(corp_code: str, bgn: str, end: str,
                          max_pages: int = 40) -> list[dict]:
    """list.json 전체 페이지 수집."""
    rows, page = [], 1
    while page <= max_pages:
        j = _get("list", corp_code=corp_code, bgn_de=bgn, end_de=end,
                 page_no=page, page_count=100)
        rows += j.get("list", []) or []
        if j.get("status") == "013":
            break
        if page >= int(j.get("total_page", 1) or 1):
            break
        page += 1
        time.sleep(0.2)
    return rows


TREASURY_KEYWORDS = ("자기주식", "자사주", "주식소각", "주식 소각")


def filter_treasury(rows: Iterable[dict]) -> list[dict]:
    out = [r for r in rows if any(k in r.get("report_nm", "") for k in TREASURY_KEYWORDS)]
    out.sort(key=lambda r: (r.get("rcept_dt", ""), r.get("rcept_no", "")))
    return out


def filter_amendments(rows: Iterable[dict], self_only_corp: str | None = None) -> list[dict]:
    """report_nm 에 '정정'이 들어간 공시. self_only_corp 주면 그 회사 명의만."""
    out = []
    for r in rows:
        if "정정" not in r.get("report_nm", ""):
            continue
        if self_only_corp and r.get("flr_nm", "").strip() != self_only_corp:
            continue
        out.append(r)
    out.sort(key=lambda r: (r.get("rcept_dt", ""), r.get("rcept_no", "")))
    return out


def check_program_amended(corp_code: str, program: dict,
                          end: str | None = None) -> dict:
    """
    진행 중(또는 특정) 취득 프로그램에 대한 정정공시 여부 판정.

    판정 로직
      - 이사회 결의일 ~ 오늘 사이 공시목록에서
        report_nm 에 '정정' + '자기주식취득결정' 이 함께 든 건을 찾는다.
      - API(tsstkAqDecsn)가 돌려준 rcept_no 가 원 공시번호보다 큰(=나중) 접수번호이거나
        '[기재정정]' 건과 일치하면 정정본이 이미 반영된 것.
    반환: {"amended": bool, "amend_filings": [...], "treasury_filings": [...],
           "api_rcept_no": ..., "note": ...}
    """
    end = end or _dt.date.today().strftime("%Y%m%d")
    bgn = (program.get("board_date") or "2024-01-01").replace("-", "")
    rows = fetch_disclosure_list(corp_code, bgn, end)
    treasury = filter_treasury(rows)
    amends = [r for r in rows
              if "정정" in r.get("report_nm", "")
              and "자기주식취득결정" in r.get("report_nm", "").replace(" ", "")]
    api_rn = program.get("rcept_no")
    matched = [r for r in amends if r.get("rcept_no") == api_rn]
    return {
        "amended": bool(amends),
        "amend_is_current": bool(matched),
        "amend_filings": [{"rcept_dt": r["rcept_dt"], "rcept_no": r["rcept_no"],
                           "report_nm": r["report_nm"].strip()} for r in amends],
        "treasury_filings": [{"rcept_dt": r["rcept_dt"], "rcept_no": r["rcept_no"],
                              "report_nm": r["report_nm"].strip(),
                              "flr_nm": r["flr_nm"]} for r in treasury],
        "api_rcept_no": api_rn,
        "note": ("tsstkAqDecsn 은 정정이 있으면 '최신 정정본'만 반환한다. "
                 "amend_filings 가 비어 있으면 취득예정수량/기간은 최초 공시 그대로."),
    }


# ---------------------------------------------------------------- 발행주식총수

_REPRT = [("11011", "사업보고서"), ("11014", "3분기보고서"),
          ("11012", "반기보고서"), ("11013", "1분기보고서")]


def fetch_stock_total(corp_code: str, year: int, reprt_code: str) -> list[dict]:
    j = _get("stockTotqySttus", corp_code=corp_code, bsns_year=year, reprt_code=reprt_code)
    return j.get("list", []) or []


def _pick_row(rows: list[dict], se: str) -> dict | None:
    for r in rows:
        if (r.get("se") or "").strip() == se:
            return r
    return None


def fetch_shares_outstanding(corp_code: str, today: _dt.date | None = None) -> dict:
    """
    보통주 발행주식총수 / 자기주식수 / 유통주식수.

    stockTotqySttus 는 '정기보고서 기준일(stlm_dt)' 시점 값이다. 그 이후의
    유상증자(piicDecsn) · 이익소각으로 실제 발행주식총수가 달라질 수 있으므로
      (a) 기준일 이후 piicDecsn(유상증자결정) 신주수를 더하고
      (b) 최신 취득결정 원문의 '③ 발행주식총수의 1%' 로 교차검증
    한다. SK하이닉스가 실제로 이 케이스(2026-07 제3자배정 17,790,000주).
    """
    today = today or _dt.date.today()
    base = None
    for year in (today.year, today.year - 1):
        for rc, label in _REPRT:
            try:
                rows = fetch_stock_total(corp_code, year, rc)
            except DartError:
                continue
            ostk = _pick_row(rows, "보통주")
            if not ostk or parse_num(ostk.get("istc_totqy")) is None:
                continue
            stlm = parse_kdate(ostk.get("stlm_dt"))
            cand = {
                "source_rcept_no": ostk.get("rcept_no"),
                "report": f"{year} {label}",
                "reprt_code": rc,
                "stlm_dt": _iso(stlm),
                "common_total": parse_num(ostk.get("istc_totqy")),
                "common_treasury": parse_num(ostk.get("tesstk_co")) or 0,
                "common_float": parse_num(ostk.get("distb_stock_co")),
                "pref_total": None,
                "pref_treasury": None,
            }
            pref = _pick_row(rows, "우선주")
            if pref:
                cand["pref_total"] = parse_num(pref.get("istc_totqy"))
                cand["pref_treasury"] = parse_num(pref.get("tesstk_co")) or 0
            if base is None or (cand["stlm_dt"] or "") > (base["stlm_dt"] or ""):
                base = cand
            break   # 그 연도에서 가장 최근 보고서 하나만
        if base:
            break
    if base is None:
        raise DartError(f"stockTotqySttus 에서 보통주 행을 찾지 못함 corp_code={corp_code}")

    # (a) 기준일 이후 유상증자 반영
    #  ★ piicDecsn 의 bgn_de/end_de 는 '최초 공시 접수일' 기준으로 필터된다.
    #    (SK하이닉스: 원본 20260624000420 → 정정본 20260710000008 을 반환하지만
    #     bgn_de=20260625 로 조회하면 0건.) 따라서 반드시 넓은 창으로 조회한 뒤
    #    '증자 전 발행주식총수(bfic_tisstk_ostk)' 로 base 이후 건인지 판별한다.
    stlm = parse_kdate(base["stlm_dt"]) or _dt.date(2024, 1, 1)
    adj, notes = 0, []
    try:
        j = _get("piicDecsn", corp_code=corp_code,
                 bgn_de=(stlm - _dt.timedelta(days=400)).strftime("%Y%m%d"),
                 end_de=today.strftime("%Y%m%d"))
        cands = [x for x in (j.get("list", []) or []) if parse_num(x.get("nstk_ostk_cnt"))]
        running = base["common_total"]
        changed = True
        while changed:                       # 연속 증자도 체인으로 따라감
            changed = False
            for it in list(cands):
                n = parse_num(it.get("nstk_ostk_cnt"))
                before = parse_num(it.get("bfic_tisstk_ostk"))
                if before is not None and before == running:
                    running += n
                    adj += n
                    cands.remove(it)
                    notes.append(f"유상증자 {it.get('rcept_no')} {it.get('ic_mthn')} "
                                 f"신주 {n:,}주 (증자전 {before:,}주 → {running:,}주)")
                    changed = True
                    break
    except DartError:
        pass

    result = dict(base)
    result["adjust_new_shares"] = adj
    result["common_total_adjusted"] = base["common_total"] + adj
    result["adjust_notes"] = notes
    result["crosschecks"] = []

    end_s = today.strftime("%Y%m%d")

    # (b) 취득결정 원문 '③ 발행주식총수의 1%' 로 교차검증 (±99)
    try:
        acq = fetch_acq_decisions(corp_code, "20240101", end_s)
        if acq:
            latest = acq[-1]
            approx = total_shares_from_acq_doc(latest["rcept_no"])
            if approx:
                lo, hi = approx, approx + 99
                result["crosschecks"].append({
                    "source": "취득결정 원문 ③ 발행주식총수의 1%",
                    "rcept_no": latest["rcept_no"],
                    "value_range": [lo, hi],
                    "match": lo <= result["common_total_adjusted"] <= hi,
                })
    except Exception as e:  # noqa: BLE001
        result["crosschecks"].append({"source": "취득결정 원문 ③", "error": str(e)})

    # (c) 거래소 '주식 소각 결정' 원문 '2. 발행주식 총수' (정확값, 소각 전 기준)
    try:
        rows = fetch_disclosure_list(corp_code, stlm.strftime("%Y%m%d"), end_s)
        cancels = [r for r in rows if "소각" in r.get("report_nm", "")]
        cancels.sort(key=lambda r: r.get("rcept_dt", ""))
        if cancels:
            last = cancels[-1]
            exact = total_shares_from_cancel_doc(last["rcept_no"])
            if exact:
                result["crosschecks"].append({
                    "source": "주식소각결정 원문 '2. 발행주식 총수'(소각 전)",
                    "rcept_no": last["rcept_no"],
                    "rcept_dt": last["rcept_dt"],
                    "value": exact,
                    "match": exact == result["common_total_adjusted"],
                })
    except Exception as e:  # noqa: BLE001
        result["crosschecks"].append({"source": "주식소각결정 원문", "error": str(e)})

    bad = [c for c in result["crosschecks"] if c.get("match") is False]
    result["crosscheck_ok"] = not bad
    for c in bad:
        result["adjust_notes"].append(
            f"⚠ 교차검증 불일치({c['source']}): "
            f"{c.get('value') or c.get('value_range')} vs 산출 "
            f"{result['common_total_adjusted']:,}")
    return result


# ---------------------------------------------------------------- 거래일 캘린더

# 1순위 소스: data/holidays_kr.json (KRX 공식 유가증권시장 휴장일, 2025~2027).
#   market_data.py 의 fetch_krx_holidays() 가 만든다.
# 2순위(폴백): 아래 하드코딩 표 — 파일이 없거나 해당 연도를 안 덮을 때만 쓴다.
#   2024년은 KRX 파일 커버 범위 밖이라 네이버 일별시세 실측으로 채웠다.
# 주말은 별도 처리하므로 토·일이 목록에 있어도 무해.
_KRX_HOLIDAY_FILE = DATA_DIR / "holidays_kr.json"

KRX_HOLIDAYS_FALLBACK: dict[int, list[str]] = {
    2024: [   # 네이버 일별시세로 실측 확정
        "2024-01-01", "2024-02-09", "2024-02-12", "2024-03-01", "2024-04-10",
        "2024-05-01", "2024-05-06", "2024-05-15", "2024-06-06", "2024-08-15",
        "2024-09-16", "2024-09-17", "2024-09-18", "2024-10-01", "2024-10-03",
        "2024-10-09", "2024-12-25", "2024-12-31",
    ],
    2025: [
        "2025-01-01",
        "2025-01-27",                               # 임시공휴일(설 연휴 확대) ★공휴일 API 에 없음
        "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-03",
        "2025-05-01", "2025-05-05", "2025-05-06", "2025-06-03", "2025-06-06",
        "2025-08-15", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
        "2025-10-09", "2025-12-25", "2025-12-31",
    ],
    2026: [
        "2026-01-01",                               # 신정
        "2026-02-16", "2026-02-17", "2026-02-18",   # 설
        "2026-03-02",                               # 3·1절 대체(3/1 일)
        "2026-05-01",                               # 근로자의날(KRX 휴장)
        "2026-05-05",                               # 어린이날
        "2026-05-25",                               # 부처님오신날
        "2026-06-03",                               # 지방선거
        "2026-06-06",                               # 현충일(토)
        "2026-07-17",                               # 제헌절
        "2026-08-15", "2026-08-17",                 # 광복절(토) + 대체
        "2026-09-24", "2026-09-25", "2026-09-26",   # 추석 (9/26 토 → 대체 없음)
        "2026-10-03", "2026-10-05",                 # 개천절(토) + 대체
        "2026-10-09",                               # 한글날
        "2026-12-25",                               # 성탄절
        "2026-12-31",                               # 연말 휴장
    ],
}

_HOLIDAY_CACHE: dict[int, set[str]] = {}
HOLIDAY_SOURCE: dict[int, str] = {}


def _load_krx_holiday_file() -> dict[int, set[str]]:
    """data/holidays_kr.json (KRX 공식) 로딩. 없으면 {}."""
    out: dict[int, set[str]] = {}
    try:
        d = json.loads(_KRX_HOLIDAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return out
    hol = d.get("holidays") or []
    dates = [x if isinstance(x, str) else x.get("date") for x in hol]
    for s in dates:
        if not s:
            continue
        out.setdefault(int(s[:4]), set()).add(s)
    cov = d.get("covers") or {}
    lo = (cov.get("from") or "")[:4]
    hi = (cov.get("to") or "")[:4]
    if lo and hi:                       # 휴장일 0건인 연도도 '커버됨'으로 표시
        for y in range(int(lo), int(hi) + 1):
            out.setdefault(y, set())
    return out


def holiday_set(year: int) -> set[str]:
    """그 해 KRX 휴장일(YYYY-MM-DD). KRX 공식 파일 우선, 없으면 하드코딩 폴백."""
    if year in _HOLIDAY_CACHE:
        return _HOLIDAY_CACHE[year]
    krx = _load_krx_holiday_file()
    if year in krx:
        _HOLIDAY_CACHE[year] = krx[year]
        HOLIDAY_SOURCE[year] = f"KRX 공식 ({_KRX_HOLIDAY_FILE.name})"
    else:
        _HOLIDAY_CACHE[year] = set(KRX_HOLIDAYS_FALLBACK.get(year, []))
        HOLIDAY_SOURCE[year] = "폴백 하드코딩(KRX_HOLIDAYS_FALLBACK)"
    return _HOLIDAY_CACHE[year]


def fetch_public_holidays(year: int) -> list[str]:
    """
    Nager.Date 공개 API(키 불필요)로 한국 '공휴일' 조회 — 참고/교차검증용.
    KRX 휴장일과 다르다(근로자의날·연말휴장 없음, 대체공휴일 누락 있음). 단독 사용 금지.
    """
    r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/KR",
                     timeout=20, headers={"User-Agent": _UA})
    r.raise_for_status()
    return sorted({x["date"] for x in r.json()})


def is_trading_day(d: _dt.date) -> bool:
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in holiday_set(d.year)


def prev_trading_day(d: _dt.date, inclusive: bool = False) -> _dt.date:
    x = d if inclusive else d - _dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(x):
            return x
        x -= _dt.timedelta(days=1)
    raise ValueError(f"직전 거래일을 찾지 못함: {d}")


def next_trading_day(d: _dt.date, inclusive: bool = False) -> _dt.date:
    x = d if inclusive else d + _dt.timedelta(days=1)
    for _ in range(30):
        if is_trading_day(x):
            return x
        x += _dt.timedelta(days=1)
    raise ValueError(f"다음 거래일을 찾지 못함: {d}")


def trading_days(start: _dt.date, end: _dt.date) -> list[_dt.date]:
    """[start, end] 양끝 포함 거래일 목록."""
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def verify_calendar_against_naver(symbol: str = "005930",
                                  start: str = "20260101",
                                  end: str | None = None) -> dict:
    """네이버 일별시세에 실제로 존재하는 날짜 = 거래일. 캘린더 자체 검증용."""
    import ast
    end = end or _dt.date.today().strftime("%Y%m%d")
    r = requests.get("https://api.finance.naver.com/siseJson.naver",
                     params={"symbol": symbol, "requestType": 1, "startTime": start,
                             "endTime": end, "timeframe": "day"},
                     timeout=25, headers={"User-Agent": _UA})
    rows = ast.literal_eval(r.text.strip().replace("'", '"').replace("\n", ""))
    actual = {row[0] for row in rows[1:]}
    s, e = parse_kdate(start), parse_kdate(end)
    mine = {d.strftime("%Y%m%d") for d in trading_days(s, e)}
    return {
        "naver_trading_days": len(actual),
        "calendar_trading_days": len(mine),
        "in_calendar_not_in_naver": sorted(mine - actual),  # 오늘분 미집계 포함될 수 있음
        "in_naver_not_in_calendar": sorted(actual - mine),  # 있으면 캘린더 오류
    }


# ---------------------------------------------------------------- 진행중 판별

def is_program_active(program: dict, today: _dt.date | None = None) -> bool:
    """오늘이 취득예상기간(aqexpd_bgd ~ aqexpd_edd) 안이면 진행 중."""
    today = today or _dt.date.today()
    s = parse_kdate(program.get("period_start"))
    e = parse_kdate(program.get("period_end"))
    if not s or not e:
        return False
    return s <= today <= e


def program_status(program: dict, today: _dt.date | None = None) -> dict:
    """
    진행 상태 + 거래일 기준 일정.

    deadline_disclosed          : 공시상 취득기간 종료일 (그대로)
    deadline_is_trading_day     : 그 날이 KRX 거래일인지
    last_trading_day            : 실질 마지막 '매매 체결' 가능일
                                  (= 종료일 이전(포함) 최근 거래일)
    last_application_day        : 그 매매일에 체결하려면 자기주식 매매신청서를 내야 하는 날
                                  (= last_trading_day 의 직전 거래일)  ※ KIND 실측 규칙
    """
    today = today or _dt.date.today()
    s = parse_kdate(program.get("period_start"))
    e = parse_kdate(program.get("period_end"))
    if not s or not e:
        return {"error": "취득기간 파싱 실패", "program": program.get("rcept_no")}

    last_td = prev_trading_day(e, inclusive=True)
    all_td = trading_days(s, last_td)
    elapsed = [d for d in all_td if d <= today]
    remaining = [d for d in all_td if d > today]
    active = s <= today <= e
    wd = ["월", "화", "수", "목", "금", "토", "일"]

    return {
        "rcept_no": program.get("rcept_no"),
        "corp_name": program.get("corp_name"),
        "active": active,
        "today": today.isoformat(),
        "period_start": s.isoformat(),
        "deadline_disclosed": e.isoformat(),
        "deadline_weekday": wd[e.weekday()],
        "deadline_is_trading_day": is_trading_day(e),
        "deadline_note": (
            "공시 종료일이 거래일" if is_trading_day(e)
            else f"공시 종료일 {e.isoformat()}({wd[e.weekday()]})은 휴장일 → "
                 f"실질 마지막 매매일 {last_td.isoformat()}({wd[last_td.weekday()]})"
        ),
        "last_trading_day": last_td.isoformat(),
        "last_trading_day_weekday": wd[last_td.weekday()],
        "last_application_day": prev_trading_day(last_td).isoformat(),
        "trading_days_total": len(all_td),
        "trading_days_elapsed": len(elapsed),
        "trading_days_remaining": len(remaining),
        "calendar_days_remaining": (e - today).days,
        "holidays_in_window": sorted(
            d for y in range(s.year, e.year + 1) for d in holiday_set(y)
            if s.isoformat() <= d <= e.isoformat()
            and _dt.date.fromisoformat(d).weekday() < 5),
        "holiday_source": {y: HOLIDAY_SOURCE.get(y) for y in range(s.year, e.year + 1)},
    }


def active_program(corp_code: str, today: _dt.date | None = None,
                   bgn: str = "20240101") -> dict | None:
    today = today or _dt.date.today()
    for p in reversed(fetch_acq_decisions(corp_code, bgn, today.strftime("%Y%m%d"))):
        if is_program_active(p, today):
            return p
    return None


# ---------------------------------------------------------------- 스냅샷

def build_company(ticker: str, today: _dt.date | None = None,
                  bgn: str = "20240101") -> dict:
    today = today or _dt.date.today()
    meta = CORPS[ticker]
    cc = meta["corp_code"]
    end = today.strftime("%Y%m%d")

    acq = fetch_acq_decisions(cc, bgn, end)
    disp = fetch_disp_decisions(cc, bgn, end)
    trust_sign = fetch_trust_contracts(cc, bgn, end)
    trust_cancel = fetch_trust_cancels(cc, bgn, end)

    cur = next((p for p in reversed(acq) if is_program_active(p, today)), None)
    shares = fetch_shares_outstanding(cc, today)

    out: dict[str, Any] = {
        "ticker": ticker,
        "name": meta["name"],
        "corp_code": cc,
        "isur_cd": meta["isur_cd"],
        "as_of": today.isoformat(),
        "shares": shares,
        "acq_decisions": acq,
        "disp_decisions": disp,
        "trust_contracts": trust_sign,
        "trust_cancellations": trust_cancel,
        "current_program": cur,
    }
    if cur:
        out["current_status"] = program_status(cur, today)
        out["current_amendment_check"] = check_program_amended(cc, cur, end)
        total = shares["common_total_adjusted"]
        qty = cur["plan_qty_ostk"] or 0
        out["current_program_pct_of_shares"] = round(qty / total * 100, 4) if total else None
        out["treasury_pct_of_shares"] = (
            round((shares["common_treasury"] or 0) / total * 100, 4) if total else None)
        pre = (cur.get("pre_hold_div_ostk") or 0) + (cur.get("pre_hold_etc_ostk") or 0)
        out["pre_program_treasury_ostk"] = pre
        out["pre_program_treasury_pct"] = round(pre / total * 100, 4) if total else None
        out["projected_treasury_after"] = pre + qty
        out["projected_treasury_after_pct"] = (
            round((pre + qty) / total * 100, 4) if total else None)

        # 자기주식 보유수: 정기보고서 기준일보다 취득결정 결의일이 더 최근이면 그쪽이 최신
        stlm = shares.get("stlm_dt") or ""
        if (cur.get("board_date") or "") > stlm:
            out["treasury_best"] = {
                "value": pre, "as_of": cur["board_date"],
                "source": f"취득결정 {cur['rcept_no']} '8. 취득 전 자기주식 보유현황'",
                "pct": out["pre_program_treasury_pct"],
            }
        else:
            out["treasury_best"] = {
                "value": shares["common_treasury"], "as_of": stlm,
                "source": f"stockTotqySttus {shares['report']}",
                "pct": out["treasury_pct_of_shares"],
            }
    return out


def build_snapshot(today: _dt.date | None = None, write: bool = True) -> dict:
    today = today or _dt.date.today()
    snap = {
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "source": "DART OpenAPI (opendart.fss.or.kr)",
        "companies": {t: build_company(t, today) for t in CORPS},
    }
    if write:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        p = DATA_DIR / "dart_snapshot.json"
        p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        snap["_written_to"] = str(p)
    return snap


# ---------------------------------------------------------------- CLI

def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    today = _dt.date.today()
    snap = build_snapshot(today, write="--print" not in argv)
    for t, c in snap["companies"].items():
        s, cur, st = c["shares"], c.get("current_program"), c.get("current_status")
        print(f"\n===== {c['name']} ({t}) corp_code={c['corp_code']} =====")
        print(f"  발행주식총수(보통) : {_fmt(s['common_total_adjusted'])}  "
              f"[{s['report']} {s['stlm_dt']} 기준 {_fmt(s['common_total'])}"
              f"{' +증자 ' + _fmt(s['adjust_new_shares']) if s['adjust_new_shares'] else ''}]")
        for n in s.get("adjust_notes", []):
            print(f"    · {n}")
        for cx in s.get("crosschecks", []):
            if "error" in cx:
                print(f"    · 교차검증 실패 {cx['source']}: {cx['error']}")
                continue
            v = cx.get("value")
            vs = f"{v:,}" if v else f"{cx['value_range'][0]:,}~{cx['value_range'][1]:,}"
            print(f"    · 교차검증 [{cx['source']} {cx['rcept_no']}] {vs} → "
                  f"{'일치' if cx['match'] else '★불일치'}")
        print(f"  자기주식(보통)     : {_fmt(s['common_treasury'])} "
              f"({c.get('treasury_pct_of_shares')}%)  [{s['report']} {s['stlm_dt']} 기준]")
        tb = c.get("treasury_best")
        if tb:
            print(f"    → 최신 기준       : {_fmt(tb['value'])} ({tb['pct']}%) "
                  f"@{tb['as_of']}  [{tb['source']}]")
        print(f"  취득결정 {len(c['acq_decisions'])}건 / 처분결정 {len(c['disp_decisions'])}건 "
              f"/ 신탁체결 {len(c['trust_contracts'])}건 / 신탁해지 {len(c['trust_cancellations'])}건")
        if cur:
            print(f"  ── 진행 중: {cur['rcept_no']} (결의 {cur['board_date']})")
            print(f"     취득예정 {_fmt(cur['plan_qty_ostk'])}주 / {_fmt(cur['plan_amt_ostk'])}원 "
                  f"= 발행주식수의 {c['current_program_pct_of_shares']}%")
            print(f"     기간 {st['period_start']} ~ {st['deadline_disclosed']}"
                  f"({st['deadline_weekday']}) · {st['deadline_note']}")
            print(f"     거래일 {st['trading_days_elapsed']}/{st['trading_days_total']} 경과, "
                  f"잔여 {st['trading_days_remaining']}일 "
                  f"(마지막 매매일 {st['last_trading_day']}, 마지막 신청일 {st['last_application_day']})")
            am = c["current_amendment_check"]
            print(f"     정정공시: {'있음 → ' + str(am['amend_filings']) if am['amended'] else '없음'}")
        else:
            print("  ── 진행 중인 취득 프로그램 없음")
    if "_written_to" in snap:
        print(f"\n[저장] {snap['_written_to']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
