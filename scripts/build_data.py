# -*- coding: utf-8 -*-
"""
build_data.py — 자사주 매입 대시보드 데이터 파이프라인

  KIND(신고/신청/체결) + DART(취득결정·발행주식총수) + 네이버(일봉)
      →  data/buyback.json

설계 원칙
--------------------------------------------------------------------------
1. 금액 단위는 **함수 경계에서 즉시 '원(KRW)'으로 정규화**한다.
   - KIND decl '체결금액누계'  : 원 단위 그대로   (price_source.fetch_decl)
   - DART aqpln_prc_ostk       : 원 단위 그대로   (dart_source._norm_acq)
   - 네이버 시세               : 원/주
   - ※ 레퍼런스 사이트(raoni)의 amountThousandKrw 만 '천원'이다. 우리는 그 소스를
     쓰지 않으며, 교차검증할 때만 ×1000 해서 비교한다(_crosscheck_reference).
   JSON 에 나가는 금액 필드는 전부 접미사 `_krw` 를 붙여 원 단위임을 명시한다.

2. 신청일 → 매매일 정렬.  KIND appl 의 신청일 D 는 매매일 next_business_day(D)
   에 대응한다(FINDINGS.md 실측). daily[] 는 '매매일' 기준으로 만들고
   applied_date 에 원 신청일을 남긴다.

3. 불변식 게이트. INVARIANTS 전부를 통과하지 못하면 InvariantError 를 던지고
   buyback.json 을 **쓰지 않는다**. 어떤 불변식이 왜 깨졌는지 메시지에 담는다.

4. 네트워크 예의. DART 0.7초 / KIND 0.5초 / 네이버 0.35초 최소 간격 +
   3회 지수 백오프 재시도. (사용자 환경에서 DART 웹은 초당 2건이면 IP 차단 전력)

5. 실패를 조용히 넘기지 않는다. 값이 없으면 None 으로 두되 어떤 필드가 왜 없는지
   warnings[] 에 남긴다.

실행
--------------------------------------------------------------------------
    python scripts/build_data.py            # 수집 → 검증 → data/buyback.json
    python scripts/build_data.py --dry-run  # 파일 쓰지 않고 요약만 출력
"""

from __future__ import annotations

import argparse
import datetime as _dt
import functools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dart_source as ds          # noqa: E402  DART OpenAPI (취득결정 / 발행주식총수 / 정정탐지)
import market_data as md          # noqa: E402  네이버 일봉 + KRX 공식 휴장일 캘린더
import price_source as ps         # noqa: E402  KIND 신고/신청/체결 + 일별 체결금액

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "buyback.json"

KST = _dt.timezone(_dt.timedelta(hours=9))

# 대상 회사 (dart_source.CORPS 와 동일 마스터를 재사용)
TICKERS = ["005930", "000660"]

# ---------------------------------------------------------------- 판정 임계값
# pace_eta_date 가 deadline_business_day 보다 며칠(거래일) 앞서야 '여유'로 보는가.
TIGHT_MARGIN_BD = 5
# 일별 체결 페이스를 평균낼 창(거래일 수). raoni 의 recentAvg 와 같은 5일.
PACE_WINDOW_BD = 5
# avg_price × quantity ≈ amount_krw 허용오차
AMOUNT_TOLERANCE = 0.005          # 0.5%
# sum(daily amount) ≈ KIND decl 체결금액누계 허용오차 (배분 반올림 흡수)
TOTAL_AMOUNT_TOLERANCE = 0.001    # 0.1%

# ---- 추정기(estimated_hl2) 정확도 — 매 빌드에서 실측 대조로 다시 계산한다 -------
# ★ 하드코딩 금지. estimator_backtest() 가 _ref 의 KIND-검증 실측 일별액과 대조해 채운다.
ESTIMATOR_STATS: dict[str, dict] = {}
ESTIMATOR_ACCURACY_TEXT = "일별 오차는 실측 대조 전이라 미상."


class InvariantError(AssertionError):
    """불변식 위반. 이 예외가 나면 buyback.json 을 쓰지 않는다."""


# ================================================================ 네트워크 예의
_LAST_CALL: dict[str, float] = {}
MIN_INTERVAL = {"dart": 0.7, "kind": 0.5, "naver": 0.35}


def _throttle(key: str) -> None:
    gap = MIN_INTERVAL.get(key, 0.5)
    wait = gap - (time.monotonic() - _LAST_CALL.get(key, 0.0))
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[key] = time.monotonic()


def _throttled(fn, key: str):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        _throttle(key)
        return fn(*a, **kw)
    return wrapper


def _retry(fn, *a, tries: int = 3, key: str = "naver", **kw):
    """지수 백오프 재시도. 마지막 실패는 예외를 그대로 올린다."""
    last = None
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(0.8 * (2 ** i))
    raise RuntimeError(f"{getattr(fn, '__name__', fn)} 실패(재시도 {tries}회): {last!r}")


# 원본 모듈의 저수준 HTTP 진입점을 그대로 감싼다(모듈 코드는 건드리지 않는다).
ds._get = _throttled(ds._get, "dart")                            # type: ignore[assignment]
ds.fetch_document_text = _throttled(ds.fetch_document_text, "dart")  # type: ignore[assignment]
ps._kind_download = _throttled(ps._kind_download, "kind")        # type: ignore[assignment]
ps.fetch_ohlcv = _throttled(ps.fetch_ohlcv, "naver")             # type: ignore[assignment]
md._http = _throttled(md._http, "naver")                         # type: ignore[assignment]


# ================================================================ 유틸
def _d(s) -> _dt.date:
    if isinstance(s, _dt.date):
        return s
    return _dt.date.fromisoformat(str(s)[:10])


def _iso(d) -> str | None:
    return None if d is None else _d(d).isoformat()


def _ratio(a, b):
    if a is None or not b:
        return None
    return a / b


def _flat(s: str | None) -> str | None:
    """
    DART 공시 원문 필드는 줄바꿈이 그대로 들어 있다
    (예: aq_pp='자기주식 소각을 통한 \\n주주가치 제고').
    ★ 첫 줄만 취하면 문장이 잘린다 — 줄바꿈을 공백으로 접어 한 줄로 만든다.
    """
    if not s:
        return None
    t = " ".join(str(s).split())
    return t or None


def _is_cancellation(purpose: str | None) -> bool | None:
    """
    취득 목적이 '소각'인가. 소각이면 발행주식수가 실제로 줄어(EPS 상승),
    임직원 보상용이면 발행주식수는 그대로다 — 비교 시 가장 결정적인 차이.
    판별 불가면 None.
    """
    t = _flat(purpose)
    if not t:
        return None
    if "소각" in t:
        return True
    if any(k in t for k in ("주식보상", "상여", "임직원", "스톡옵션", "성과급", "보상")):
        return False
    return None


def estimator_backtest(ticker: str, ohlcv: dict) -> dict | None:
    """
    ★ estimated_hl2 의 실제 오차를 '하드코딩이 아니라' 매 빌드에서 계산한다.

    _ref/raoni_api_*.json 의 일별 체결금액(KIND decl 체결금액누계와 원 단위 대조 완료)을
    실측값으로 두고, 같은 날짜·같은 수량에 (고가+저가)/2 가중 배분 + 총액 정합을
    적용했을 때 얼마나 어긋나는지 전수 대조한다.
    반환: {"n", "mae_pct", "max_pct", "max_date"} 또는 None.
    """
    f = ROOT / "_ref" / f"raoni_api_{ticker}.json"
    if not f.exists():
        return None
    try:
        ref = json.loads(f.read_text(encoding="utf-8"))
        hist = [r for r in ref.get("kind", {}).get("history", []) if r.get("filled")]
    except Exception:                                    # noqa: BLE001
        return None
    obs = {}
    for r in hist:
        fl = r["filled"]
        amt, q = fl.get("amountThousandKrw"), fl.get("quantity")
        b = ohlcv.get(r["date"])
        if not (amt and q and b):
            continue
        obs[r["date"]] = (amt * 1000, q, (b["high"] + b["low"]) / 2.0)
    if len(obs) < 2:
        return None
    total = sum(v[0] for v in obs.values())
    wsum = sum(v[1] * v[2] for v in obs.values())
    if wsum <= 0:
        return None
    errs = []
    for d, (amt, q, hl2) in obs.items():
        est = q * hl2 * total / wsum
        errs.append((abs(est / amt - 1) * 100, d))
    mx = max(errs)
    return {"n": len(errs),
            "mae_pct": round(sum(e for e, _ in errs) / len(errs), 3),
            "max_pct": round(mx[0], 3),
            "max_date": mx[1]}


def _estimator_text(stats: dict[str, dict]) -> str:
    vals = [s for s in stats.values() if s]
    if not vals:
        return "일별 오차는 실측 대조 전이라 미상."
    maes = sorted(s["mae_pct"] for s in vals)
    mx = max(s["max_pct"] for s in vals)
    lo, hi = maes[0], maes[-1]
    rng = f"{lo:.1f}%" if abs(hi - lo) < 0.05 else f"{lo:.1f}~{hi:.1f}%"
    return f"일별 MAE {rng}, 최대 ±{mx:.1f}%."


# ================================================================ KIND 신청내역
def fetch_appl(isur_cd: str, name: str, code: str,
               from_date: str, to_date: str, sess=None) -> list[dict]:
    """
    KIND 자기주식 매매 '신청내역'.

    downloadAppl 컬럼(실측 7개):
        신청일 | 종목명 | 종목코드 | 자사주구분 | 취득/처분구분 | 신청수량 | 신청가능수량

    ★ 종목코드만으로는 부족하다 — '삼성전자우' 행도 code='005930' 으로 나온다.
      반드시 종목명까지 일치시켜야 한다.
    반환 수량 단위는 '주', 날짜는 '신청일'(매매일 아님).
    """
    sess = sess or ps._session()
    rows = ps._kind_download(sess, "downloadAppl", "appl", isur_cd, name,
                             from_date, to_date, 7)
    out = []
    for c in rows:
        if c[2] != code or c[1] != name:
            continue
        out.append({
            "appl_date": c[0],
            "name": c[1], "code": c[2],
            "trstk_gubun": c[3],          # 직접 / 신탁 / 스톡옵션
            "side": c[4],                 # 취득 / 처분
            "applied_qty": ps._num(c[5]),
            "appliable_qty": ps._num(c[6]),   # 신청 '전' 잔여 신고수량
        })
    out.sort(key=lambda r: r["appl_date"])
    return out


# ================================================================ 회사 단위 수집
def collect_company(ticker: str, today: _dt.date, sess) -> dict[str, Any]:
    """한 회사의 raw 데이터를 모아 dict 로. 네트워크 호출은 전부 여기서."""
    meta = ds.CORPS[ticker]
    corp_code, isur_cd, name = meta["corp_code"], meta["isur_cd"], meta["name"]
    end_s = today.strftime("%Y%m%d")
    warns: list[str] = []

    # ---------------------------------------------------------- (1) DART
    acq = ds.fetch_acq_decisions(corp_code, "20240101", end_s)
    prog = next((p for p in reversed(acq) if ds.is_program_active(p, today)), None)
    status = "active"
    if prog is None:
        # ★ 프로그램이 끝나는 순간이 오히려 결산이 필요한 시점이다. 예외로 죽지 말고
        #   '마지막으로 끝난 프로그램의 최종 결과'를 보여주는 종료 뷰로 전환한다.
        ended = [p for p in acq if p.get("period_end")]
        ended.sort(key=lambda p: str(p["period_end"]))
        if not ended:
            raise InvariantError(
                f"[{ticker} {name}] DART tsstkAqDecsn 에 자기주식 취득결정이 하나도 없다 "
                f"(조회 {len(acq)}건). 보여줄 프로그램이 없다.")
        prog = ended[-1]
        status = "ended"
        warns.append(
            f"오늘({today}) 진행 중인 자기주식 취득 프로그램이 없다 → 마지막으로 종료된 "
            f"프로그램({prog['period_start']}~{prog['period_end']}, 공시 {prog['rcept_no']})의 "
            f"최종 결과를 표시한다.")

    # 정정공시 여부 — 진행률 분모(plan_shares)가 바뀌었을 수 있으므로 매 실행 확인
    amend = ds.check_program_amended(corp_code, prog, end_s)
    if amend.get("amended"):
        warns.append(
            f"DART 정정공시 감지: {[f['rcept_no'] for f in amend['amend_filings']]} "
            f"— tsstkAqDecsn 은 최신 정정본만 반환하므로 plan_shares/기간이 "
            f"이미 정정 반영된 값일 수 있다. 수동 확인 필요.")

    shares = ds.fetch_shares_outstanding(corp_code, today)
    if not shares.get("crosscheck_ok", True):
        warns.append(f"발행주식총수 교차검증 불일치: {shares.get('adjust_notes')}")

    # ---------------------------------------------------------- (2) KIND
    p_from, p_to = _d(prog["period_start"]), _d(prog["period_end"])
    # appl 은 매매일의 '직전 영업일'에 제출되므로 프로그램 시작 이전까지 거슬러 조회한다.
    appl_from = md.prev_business_day(p_from)
    lookback = (p_from - _dt.timedelta(days=30)).isoformat()

    decls = [d for d in ps.fetch_decl(isur_cd, name, lookback, today.isoformat(), sess)
             if d["code"] == ticker and d["name"] == name and "취득" in d["kind"]
             and d["period_from"] == p_from.isoformat()]
    if not decls:
        raise InvariantError(
            f"[{ticker} {name}] KIND decl(신고내역)에서 프로그램 "
            f"{p_from}~{p_to} 을 찾지 못했다. DART 취득결정과 KIND 신고가 어긋난다.")
    decl = decls[-1]

    appl = [a for a in fetch_appl(isur_cd, name, ticker,
                                  appl_from.isoformat(), today.isoformat(), sess)
            if a["side"] == "취득" and a["trstk_gubun"] == decl["kind"].split("/")[0].strip()
            and appl_from.isoformat() <= a["appl_date"] <= today.isoformat()]

    # 일별 체결(수량은 정확, 금액은 정확/추정 혼재 — amount_source 로 구분)
    exec_to = min(today, p_to)
    execs = ps.fetch_exec_detail(ticker, isur_cd, name,
                                 p_from.isoformat(), exec_to.isoformat(), sess=sess)

    # ---------------------------------------------------------- (3) 시세
    ohlcv_rows = _retry(md.fetch_ohlcv, ticker, p_from.isoformat(), today.isoformat())
    ohlcv = {r["date"]: r for r in ohlcv_rows}

    return {
        "meta": meta, "ticker": ticker, "warns": warns, "status": status,
        "program": prog, "acq_all": acq, "amend": amend, "shares": shares,
        "decl": decl, "appl": appl, "execs": execs, "ohlcv": ohlcv,
    }


# ================================================================ 조립
def assemble(raw: dict[str, Any], today: _dt.date) -> dict[str, Any]:
    ticker = raw["ticker"]
    meta, prog, decl = raw["meta"], raw["program"], raw["decl"]
    warns: list[str] = list(raw["warns"])
    status = raw.get("status", "active")

    p_from, p_to = _d(prog["period_start"]), _d(prog["period_end"])
    plan_shares = prog["plan_qty_ostk"]
    plan_amount_krw = prog["plan_amt_ostk"]          # ← DART 원 단위(원)
    daily_limit = prog["daily_limit_ostk"]

    # ---- 공시 마감일 / 실질 마지막 매매일 ------------------------------------
    deadline_raw = p_to
    deadline_bd = md.prev_business_day(p_to, inclusive=True)
    if deadline_bd != deadline_raw:
        warns.append(
            f"공시 취득기간 종료일 {deadline_raw} 는 휴장일(주말/공휴일)이다 → "
            f"실질 마지막 매매일 {deadline_bd}.")

    # ---- 신청일 → 매매일 정렬 ------------------------------------------------
    appl_by_trade: dict[str, dict] = {}
    for a in raw["appl"]:
        td = md.next_business_day(_d(a["appl_date"]))     # ★규칙 1
        if td.isoformat() in appl_by_trade:
            warns.append(f"신청행 중복: 매매일 {td} 에 신청일 "
                         f"{appl_by_trade[td.isoformat()]['appl_date']} 와 "
                         f"{a['appl_date']} 가 함께 매핑됨. 뒤엣것을 채택.")
        appl_by_trade[td.isoformat()] = a

    exec_by_date = {e["date"]: e for e in raw["execs"]}
    ohlcv = raw["ohlcv"]

    # ---- daily[] -------------------------------------------------------------
    last_day = min(today, deadline_bd)
    trading = md.business_days_list(p_from, last_day)
    daily: list[dict] = []
    cum = 0
    for d in trading:
        ds_ = d.isoformat()
        a = appl_by_trade.get(ds_)
        e = exec_by_date.get(ds_)
        q = e["quantity"] if e else None
        amt = e["amount_krw"] if e else None            # 원 단위
        avg = e["avg_price"] if e else None
        bar = ohlcv.get(ds_)
        close = bar["close"] if bar else None
        vol = bar["volume"] if bar else None
        if q is not None:
            cum += q
        applied = a["applied_qty"] if a else None
        daily.append({
            "date": ds_,
            "applied": applied,
            "applied_date": a["appl_date"] if a else None,
            "appliable_before": a["appliable_qty"] if a else None,
            "filled": q,
            "fill_rate": _ratio(q, applied),
            "amount_krw": amt,
            "avg_price": (round(avg) if avg is not None else None),
            "amount_exact": (e["amount_exact"] if e else None),
            "amount_source": (e["amount_source"] if e else None),
            "cumulative": cum,
            "close": close,
            "volume": vol,
            "share_of_volume": _ratio(q, vol),
            "avg_vs_close": ((avg / close - 1) if (avg and close) else None),
            "provisional": (q is None),
        })

    # 결측 사유 기록
    for r in daily:
        if r["filled"] is None:
            warns.append(
                f"{r['date']}: 체결수량 없음 — KIND 는 당일 체결분을 18시 이후 집계한다"
                f"(신청 {r['applied']:,}주 는 이미 공시됨)."
                if r["applied"] else f"{r['date']}: 체결·신청 데이터 모두 없음.")
        if r["close"] is None:
            warns.append(f"{r['date']}: 네이버 일봉 없음 — 장 마감(15:30 KST) 전이면 정상.")
        if r["filled"] is not None and r["amount_krw"] is None:
            warns.append(f"{r['date']}: 체결금액 확보 실패(amount_source=unavailable).")

    est_days = [r for r in daily if r.get("amount_source") == "estimated_hl2"]
    if est_days:
        warns.append(
            f"일별 체결금액 {len(est_days)}일이 추정치다(amount_source='estimated_hl2'). "
            f"KOSPI×직접취득은 KIND trddetail 체결금액이 구조적으로 공란이라 "
            f"(고가+저가)/2 가중 배분 후 총액을 KIND 누계에 맞췄다. "
            f"{ESTIMATOR_ACCURACY_TEXT} 총액·누적평단은 정확.")
    back_days = [r for r in daily if r.get("amount_source") == "kind_decl_backfill"]
    if back_days:
        warns.append(
            f"일별 체결금액 {len(back_days)}일은 파이프라인 가동 전 구간이라 "
            f"data/kind_decl_backfill.json 의 KIND 누계 백필 차분을 썼다"
            f"(amount_source='kind_decl_backfill', 프로그램 누계는 KIND 원본과 대조 완료).")

    # ---- derived -------------------------------------------------------------
    cum_filled = cum
    settled = [r for r in daily if r["filled"] is not None]
    exec_rows = [r for r in daily if (r["filled"] or 0) > 0]
    exec_days = len(exec_rows)
    last_settled = _d(settled[-1]["date"]) if settled else None

    # 프로그램 누적 금액은 KIND decl 원본(원 단위)이 항상 정확하다.
    spent_krw = decl["cum_amount_krw"]
    avg_cost = _ratio(spent_krw, cum_filled)
    remaining_shares = (plan_shares - cum_filled) if plan_shares is not None else None
    progress_ratio = _ratio(cum_filled, plan_shares)
    remaining_est_krw = (round(remaining_shares * avg_cost)
                         if (remaining_shares is not None and avg_cost) else None)

    # 남은 거래일 : '아직 체결이 집계되지 않은 첫 거래일' ~ 실질 마지막 매매일 (양끝 포함)
    first_open = (md.next_business_day(last_settled) if last_settled
                  else md.next_business_day(p_from, inclusive=True))
    if first_open > deadline_bd:
        business_days_left = 0
        open_days: list[_dt.date] = []
    else:
        open_days = md.business_days_list(first_open, deadline_bd)
        business_days_left = len(open_days)

    total_bd = len(md.business_days_list(p_from, deadline_bd))
    elapsed_bd = len(md.business_days_list(p_from, last_settled)) if last_settled else 0
    elapsed_ratio = _ratio(elapsed_bd, total_bd)
    # ★ 기준일이 다르다는 사실을 필드명에 박는다.
    #   elapsed_ratio             : last_settled(체결 집계 완료일) 기준, 거래일
    #   elapsed_ratio_calendar_asof_today : today 기준, 달력일 (raoni 방식, UI 미표시)
    elapsed_ratio_calendar_asof_today = _ratio((today - p_from).days, (p_to - p_from).days)

    # 페이스: 최근 PACE_WINDOW_BD 개의 '체결이 집계된 거래일' 평균 체결량.
    #   - 체결 0주인 날도 집계되었으면 포함한다(페이스가 실제로 느려진 것이므로).
    #   - 아직 집계 안 된 오늘(체결 null)은 제외한다.
    #   ★ 표본이 5일 미만일 수 있다 — 실제 표본 크기를 그대로 내보낸다.
    recent = settled[-PACE_WINDOW_BD:]
    pace_window_used = len(recent)
    recent5_avg = (sum(r["filled"] for r in recent) / len(recent)) if recent else None
    all_avg = (cum_filled / len(settled)) if settled else None
    required_daily_avg = _ratio(remaining_shares, business_days_left)
    if 0 < pace_window_used < PACE_WINDOW_BD:
        warns.append(
            f"페이스 표본 {pace_window_used}일(목표 {PACE_WINDOW_BD}일 미만) — "
            f"완료 예상일(ETA) 신뢰도가 낮다.")

    pace_eta_date = pace_eta_bd = None
    if status == "ended":
        warns.append("프로그램이 종료돼 페이스 기반 완료 예상(ETA)은 산출하지 않는다.")
    elif remaining_shares is not None and remaining_shares <= 0:
        pace_eta_date, pace_eta_bd = (last_settled.isoformat() if last_settled else None), 0
    elif recent5_avg and recent5_avg > 0 and remaining_shares:
        pace_eta_bd = int(math.ceil(remaining_shares / recent5_avg))
        # first_open 부터 세어 pace_eta_bd 번째 '거래일'(주말+공휴일 제외)
        try:
            pace_eta_date = md.add_business_days(first_open, pace_eta_bd - 1).isoformat()
        except (md.HolidayCoverageError, ValueError) as e:
            pace_eta_bd = None
            warns.append(f"pace_eta_date 산출 불가 — {e}")
    else:
        warns.append("최근 체결 페이스가 0 이라 pace_eta_date 를 계산할 수 없다.")

    # 여유 거래일 = ETA 다음날부터 실질 마지막 매매일까지의 거래일 수
    margin_bd = None
    if pace_eta_date:
        eta = _d(pace_eta_date)
        if eta <= deadline_bd:
            margin_bd = len(md.business_days_list(eta, deadline_bd)) - 1
        else:
            margin_bd = -(len(md.business_days_list(deadline_bd, eta)) - 1)

    # ---- 휴장일 캘린더 자체를 시세로 교차검증 --------------------------------
    # covers 범위 '안'의 누락/오탐은 커버리지 게이트로는 못 잡는다. 네이버 일봉은
    # 실제로 장이 열린 날에만 존재하므로, 두 집합이 어긋나면 캘린더가 틀린 것이다.
    if last_settled:
        cal = {d.isoformat() for d in md.business_days_list(p_from, last_settled)}
        quo = {d for d in ohlcv if p_from.isoformat() <= d <= last_settled.isoformat()}
        miss = sorted(cal - quo)      # 달력은 거래일이라는데 시세가 없다 → 휴장일 누락 의심
        extra = sorted(quo - cal)     # 시세는 있는데 달력은 휴장 → 휴장일 오탐
        if miss:
            warns.append(f"휴장일 캘린더 의심(누락): {miss} 은 거래일로 계산됐지만 그날 일봉이 "
                         f"없다. holidays_kr.json 을 재수집하라.")
        if extra:
            warns.append(f"휴장일 캘린더 의심(오탐): {extra} 은 휴장으로 계산됐지만 그날 일봉이 "
                         f"있다. holidays_kr.json 을 재수집하라.")

    # ---- 잠정(오늘 신청분 반영) 진행률 ---------------------------------------
    # 오늘 신청량은 이미 공시돼 있고 체결률이 100% 로 이어져 왔다면 오늘 진행률은
    # 확정치보다 앞서 있다. 확정/잠정을 색으로 분리해 보여주기 위한 파생값.
    # 종료된 프로그램에는 '오늘 신청 반영 시' 라는 개념이 없다.
    prov_rows = ([] if status == "ended"
                 else [r for r in daily if r["provisional"] and r["applied"]])
    provisional_applied = sum(r["applied"] for r in prov_rows) or None
    provisional_cumulative = ((cum_filled + provisional_applied)
                              if provisional_applied else None)
    provisional_ratio = _ratio(provisional_cumulative, plan_shares)
    fr = [r["fill_rate"] for r in daily if r["fill_rate"] is not None]
    fill_rate_avg = (sum(fr) / len(fr)) if fr else None

    # ---- 금액 한도 여유 ------------------------------------------------------
    # 현재 평단으로 잔여 물량을 다 사면 공시 취득예정금액을 넘는가?
    amount_headroom_krw = None
    if plan_amount_krw is not None and spent_krw is not None and remaining_est_krw is not None:
        amount_headroom_krw = plan_amount_krw - spent_krw - remaining_est_krw
        if amount_headroom_krw < 0:
            warns.append(
                f"금액 한도 초과 우려: 현 평단({round(avg_cost):,}원)으로 잔여 "
                f"{remaining_shares:,}주를 다 매입하면 "
                f"{spent_krw + remaining_est_krw:,}원 → 공시 취득예정금액 "
                f"{plan_amount_krw:,}원 대비 {-amount_headroom_krw:,}원"
                f"({-amount_headroom_krw / plan_amount_krw * 100:.2f}%) 초과. "
                f"초과 매입에는 정정공시가 필요하다.")

    # ---- 기한 내 완료 판정 (임계값은 파일 상단 상수) --------------------------
    if status == "ended":
        done = (progress_ratio or 0) >= 0.999
        verdict = {"code": "ended",
                   "label": "프로그램 종료" + (" · 전량 취득" if done else " · 미달"),
                   "reason": f"취득기간 {p_from}~{p_to} 종료. 최종 진행률 "
                             f"{(progress_ratio or 0) * 100:.2f}% "
                             f"({cum_filled:,}/{plan_shares:,}주), 총 매입 {spent_krw:,}원"
                             + (f", 평단 {round(avg_cost):,}원" if avg_cost else "")}
    elif required_daily_avg is not None and daily_limit and required_daily_avg > daily_limit:
        verdict = {"code": "impossible",
                   "label": "기한 내 완료 불가(1일 한도 초과)",
                   "reason": f"필요 일평균 {required_daily_avg:,.0f}주 > 1일 매수한도 "
                             f"{daily_limit:,}주"}
    elif margin_bd is None:
        verdict = {"code": "unknown", "label": "판정 불가",
                   "reason": "체결 페이스 데이터 부족"}
    elif margin_bd < 0:
        verdict = {"code": "unlikely", "label": "기한 내 완료 불가",
                   "reason": f"현 페이스 ETA {pace_eta_date} 가 실질 마감 {deadline_bd} 보다 "
                             f"{-margin_bd}거래일 늦다"}
    elif margin_bd < TIGHT_MARGIN_BD:
        verdict = {"code": "tight", "label": "빠듯",
                   "reason": f"여유 {margin_bd}거래일 (< 임계 {TIGHT_MARGIN_BD}거래일)"}
    else:
        verdict = {"code": "ok", "label": "기한 내 완료 가능",
                   "reason": f"여유 {margin_bd}거래일 (>= 임계 {TIGHT_MARGIN_BD}거래일)"}

    if not _flat(prog.get("brokers")):
        warns.append("DART 취득결정에 위탁증권사(cs_iv_bk)가 비어 있다 → broker=null.")

    shares_out = raw["shares"]["common_total_adjusted"]
    treasury_held = ((prog.get("pre_hold_div_ostk") or 0)
                     + (prog.get("pre_hold_etc_ostk") or 0))

    company = {
        "meta": {
            "code": ticker,
            "name": meta["name"],
            "isur_cd": meta["isur_cd"],
            "corp_code": meta["corp_code"],
            "generated_at": _dt.datetime.now(KST).isoformat(timespec="seconds"),
            "as_of": today.isoformat(),
            "status": status,          # 'active' | 'ended'
        },
        "program": {
            "rcept_no": prog["rcept_no"],
            "decision_date": prog["board_date"],
            "plan_shares": plan_shares,
            "plan_amount_krw": plan_amount_krw,
            "period_from": p_from.isoformat(),
            "period_to": p_to.isoformat(),
            "method": _flat(prog.get("method")),
            # ★ dart_source._norm_acq 가 내보내는 키는 'brokers'(복수)다. 'broker' 로
            #   읽으면 항상 None 이 된다. 위탁증권사가 여럿이면 콤마로 이어져 온다.
            "broker": _flat(prog.get("brokers")),
            "daily_limit": daily_limit,
            "shares_outstanding": shares_out,
            "shares_outstanding_note": (
                f"{raw['shares']['report']} 기준 {raw['shares']['common_total']:,}주"
                + (f" + 이후 유상증자 {raw['shares']['adjust_new_shares']:,}주"
                   if raw["shares"]["adjust_new_shares"] else "")),
            "treasury_held": treasury_held,
            "treasury_held_as_of": prog["board_date"],
            "purpose": _flat(prog.get("purpose")),
            "kind_declared_qty": decl["declared_qty"],
            "amended": bool(raw["amend"].get("amended")),
            "status": status,
            # 소각 목적이면 발행주식수가 실제로 줄어든다(EPS 증가). 보상용이면 줄지 않는다.
            "is_cancellation": _is_cancellation(prog.get("purpose")),
        },
        "daily": daily,
        "derived": {
            "cum_filled": cum_filled,
            "progress_ratio": progress_ratio,
            "remaining_shares": remaining_shares,
            "spent_krw": spent_krw,
            "avg_cost": (round(avg_cost) if avg_cost else None),
            "avg_cost_exact": avg_cost,
            "remaining_est_krw": remaining_est_krw,
            "recent5_avg": recent5_avg,
            "all_avg": all_avg,
            "required_daily_avg": required_daily_avg,
            "business_days_left": business_days_left,
            "business_days_total": total_bd,
            "business_days_elapsed": elapsed_bd,
            "deadline_raw": deadline_raw.isoformat(),
            "deadline_business_day": deadline_bd.isoformat(),
            "deadline_is_business_day": deadline_raw == deadline_bd,
            "last_application_day": md.prev_business_day(deadline_bd).isoformat(),
            "pace_eta_date": pace_eta_date,
            "pace_eta_business_days": pace_eta_bd,
            # ★ 실제로 평균에 쓰인 표본 크기(상수 5가 아니다).
            "pace_window_bd": pace_window_used,
            "pace_window_target_bd": PACE_WINDOW_BD,
            "pace_margin_business_days": margin_bd,
            "completion_verdict": verdict,
            "provisional_applied": provisional_applied,
            "provisional_cumulative": provisional_cumulative,
            "provisional_ratio": provisional_ratio,
            "fill_rate_avg": fill_rate_avg,
            "amount_headroom_krw": amount_headroom_krw,
            "amount_headroom_pct": (round(amount_headroom_krw / plan_amount_krw * 100, 4)
                                    if (amount_headroom_krw is not None and plan_amount_krw)
                                    else None),
            "deadline_short_session": md.short_session_info(deadline_bd),
            "pace_eta_short_session": (md.short_session_info(pace_eta_date)
                                       if pace_eta_date else None),
            "on_schedule_gap_pp": (round((progress_ratio - elapsed_ratio) * 100, 4)
                                   if (progress_ratio is not None
                                       and elapsed_ratio is not None) else None),
            "elapsed_ratio": elapsed_ratio,
            "elapsed_ratio_calendar_asof_today": elapsed_ratio_calendar_asof_today,
            "exec_days": exec_days,
            "settled_days": len(settled),
            "last_settled_date": _iso(last_settled),
            "pct_of_shares_outstanding": (round(plan_shares / shares_out * 100, 4)
                                          if shares_out else None),
            "kind_cum_qty": decl["cum_qty"],
            "kind_cum_ratio_pct": decl["cum_ratio_pct"],
        },
        "warnings": warns,
    }
    return company


# ================================================================ 불변식 게이트
def check_invariants(c: dict[str, Any]) -> list[str]:
    """통과하면 [] 반환. 위반 메시지를 모아서 돌려준다."""
    bad: list[str] = []
    tag = f"[{c['meta']['code']} {c['meta']['name']}]"
    p, d, rows = c["program"], c["derived"], c["daily"]
    plan = p["plan_shares"]
    limit = p["daily_limit"]

    # (1) 누적 일관성: cumulative[i] == cumulative[i-1] + filled[i]
    prev = 0
    for r in rows:
        want = prev + (r["filled"] or 0)
        if r["cumulative"] != want:
            bad.append(f"{tag} 누적 불일치 {r['date']}: cumulative={r['cumulative']:,} "
                       f"!= 직전 {prev:,} + 당일 {(r['filled'] or 0):,} = {want:,}")
        prev = r["cumulative"]

    # (2) 총량/한도
    if plan is not None and d["cum_filled"] > plan:
        bad.append(f"{tag} 누적 체결 {d['cum_filled']:,} > 취득예정 {plan:,}")
    if limit:
        for r in rows:
            if (r["filled"] or 0) > limit:
                bad.append(f"{tag} 1일 한도 초과 {r['date']}: 체결 {r['filled']:,} "
                           f"> 한도 {limit:,}")

    # (3) KIND appl 불변식: 신청가능수량[D] == 취득예정수량 − (D 이전 누적 신청수량)
    applied_before = 0
    for r in sorted([x for x in rows if x["applied_date"]], key=lambda x: x["applied_date"]):
        exp = plan - applied_before
        if r["appliable_before"] is not None and r["appliable_before"] != exp:
            bad.append(f"{tag} 신청가능수량 불일치 (신청일 {r['applied_date']}): "
                       f"KIND {r['appliable_before']:,} != 취득예정 {plan:,} − "
                       f"이전누적신청 {applied_before:,} = {exp:,}")
        applied_before += r["applied"] or 0

    # (4) 진행률
    if plan:
        exp = d["cum_filled"] / plan
        if d["progress_ratio"] is None or abs(d["progress_ratio"] - exp) > 1e-12:
            bad.append(f"{tag} progress_ratio {d['progress_ratio']} != "
                       f"cum_filled/plan_shares {exp}")
        if not (0.0 <= (d["progress_ratio"] or -1) <= 1.0):
            bad.append(f"{tag} progress_ratio 범위 이탈: {d['progress_ratio']}")

    # (5) 모든 date 가 영업일
    for r in rows:
        if not md.is_business_day(r["date"]):
            bad.append(f"{tag} daily 에 비영업일 포함: {r['date']}")

    # (6) avg_price × quantity ≈ amount_krw (단가가 있는 행만)
    for r in rows:
        if r["avg_price"] and r["filled"] and r["amount_krw"]:
            calc = r["avg_price"] * r["filled"]
            if abs(calc - r["amount_krw"]) / r["amount_krw"] > AMOUNT_TOLERANCE:
                bad.append(f"{tag} 단가×수량 불일치 {r['date']}: "
                           f"{r['avg_price']:,}×{r['filled']:,}={calc:,} vs "
                           f"amount_krw {r['amount_krw']:,}")

    # (7) 크로스소스: 일별 체결수량 합 == KIND decl 체결수량누계,
    #     일별 체결금액 합 ≈ KIND decl 체결금액누계 (배분 반올림 허용)
    if d["kind_cum_qty"] is not None and d["cum_filled"] != d["kind_cum_qty"]:
        bad.append(f"{tag} 일별 체결수량 합 {d['cum_filled']:,} != "
                   f"KIND decl 체결수량누계 {d['kind_cum_qty']:,}")
    tot = sum(r["amount_krw"] or 0 for r in rows)
    if d["spent_krw"] and tot:
        if abs(tot - d["spent_krw"]) / d["spent_krw"] > TOTAL_AMOUNT_TOLERANCE:
            bad.append(f"{tag} 일별 체결금액 합 {tot:,}원 != "
                       f"KIND decl 체결금액누계 {d['spent_krw']:,}원")
        # ★ 수량이 완전히 정합하고 모든 체결일에 금액이 붙어 있으면 합계는
        #   **원 단위까지** 같아야 한다(배분 잔차를 최대 수량일에 흡수시켰으므로).
        settled_rows = [r for r in rows if (r["filled"] or 0) > 0]
        if (d["kind_cum_qty"] is not None and d["cum_filled"] == d["kind_cum_qty"]
                and settled_rows and all(r["amount_krw"] is not None for r in settled_rows)
                and tot != d["spent_krw"]):
            bad.append(f"{tag} 일별 체결금액 합 {tot:,}원 이 KIND decl 체결금액누계 "
                       f"{d['spent_krw']:,}원 과 {tot - d['spent_krw']:+,}원 어긋난다 "
                       f"(반올림 잔차 흡수 실패)")

    # (9) 날짜·영업일 파생값 항등식
    if None not in (d["business_days_total"], d["business_days_elapsed"],
                    d["business_days_left"]):
        s = d["business_days_elapsed"] + d["business_days_left"]
        if s != d["business_days_total"]:
            bad.append(f"{tag} 영업일 항등식 위반: elapsed {d['business_days_elapsed']} + "
                       f"left {d['business_days_left']} = {s} != total "
                       f"{d['business_days_total']}")
    if d["pace_margin_business_days"] is not None and d["pace_eta_business_days"] is not None:
        s = d["business_days_left"] - d["pace_eta_business_days"]
        if s != d["pace_margin_business_days"]:
            bad.append(f"{tag} 여유 거래일 항등식 위반: left {d['business_days_left']} − "
                       f"eta {d['pace_eta_business_days']} = {s} != margin "
                       f"{d['pace_margin_business_days']}")

    # (10) 실질 마감일 보정이 옳은가: deadline_bd <= deadline_raw 이고 그 사이에 거래일이 없다
    draw, dbd = _d(d["deadline_raw"]), _d(d["deadline_business_day"])
    if dbd > draw:
        bad.append(f"{tag} deadline_business_day {dbd} > deadline_raw {draw}")
    elif dbd < draw:
        between = [x for x in md.business_days_list(dbd, draw) if x != dbd]
        if between:
            bad.append(f"{tag} deadline 보정 오류: {dbd}~{draw} 사이에 거래일 "
                       f"{[x.isoformat() for x in between]} 이 남아 있다")

    # (11) ★휴장일 캘린더 커버리지가 우리가 실제로 계산한 구간을 전부 덮는가.
    #     덮지 못하면 '주말만 제외' 로 계산돼 ETA 가 조용히 낙관 편향된다.
    need = [p["period_from"], d["deadline_raw"], d["deadline_business_day"]]
    if d["pace_eta_date"]:
        need.append(d["pace_eta_date"])
    lo, hi = md.covers_range()
    if lo is None or hi is None:
        bad.append(f"{tag} 휴장일 캘린더(covers)가 없다 — 영업일 계산이 주말만 제외로 퇴화한다")
    else:
        out = [x for x in need if not (lo <= _d(x) <= hi)]
        if out:
            bad.append(f"{tag} 휴장일 미반영 구간 — ETA 낙관 편향: {out} 이 커버리지 "
                       f"[{lo} ~ {hi}] 밖이다. market_data.py holidays 로 캘린더를 확장하라.")

    # (8) 금액 단위 sanity — 평단이 그 기간 주가 밴드(±30%) 안에 있어야 원 단위다.
    px = [r["close"] for r in rows if r["close"]]
    if px and d["avg_cost"]:
        if not (min(px) * 0.7 <= d["avg_cost"] <= max(px) * 1.3):
            bad.append(f"{tag} 평균단가 {d['avg_cost']:,}원 이 기간 주가 밴드 "
                       f"[{min(px):,}, {max(px):,}] 밖 — 금액 단위(원/천원) 혼용 의심")

    return bad


# ================================================================ 교차검증(참고)
def crosscheck_reference(companies: dict[str, Any]) -> list[str]:
    """
    _ref/raoni_api_*.json 이 있으면 핵심 수치를 대조한다(경고만, 게이트 아님).
    ★ raoni 의 amountThousandKrw 는 '천원' 단위다 — ×1000 해서 원으로 맞춘다.
    """
    notes = []
    for tk, c in companies.items():
        f = ROOT / "_ref" / f"raoni_api_{tk}.json"
        if not f.exists():
            continue
        try:
            ref = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:                              # noqa: BLE001
            notes.append(f"[{tk}] 레퍼런스 파일 파싱 실패: {e}")
            continue
        a = ref.get("analysis") or {}
        d = c["derived"]
        if a.get("spentShares") and a["spentShares"] != d["cum_filled"]:
            notes.append(f"[{tk}] 누적체결 대조: 우리 {d['cum_filled']:,} vs "
                         f"raoni {a['spentShares']:,}")
        if a.get("spentKrw") and d["spent_krw"]:
            gap = abs(a["spentKrw"] - d["spent_krw"])
            if gap / d["spent_krw"] > 1e-6:
                notes.append(f"[{tk}] 누적금액 대조: 우리 {d['spent_krw']:,}원 vs "
                             f"raoni {a['spentKrw']:,}원 (차 {gap:,}원)")
        if a.get("avgPriceOverall") and d["avg_cost"] != a["avgPriceOverall"]:
            notes.append(f"[{tk}] 평균단가 대조: 우리 {d['avg_cost']:,} vs "
                         f"raoni {a['avgPriceOverall']:,}")

        # ---- ★일별 체결금액 전수 대조 (편차를 기록한다 — '차이 없음'도 기록한다)
        obs = {}
        for r in (ref.get("kind", {}).get("history") or []):
            fl = r.get("filled") or {}
            if fl.get("amountThousandKrw"):
                obs[r["date"]] = fl["amountThousandKrw"] * 1000   # 천원 → 원
        devs = []
        for row in c["daily"]:
            ex = obs.get(row["date"])
            if ex and row["amount_krw"]:
                devs.append((abs(row["amount_krw"] / ex - 1) * 100, row["date"],
                             row["amount_krw"] - ex))
        if devs:
            mx = max(devs)
            mae = sum(x[0] for x in devs) / len(devs)
            if mx[0] < 1e-6:
                notes.append(f"[{tk}] 일별 체결금액 {len(devs)}일 전수 대조: 원 단위까지 일치.")
            else:
                notes.append(
                    f"[{tk}] 일별 체결금액 {len(devs)}일 대조: 평균편차 {mae:.3f}%, "
                    f"최대편차 {mx[0]:.3f}% ({mx[1]}, {mx[2]:+,}원).")
    return notes


# ================================================================ 메인
def build(today: _dt.date | None = None, write: bool = True,
          snapshot: bool = True) -> dict[str, Any]:
    global ESTIMATOR_STATS, ESTIMATOR_ACCURACY_TEXT
    today = today or _dt.datetime.now(KST).date()
    sess = ps._session()

    # ---- 수집: ★회사 단위로 실패를 격리한다 ---------------------------------
    # 한 회사의 프로그램이 끝나거나 소스가 흔들려도, 진행 중인 나머지 회사의
    # 대시보드까지 같이 멈추면 안 된다.
    raws: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for tk in TICKERS:
        try:
            raws[tk] = collect_company(tk, today, sess)
        except Exception as e:                                  # noqa: BLE001
            failures[tk] = f"수집 실패 — {type(e).__name__}: {e}"

    # ---- 추정기 오차를 실측 대조로 계산 (assemble 의 경고문이 이 값을 쓴다) ----
    ESTIMATOR_STATS = {tk: estimator_backtest(tk, r["ohlcv"]) for tk, r in raws.items()}
    ESTIMATOR_ACCURACY_TEXT = _estimator_text(ESTIMATOR_STATS)

    companies: dict[str, Any] = {}
    for tk, raw in raws.items():
        try:
            companies[tk] = assemble(raw, today)
        except Exception as e:                                  # noqa: BLE001
            failures[tk] = f"조립 실패 — {type(e).__name__}: {e}"

    # ---- KIND decl 누계 스냅샷 적재 -----------------------------------------
    # KOSPI×직접취득은 일별 체결금액이 KIND 에 구조적으로 없다. decl 의 '체결금액누계'를
    # 매 영업일 18시 이후 찍어두면 그 다음날부터 전일 대비 차분으로 '정확한' 일별 금액이
    # 나온다(amount_source='kind_decl_snapshot'). 키는 (종목|프로그램시작일)/as_of 라
    # 하루에 여러 번 돌려도 같은 자리에 덮어쓴다.
    snap_note = None
    if snapshot:
        try:
            ps.snapshot_decl([(tk, ds.CORPS[tk]["isur_cd"], ds.CORPS[tk]["name"])
                              for tk in TICKERS], sess=sess, today=today)
            snap_note = "기록 완료 (data/kind_decl_snapshots.json)"
        except Exception as e:                                  # noqa: BLE001
            snap_note = f"실패: {e!r}"
    else:
        snap_note = "건너뜀 (--no-snapshot 또는 --date 백필)"

    # ---- 불변식 게이트: 위반한 회사만 떨어뜨리고, 전멸이면 파일을 쓰지 않는다 --
    violations: list[str] = []
    for tk in list(companies):
        bad = check_invariants(companies[tk])
        if bad:
            violations += bad
            failures[tk] = "불변식 위반 — " + " / ".join(bad)
            companies.pop(tk)
    if not companies:
        raise InvariantError(
            "모든 대상 회사의 빌드가 실패했다 — buyback.json 을 쓰지 않는다.\n  - %s"
            % "\n  - ".join(f"[{tk}] {msg}" for tk, msg in failures.items()))

    xref = crosscheck_reference(companies)

    hol = md.load_holidays()
    doc = {
        "generated_at": _dt.datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "sources": {
            "kind": "KIND 자기주식 취득/처분 (kind.krx.co.kr/corpgeneral/treasurystk.do) "
                    "— decl(신고·체결금액누계) / appl(신청) / trd·trddetail(체결)",
            "dart": "DART OpenAPI tsstkAqDecsn · stockTotqySttus · piicDecsn · list",
            "quote": "네이버 금융 siseJson (일봉 OHLCV)",
            "holidays": f"{hol.get('source')} (fetched {hol.get('fetched')}, "
                        f"{len(hol.get('holidays', []))}일)",
            "amount_unit": "모든 *_krw 필드는 원(KRW) 단위. "
                           "레퍼런스(raoni)의 amountThousandKrw 만 천원이라 비교 시 ×1000.",
        },
        "rules": {
            "appl_to_trade_date": "KIND 신청일 D → 매매일 next_business_day(D)",
            # 사람이 읽는 문장 — 푸터에 그대로 노출된다. 코드 식별자를 넣지 말 것.
            "pace_definition": f"체결이 집계된 가장 최근 최대 {PACE_WINDOW_BD}거래일의 평균 "
                               f"체결량으로 잔여 물량을 나눠 계산합니다. 체결이 0주인 날도 "
                               f"포함하고, 아직 집계되지 않은 당일은 제외합니다. "
                               f"표본이 {PACE_WINDOW_BD}일에 못 미치면 화면에 표본 일수를 함께 "
                               f"표시합니다.",
            "verdict_threshold": f"마감까지 여유가 {TIGHT_MARGIN_BD}거래일 이상이면 '기한 내 완료 "
                                 f"가능', 0~{TIGHT_MARGIN_BD - 1}거래일이면 '빠듯', 마감을 넘기면 "
                                 f"'기한 내 완료 불가'입니다. 필요 일평균이 1일 매수한도를 넘으면 "
                                 f"물리적으로 불가능한 것으로 봅니다.",
            "unused_fields": "elapsed_ratio_calendar_asof_today, all_avg 는 참고용이며 "
                             "UI 에 표시하지 않는다(기준일이 today 라 elapsed_ratio 와 다르다).",
            "business_days_left": "체결 미집계 첫 거래일 ~ 실질 마지막 매매일 (양끝 포함)",
            "verdict_codes": f"ok(여유>={TIGHT_MARGIN_BD}) / tight(0~{TIGHT_MARGIN_BD - 1}) / "
                             f"unlikely(음수) / impossible(필요 일평균>1일 한도) / ended(기간 종료)",
        },
        "invariants_passed": True,
        "decl_snapshot": snap_note,
        "crosscheck_reference": xref,
        "estimator_backtest": ESTIMATOR_STATS,
        "estimator_accuracy_text": ESTIMATOR_ACCURACY_TEXT,
        "build_failures": failures,
        "holiday_coverage": {"from": _iso(md.covers_range()[0]),
                             "to": _iso(md.covers_range()[1])},
        # 페이지가 '오늘(서울) vs 기준일' 을 거래일 단위로 대조하는 데 쓴다.
        "holidays_kr": hol.get("holidays", []),
        "warnings": ([f"[{t}] {w}" for t, c in companies.items() for w in c["warnings"]]
                     + [f"[{t}] {m}" for t, m in failures.items()]),
        "companies": companies,
    }

    if write:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        doc["_written_to"] = str(OUT_PATH)
    return doc


def _n(v, spec: str = ",", dash: str = "—") -> str:
    """None 안전 숫자 포맷 (콘솔 리포트가 None 에서 죽지 않도록)."""
    if v is None:
        return dash
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def _report(doc: dict[str, Any]) -> None:
    print("=" * 96)
    print(f"buyback.json  generated_at={doc['generated_at']}  as_of={doc['as_of']}")
    print("=" * 96)
    for tk, c in doc["companies"].items():
        p, d = c["program"], c["derived"]
        v = d["completion_verdict"]
        print(f"\n■ {c['meta']['name']} ({tk})   공시 {p['rcept_no']}  "
              f"{p['period_from']} ~ {p['period_to']}")
        print(f"  취득예정      {p['plan_shares']:>14,} 주 / {p['plan_amount_krw']:>18,} 원"
              f"   (발행주식총수의 {d['pct_of_shares_outstanding']}%)")
        print(f"  누적 체결     {d['cum_filled']:>14,} 주   진행률 "
              f"{_n((d['progress_ratio'] or 0)*100, '.2f')}%   "
              f"(잔여 {_n(d['remaining_shares'])}주)")
        print(f"  체결 금액     {_n(d['spent_krw'], '>18,')} 원   "
              f"평균단가 {_n(d['avg_cost'])} 원")
        print(f"  잔여 추정액   {_n(d['remaining_est_krw'], '>18,')} 원   "
              f"금액 여유 {_n(d['amount_headroom_krw'], '+,')} 원")
        print(f"  최근{d['pace_window_bd']}일 평균 {_n(d['recent5_avg'], '>10,.0f')} 주/일   "
              f"필요 일평균 {_n(d['required_daily_avg'], ',.0f')} 주/일   "
              f"남은 거래일 {d['business_days_left']}일")
        print(f"  pace_eta_date          {d['pace_eta_date']}  "
              f"({d['pace_eta_business_days']} 거래일 소요 예상)")
        print(f"  deadline_raw           {d['deadline_raw']}"
              f"{'' if d['deadline_is_business_day'] else '  ← 휴장일'}")
        print(f"  deadline_business_day  {d['deadline_business_day']}  "
              f"(마지막 신청일 {d['last_application_day']})")
        print(f"  판정  {v['code'].upper():10s} {v['label']} — {v['reason']}")
        print(f"  일정대비 {_n(d['on_schedule_gap_pp'], '+.2f')}%p  "
              f"(진행 {_n((d['progress_ratio'] or 0)*100, '.2f')}% vs 경과 "
              f"{_n((d['elapsed_ratio'] or 0)*100, '.2f')}%)")
        print(f"  daily 행 {len(c['daily'])}개 · 체결집계 {d['settled_days']}일 · "
              f"체결발생 {d['exec_days']}일")
        print(f"  {'date':<11}{'applied':>10}{'filled':>10}{'amount_krw':>18}"
              f"{'avg':>10}{'close':>10}  source")
        for r in c["daily"]:
            print(f"  {r['date']:<11}"
                  f"{(f'{r['applied']:,}' if r['applied'] else '-'):>10}"
                  f"{(f'{r['filled']:,}' if r['filled'] else '-'):>10}"
                  f"{(f'{r['amount_krw']:,}' if r['amount_krw'] else '-'):>18}"
                  f"{(f'{r['avg_price']:,}' if r['avg_price'] else '-'):>10}"
                  f"{(f'{r['close']:,}' if r['close'] else '-'):>10}"
                  f"  {r['amount_source'] or '-'}")
    if doc.get("crosscheck_reference"):
        print("\n[레퍼런스 대조 차이]")
        for n in doc["crosscheck_reference"]:
            print("  -", n)
    else:
        print("\n[레퍼런스 대조] 차이 없음 (누적체결·누적금액·평균단가 모두 일치)")
    print("\n[추정기 실측 대조] " + doc.get("estimator_accuracy_text", "-"))
    for tk, s in (doc.get("estimator_backtest") or {}).items():
        if s:
            print(f"  {tk}: n={s['n']}  MAE {s['mae_pct']}%  MAX {s['max_pct']}% ({s['max_date']})")
    print(f"\n[decl 스냅샷] {doc.get('decl_snapshot')}")
    print("  ※ 매 영업일 18시 이후 이 스크립트를 한 번 돌려두면, 다음날부터 일별 체결금액이"
          " 추정(estimated_hl2)에서 정확(kind_decl_snapshot)으로 승격된다.")
    print(f"\n[warnings] {len(doc['warnings'])}건")
    for w in doc["warnings"]:
        print("  -", w)
    if doc.get("_written_to"):
        print(f"\n→ {doc['_written_to']}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="자사주 대시보드 데이터 빌드")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않는다")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="KIND decl 누계 스냅샷을 남기지 않는다")
    ap.add_argument("--date", help="기준일 YYYY-MM-DD (기본: 오늘 KST)")
    args = ap.parse_args(argv)
    today = _d(args.date) if args.date else None
    # ★ --date 백필은 실시간 스냅샷 계열을 오염시키면 안 된다(스냅샷 키는 '지금' 값이다).
    snapshot = (not args.no_snapshot) and (today is None)
    try:
        doc = build(today=today, write=not args.dry_run, snapshot=snapshot)
    except InvariantError as e:
        print("불변식 게이트 실패 — buyback.json 미생성\n", e, file=sys.stderr)
        return 2
    _report(doc)
    if doc.get("build_failures"):
        # 일부 회사만 실패한 경우: 데이터는 썼으니 render 는 계속 진행시킨다(exit 0).
        print("\n[주의] 일부 회사 빌드 실패 — 나머지만 반영됐다.", file=sys.stderr)
        for tk, m in doc["build_failures"].items():
            print(f"  - [{tk}] {m}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
