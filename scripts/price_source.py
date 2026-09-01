# -*- coding: utf-8 -*-
"""
자사주 '체결금액 / 평균체결단가' 소스.

핵심 발견 (2026-09-01 실측)
--------------------------------------------------------------------------
1) KIND 자사주취득/처분 페이지에는 4개의 조회구분(searchGubun)이 있다.
     decl      -> searchDeclOfTreasuryStkAcqDisp / downloadDecl          (신고내역)
     appl      -> searchApplOfTreasuryStkAcqDisp / downloadAppl          (신청내역)
     trd       -> searchTrdOfTreasuryStkAcqDisp  / downloadTrd           (체결내역)
     trddetail -> searchTrdDetailOfTreasuryStkAcqDisp / downloadTrdDetail (체결상세)
   화면 탭은 3개뿐이고 trddetail 은 숨은 구분이다.
   ★ searchTrdDetailOfTreasuryStkAcqDisp(HTML 뷰)는 서버 내부에러(KRX 에러페이지)로 죽어 있다.
     파라미터 문제가 아니다 - marketType/trstkGubun/acqDispGubun/currentPageSize 48조합
     전부 동일하게 에러. 반면 downloadTrdDetail(엑셀)은 정상 동작한다.

2) ★★ 체결금액은 'trd(체결내역)'이 아니라 **'decl(신고내역)' 표의 마지막 열 '체결금액누계'** 에 있다.
     downloadDecl 컬럼:
       신고일|종목명|종목코드|자사주/취득·처분|기간|신고수량|체결수량누계|체결수량 비율누계|체결금액누계
     실측 2026-09-01:
       삼성전자   11,800,000주 / 3,054,461,236,000원  (평단 258,853원)
       SK하이닉스  5,200,000주 / 8,782,033,314,000원  (평단 1,688,853원)
     -> 레퍼런스 사이트(raoni)의 analysis.spentKrw 값과 원 단위까지 완전히 일치.
   단, 이 값은 '지금 시점의 프로그램 누계'라서 **일자별로 쪼개져 있지 않다.**

3) 일자별 체결금액은 trddetail 의 '체결금액누계' 열에 있는데,
   ★ 유가증권시장(KOSPI) + 자사주구분 '일반(직접)' 조합만 이 열이 통째로 비어 있다.
     2026-08 전체 2,383행 실측:
        (유,신탁)   578행 전부 값 있음
        (코,일반)   351행 전부 값 있음
        (코,신탁) 1,056행 전부 값 있음
        (유,일반)   391행 전부 공란   <-- 삼성전자·SK하이닉스가 여기 해당
     삼성 2025-07-09~10-08 (유,일반) 과거 종료 프로그램 116행도 전부 공란 -> 지연 아님, 구조적 결측.

4) 다른 경로 전부 확인 결과:
   - KRX 정보데이터시스템 [20005] '자사주취득/처분 내역(개별종목)'(menuId=MDC02020302),
     [20004] '자사주취득/처분종목 현황'(MDC02020301) -> "로그인 또는 회원가입이 필요합니다",
     통계 bld 직접 호출도 400 LOGOUT. (종목 finder bld 는 열려 있으나 통계는 막힘)
   - DART OpenAPI tsstkAqDecsn 등에는 취득 '결정'만 있고 일자별 체결단가 없음.
   - engkind.krx.co.kr 는 해당 경로 404.

=> 따라서 KOSPI 직접취득의 일자별 체결금액을 정확히 얻는 유일한 방법은
   **decl 누계를 매 영업일 스냅샷해서 전일 대비 차분**하는 것이다(레퍼런스 사이트도 동일 방식:
   응답에 collected 필드가 있고, 일별 금액 합이 KIND 누계와 3천원 오차로 일치).
   과거 구간 백필은 불가능하므로, 스냅샷이 없는 날은 (고가+저가)/2 가중치로 배분한 뒤
   총합을 KIND 누계에 정확히 맞추는 **추정치**를 쓰고 amount_exact=False 로 표시한다.

추정 오차 (레퍼런스 실측 일별 체결금액 대비 백테스트, 총액 정합 후):
   삼성전자  6일  MAE 0.38%  max 1.08%   (종가만 쓰면 MAE 1.41% / max 2.59%)
   SK하이닉스 8일  MAE 0.78%  max 1.60%   (종가만 쓰면 MAE 1.95% / max 4.05%)
   -> 반드시 (고가+저가)/2 가중치를 쓸 것. 총액·누적평단은 항상 정확(KIND 원본).
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from datetime import date, datetime, timedelta

import requests

# ---------------------------------------------------------------- 상수

KIND_URL = "https://kind.krx.co.kr/corpgeneral/treasurystk.do"
KIND_INIT = KIND_URL + "?method=loadInitPage"
NAVER_SISE = "https://api.finance.naver.com/siseJson.naver"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_PATH = os.path.join(os.path.dirname(_HERE), "data", "kind_decl_snapshots.json")
# 우리가 아직 돌지 않던 과거 구간을 메우는 KIND 누계 백필(출처·검증근거는 파일 안에 기록).
BACKFILL_PATH = os.path.join(os.path.dirname(_HERE), "data", "kind_decl_backfill.json")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAG_RE = re.compile(r"<[^>]+>")
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


# ---------------------------------------------------------------- 저수준 유틸

def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(KIND_INIT, timeout=20)
    return s


def _num(v):
    """'1,234' -> 1234 / '' 또는 '&nbsp;' -> None"""
    if v is None:
        return None
    v = v.replace("\xa0", " ").replace("&nbsp;", "").replace(",", "").replace("%", "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return None


def _cell(raw):
    t = _TAG_RE.sub("", raw)
    t = t.replace("&nbsp;", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _kind_download(sess, method, search_gubun, isur_cd, name,
                   from_date, to_date, ncols, retries=3):
    """KIND 엑셀 다운로드(EUC-KR HTML table)를 행 리스트로 파싱."""
    body = {
        "method": method, "searchGubun": search_gubun,
        "pageIndex": "1", "currentPageSize": "3000",
        "orderMode": "", "orderStat": "",
        "isurCd": isur_cd or "", "repIsuSrtCd": "", "repIsuCd": "", "corpName": "",
        "marketType": "all", "comAbbrv": name or "",
        "trstkGubun": "all", "acqDispGubun": "all",
        "fromDate": from_date, "toDate": to_date,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": KIND_INIT,
    }
    last = None
    for i in range(retries):
        try:
            r = sess.post(KIND_URL, data=body, headers=headers, timeout=60)
            txt = r.content.decode("euc-kr", "replace")
            rows = []
            for tr in _TR_RE.findall(txt):
                cells = [_cell(c) for c in _TD_RE.findall(tr)]
                if len(cells) == ncols and _DATE_RE.match(cells[0] or ""):
                    rows.append(cells)
            return rows
        except Exception as e:                    # 네트워크 튐 대비
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("KIND %s 실패: %r" % (method, last))


# ---------------------------------------------------------------- KIND 개별 조회

def fetch_decl(isur_cd, name, from_date, to_date, sess=None):
    """신고내역. ★체결금액누계(원)가 여기 있다."""
    sess = sess or _session()
    out = []
    for c in _kind_download(sess, "downloadDecl", "decl", isur_cd, name,
                            from_date, to_date, 9):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", c[4])
        out.append({
            "decl_date": c[0], "name": c[1], "code": c[2], "kind": c[3],
            "period_from": m.group(1) if m else None,
            "period_to": m.group(2) if m else None,
            "declared_qty": _num(c[5]),
            "cum_qty": _num(c[6]),
            "cum_ratio_pct": _num(c[7]),
            "cum_amount_krw": _num(c[8]),
        })
    return out


def fetch_trd(isur_cd, name, from_date, to_date, sess=None):
    """체결내역(일별 수량). 금액 없음."""
    sess = sess or _session()
    out = []
    for c in _kind_download(sess, "downloadTrd", "trd", isur_cd, name,
                            from_date, to_date, 7):
        out.append({
            "date": c[0], "name": c[1], "code": c[2], "kind": c[3],
            "applied_qty": _num(c[4]), "filled_qty": _num(c[5]),
            "fill_rate_pct": _num(c[6]),
        })
    return out


def fetch_trd_detail(isur_cd, name, from_date, to_date, sess=None):
    """체결상세(일별 누계). KOSPI 직접취득은 cum_amount_krw 가 None."""
    sess = sess or _session()
    out = []
    for c in _kind_download(sess, "downloadTrdDetail", "trddetail", isur_cd, name,
                            from_date, to_date, 10):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", c[5])
        out.append({
            "date": c[0], "name": c[1], "code": c[2], "kind": c[3], "side": c[4],
            "period_from": m.group(1) if m else None,
            "period_to": m.group(2) if m else None,
            "declared_qty": _num(c[6]),
            "cum_qty": _num(c[7]),
            "cum_ratio_pct": _num(c[8]),
            "cum_amount_krw": _num(c[9]),
        })
    return out


# ---------------------------------------------------------------- 시세

def fetch_ohlcv(code, from_date, to_date):
    """네이버 일별시세. {'YYYY-MM-DD': {open,high,low,close,volume}}"""
    p = {"symbol": code, "requestType": "1",
         "startTime": from_date.replace("-", ""), "endTime": to_date.replace("-", ""),
         "timeframe": "day"}
    r = requests.get(NAVER_SISE, params=p,
                     headers={"User-Agent": UA, "Referer": "https://finance.naver.com/"},
                     timeout=25)
    arr = ast.literal_eval(r.text.strip().replace("'", '"'))
    out = {}
    for row in arr[1:]:
        d = row[0]
        out["%s-%s-%s" % (d[:4], d[4:6], d[6:8])] = {
            "open": row[1], "high": row[2], "low": row[3],
            "close": row[4], "volume": row[5],
        }
    return out


# ---------------------------------------------------------------- 스냅샷 저장소
# decl 의 '체결금액누계'는 지금 시점 값이라 일자별로 못 쪼갠다.
# 매 영업일 18시 이후 snapshot_decl() 를 돌려두면 다음날부터 차분으로 '정확한' 일별 금액이 나온다.

def load_snapshots(path=SNAPSHOT_PATH):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_backfill(path=BACKFILL_PATH):
    """
    과거 구간 백필(스냅샷과 같은 모양). 실측 스냅샷이 있으면 그쪽이 항상 우선한다.
    반환: {"<code>|<program_from>": {as_of: {cum_qty, cum_amount_krw, ...}}}
    """
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return (json.load(f) or {}).get("series", {})


def snapshot_decl(targets, path=SNAPSHOT_PATH, sess=None, today=None):
    """
    targets: [(code, isur_cd, name), ...]
    today  : 기준일(date | 'YYYY-MM-DD' | None=시스템 오늘). ★ 호출자(build)의 KST 기준일을
             그대로 받아 시스템 로컬 날짜와 어긋나지 않게 한다.
    오늘 시점의 decl 누계를 '마지막 체결처리일(as_of)' 키로 저장.
    키: "<code>|<program_from>" -> {as_of: {cum_qty, cum_amount_krw, captured_at}}
    """
    sess = sess or _session()
    store = load_snapshots(path)
    base = today if isinstance(today, date) else (
        datetime.strptime(today, "%Y-%m-%d").date() if today else date.today())
    today = base.isoformat()
    start = (base - timedelta(days=400)).isoformat()
    for code, isur_cd, name in targets:
        decls = [d for d in fetch_decl(isur_cd, name, start, today, sess)
                 if d["code"] == code and "취득" in d["kind"]]
        det = [d for d in fetch_trd_detail(isur_cd, name, start, today, sess)
               if d["code"] == code and "취득" in d["side"]]
        for d in decls:
            if d["cum_amount_krw"] is None:
                continue
            same = [x["date"] for x in det if x["period_from"] == d["period_from"]]
            as_of = max(same) if same else today
            key = "%s|%s" % (code, d["period_from"])
            store.setdefault(key, {})[as_of] = {
                "cum_qty": d["cum_qty"],
                "cum_amount_krw": d["cum_amount_krw"],
                "captured_at": datetime.now().isoformat(timespec="seconds"),
            }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1, sort_keys=True)
    return store


# ---------------------------------------------------------------- 검증

def _price_band_bad_dates(exact, qty_by_date, ohlc, band=0.15):
    """
    차분으로 얻은 일별 체결금액이 '그날 저가~고가 ±band' 안의 단가를 만드는지 검사.
    반환: (밴드를 벗어난 날짜 set, 실제로 검사된 날짜 수)

    두 가지 오염 원인이 있고 대응이 다르다:
      - KIND trddetail 의 '누계의 누계' 이중가산  → 계열 전체가 오염. 통째로 버린다.
      - 스냅샷을 하루 거른 구간(차분이 2일치로 뭉침) → 그 날짜만 오염. 그 날만 버린다.
    """
    bad, checked = set(), 0
    for d, amt in exact.items():
        q = qty_by_date.get(d)
        b = ohlc.get(d)
        if not q or not b or amt is None:
            continue
        checked += 1
        p = amt / q
        if not (b["low"] * (1 - band) <= p <= b["high"] * (1 + band)):
            bad.add(d)
    return bad, checked


def _price_band_ok(exact, qty_by_date, ohlc, band=0.15):
    """하위호환용 boolean 래퍼 (검사된 날이 있고 전부 밴드 안이면 True)."""
    bad, checked = _price_band_bad_dates(exact, qty_by_date, ohlc, band)
    return checked > 0 and not bad


# ---------------------------------------------------------------- 메인

def fetch_exec_detail(code, isur_cd, name, from_date, to_date,
                      side="취득", snapshot_path=SNAPSHOT_PATH, sess=None):
    """
    일별 자사주 체결 내역.

    반환: [{date, quantity, amount_krw, avg_price, ...}, ...]  (날짜 오름차순)
      date                    매매일 (YYYY-MM-DD)
      quantity                당일 체결수량 (주)          <- KIND trd, 정확
      amount_krw              당일 체결금액 (원)
      avg_price               당일 평균체결단가 (원) = amount_krw / quantity
      amount_exact            True면 KRX 공시값(또는 스냅샷 차분), False면 추정치
      amount_source           'kind_trddetail'      KIND 체결상세 누계 차분 (정확)
                              'kind_decl_snapshot'  우리가 매 영업일 찍은 decl 누계 차분 (정확)
                              'kind_decl_backfill'  가동 전 구간 백필 누계 차분 (정확, 출처는
                                                    data/kind_decl_backfill.json 에 기록)
                              'estimated_hl2'       (고가+저가)/2 가중 배분 추정
                              'unavailable'         금액 확보 실패
      applied_quantity        당일 신청수량
      fill_rate_pct           체결율(%)
      cumulative_qty          누적 체결수량
      declared_qty            신고(취득예정) 수량
      program_from / program_to
      program_cum_qty         프로그램 누적 체결수량 (KIND decl 원본, 정확)
      program_cum_amount_krw  프로그램 누적 체결금액 (KIND decl 원본, 정확)
      close / high / low / market_volume  그날 시세(참고)
    """
    sess = sess or _session()
    lookback = (datetime.strptime(from_date, "%Y-%m-%d").date() - timedelta(days=400)).isoformat()

    # 1) 신고(프로그램) 목록 - 요청 구간과 겹치는 것만
    decls = [d for d in fetch_decl(isur_cd, name, lookback, to_date, sess)
             if d["code"] == code and side in d["kind"] and d["period_from"]]
    programs = [d for d in decls
                if d["period_from"] <= to_date and (d["period_to"] or "9999-12-31") >= from_date]
    if not programs:
        return []

    snaps = load_snapshots(snapshot_path)
    backfill = load_backfill()
    today = date.today().isoformat()
    rows_out = []

    for prog in programs:
        p_from = prog["period_from"]
        p_to = min(prog["period_to"] or today, today)
        # trddetail 의 첫 행(신고일, 누계 0)을 반드시 포함시키려고 앞쪽을 조금 넉넉히 잡는다
        d_from = (datetime.strptime(p_from, "%Y-%m-%d").date() - timedelta(days=14)).isoformat()

        trd = [t for t in fetch_trd(isur_cd, name, d_from, p_to, sess)
               if t["code"] == code and side in t["kind"] and t["date"] >= p_from]
        trd.sort(key=lambda x: x["date"])

        det_rows = sorted(
            [d for d in fetch_trd_detail(isur_cd, name, d_from, p_to, sess)
             if d["code"] == code and side in d["side"] and d["period_from"] == p_from],
            key=lambda x: x["date"])
        det = {d["date"]: d for d in det_rows}

        # ---- 일별 체결수량: trddetail 의 누계 차분이 '프로그램 단위'로 정확하다.
        #      (trd 탭은 같은 날 여러 신고건이 겹치면 합산돼 나와서 프로그램 귀속이 안 된다)
        qty_by_date = {}
        if det_rows:
            prev = det_rows[0]["cum_qty"] or 0
            for d in det_rows[1:]:
                cur = d["cum_qty"] or 0
                if cur - prev > 0:
                    qty_by_date[d["date"]] = cur - prev
                prev = cur
        covered = sum(qty_by_date.values())

        # trddetail 이 아직 못 따라온 최근 영업일은 trd 로 보충
        missing = (prog["cum_qty"] or 0) - covered
        last_det = det_rows[-1]["date"] if det_rows else p_from
        if missing > 0:
            tail = [t for t in trd if t["date"] > last_det and (t["filled_qty"] or 0) > 0]
            if sum(t["filled_qty"] for t in tail) == missing:
                for t in tail:
                    qty_by_date[t["date"]] = t["filled_qty"]
                covered += missing
        if not qty_by_date:                        # trddetail 자체가 없으면 trd 로 대체
            qty_by_date = {t["date"]: t["filled_qty"] for t in trd if (t["filled_qty"] or 0) > 0}
            covered = sum(qty_by_date.values())

        # ---- ★불변식: 일별 체결수량 합 == decl 체결수량누계
        qty_reconciled = (prog["cum_qty"] is None) or (covered == prog["cum_qty"])
        if not qty_reconciled and len(programs) == 1:
            raise AssertionError(
                "불변식 위반: 일별 체결수량 합 %s != decl 체결수량누계 %s (%s %s~)"
                % (covered, prog["cum_qty"], code, p_from))

        ohlc = fetch_ohlcv(code, p_from, p_to)
        trd_by_date = {}
        for t in trd:
            trd_by_date.setdefault(t["date"], []).append(t)

        # ---- 정확한 일별 금액 확보 시도
        exact, source = {}, {}
        pkey = "%s|%s" % (code, p_from)
        cum_series = [(d, det[d]["cum_amount_krw"], "kind_trddetail") for d in sorted(det)
                      if det[d]["cum_amount_krw"] is not None]
        # 실측 스냅샷 + 과거 백필을 병합한다. 같은 날짜면 **실측 스냅샷이 항상 이긴다.**
        merged = {}
        for as_of, v in (backfill.get(pkey) or {}).items():
            merged[as_of] = (v.get("cum_amount_krw"), "kind_decl_backfill")
        for as_of, v in (snaps.get(pkey) or {}).items():
            merged[as_of] = (v.get("cum_amount_krw"), "kind_decl_snapshot")
        snap_series = [(as_of, merged[as_of][0], merged[as_of][1])
                       for as_of in sorted(merged)]

        use_trddetail = len(cum_series) > 1
        series = cum_series if use_trddetail else snap_series
        if len(series) > 1:
            prev_v = series[0][1]
            for d, v, tag in series[1:]:
                if v is not None and prev_v is not None:
                    exact[d] = v - prev_v
                    source[d] = tag
                prev_v = v if v is not None else prev_v

        # ---- ★불변식 게이트: 차분으로 나온 '일별 단가'가 그날 저가~고가 밴드 안이어야 한다.
        # KIND trddetail 의 체결금액누계는 일부 신고건(실측: 삼성전자 스톡옵션 프로그램)에서
        # '누계의 누계'로 이중가산돼 나온다. 그런 계열은 통째로 버리고 추정 경로로 넘긴다.
        if exact:
            bad, checked = _price_band_bad_dates(exact, qty_by_date, ohlc)
            if checked == 0 or (bad and use_trddetail):
                exact, source = {}, {}     # trddetail 이중가산 → 계열 전체 폐기
            else:
                for d in bad:              # 스냅샷 누락 등 → 그 날짜만 폐기(추정으로 대체)
                    exact.pop(d, None)
                    source.pop(d, None)

        # ---- 나머지는 (고가+저가)/2 가중치로 배분하고 총액을 KIND 누계에 정확히 맞춤
        # 겹치는 신고건 때문에 일별 수량이 누계를 다 못 덮으면(qty_reconciled=False),
        # 덮은 수량 비율만큼만 금액을 배분한다(안 덮인 물량도 같은 평단이라고 가정).
        total = prog["cum_amount_krw"]
        if total is not None and prog["cum_qty"] and covered != prog["cum_qty"]:
            total = total * covered / float(prog["cum_qty"])
        # exact 에는 qty_by_date 밖의 날짜가 섞이면 안 된다(차분 baseline 등).
        exact = {d: v for d, v in exact.items() if d in qty_by_date}
        source = {d: v for d, v in source.items() if d in exact}

        unknown = [d for d in qty_by_date if d not in exact]
        if total is not None and unknown:
            residual = total - sum(exact.values())
            weights = {}
            for d in unknown:
                b = ohlc.get(d)
                if b:
                    weights[d] = qty_by_date[d] * (b["high"] + b["low"]) / 2.0
            wsum = sum(weights.values())
            if wsum > 0 and residual > 0:
                k = residual / wsum
                alloc = {d: int(round(w * k)) for d, w in weights.items()}
                # ★합계 불변식: 일자별 반올림 잔차를 '최대 수량일'에 흡수시켜
                #   sum(배분액) == residual 을 강제한다(1원 어긋남 방지).
                drift = int(round(residual)) - sum(alloc.values())
                if alloc and drift:
                    anchor = max(alloc, key=lambda d: (qty_by_date.get(d, 0), d))
                    alloc[anchor] += drift
                for d, v in alloc.items():
                    exact[d] = v
                    source[d] = "estimated_hl2"

        for d in sorted(qty_by_date):
            q = qty_by_date[d]
            amt = exact.get(d)
            b = ohlc.get(d, {})
            cand = trd_by_date.get(d, [])
            t = next((x for x in cand if x["filled_qty"] == q), cand[0] if cand else {})
            rows_out.append({
                "date": d,
                "code": code,
                "quantity": q,
                "amount_krw": int(round(amt)) if amt is not None else None,
                "avg_price": (amt / q) if (amt is not None and q) else None,
                "amount_exact": source.get(d) in ("kind_trddetail", "kind_decl_snapshot",
                                                  "kind_decl_backfill"),
                "amount_source": source.get(d) or "unavailable",
                "applied_quantity": t.get("applied_qty"),
                "fill_rate_pct": t.get("fill_rate_pct"),
                "cumulative_qty": det.get(d, {}).get("cum_qty"),
                "declared_qty": prog["declared_qty"],
                "program_from": p_from,
                "program_to": prog["period_to"],
                "program_cum_qty": prog["cum_qty"],
                "program_cum_amount_krw": prog["cum_amount_krw"],
                "qty_reconciled": qty_reconciled,
                "close": b.get("close"), "high": b.get("high"), "low": b.get("low"),
                "market_volume": b.get("volume"),
            })

    rows_out = [r for r in rows_out if from_date <= r["date"] <= to_date]
    rows_out.sort(key=lambda r: r["date"])
    return rows_out


# ---------------------------------------------------------------- 데모

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    TARGETS = [("005930", "00593", "삼성전자"), ("000660", "00066", "SK하이닉스")]
    F, T = "2026-08-01", "2026-09-01"
    sess = _session()
    for code, isur, nm in TARGETS:
        rows = fetch_exec_detail(code, isur, nm, F, T, sess=sess)
        print("=" * 108)
        print("%s (%s)  %s ~ %s   rows=%d" % (nm, code, F, T, len(rows)))
        if not rows:
            continue
        p = rows[0]
        print("  프로그램 %s ~ %s / 신고 %s주 / KIND 누계 %s주 · %s원 (평단 %s원)"
              % (p["program_from"], p["program_to"], format(p["declared_qty"], ","),
                 format(p["program_cum_qty"], ","), format(p["program_cum_amount_krw"], ","),
                 format(p["program_cum_amount_krw"] / p["program_cum_qty"], ",.0f")))
        print("  %-11s %10s %20s %11s %9s %9s %6s  %s"
              % ("date", "qty", "amount_krw", "avg_price", "close", "vs close", "fill%", "source"))
        for r in rows:
            vs = ("%+.2f%%" % ((r["avg_price"] / r["close"] - 1) * 100)) if (r["avg_price"] and r["close"]) else "-"
            print("  %-11s %10s %20s %11s %9s %9s %6s  %s"
                  % (r["date"], format(r["quantity"], ","),
                     format(r["amount_krw"], ",") if r["amount_krw"] else "-",
                     format(r["avg_price"], ",.0f") if r["avg_price"] else "-",
                     format(r["close"], ",") if r["close"] else "-", vs,
                     r["fill_rate_pct"], r["amount_source"]))
        tq = sum(r["quantity"] for r in rows)
        ta = sum(r["amount_krw"] or 0 for r in rows)
        print("  합계 %s주 / %s원 / 평단 %s원  (KIND 누계와 일치 여부: %s)"
              % (format(tq, ","), format(ta, ","), format(ta / tq, ",.0f") if tq else "-",
                 "OK" if abs(ta - (p["program_cum_amount_krw"] or 0)) <= len(rows) else "DIFF"))
