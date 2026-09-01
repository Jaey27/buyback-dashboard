# 정찰 결과 (메인 세션에서 이미 확정한 사실 — 재조사 불필요)

오늘 날짜: 2026-09-01 (KST). 작업 루트: `C:\Users\pjy09\buyback-dashboard`

## 1. 대상
| 회사 | 종목코드 | DART corp_code | KIND isurCd |
|---|---|---|---|
| 삼성전자 | 005930 | 00126380 | 00593 |
| SK하이닉스 | 000660 | 00164779 | 00066 |

## 2. DART OpenAPI (동작 확인됨)
- 인증키: `<REDACTED — config.json / .env 에서만 읽는다>` (파일 `C:\Users\pjy09\_stock_tools\_dart\config.json`)
- 자기주식 취득 결정: `https://opendart.fss.or.kr/api/tsstkAqDecsn.json?crtfc_key=KEY&corp_code=..&bgn_de=YYYYMMDD&end_de=YYYYMMDD`
- 자기주식 처분 결정: `https://opendart.fss.or.kr/api/tsstkDpDecsn.json` (동일 파라미터)
- 신탁계약: `tsstkAqTrctrCnsDecsn.json`
- 주요 필드: `aqpln_stk_ostk`(취득예정 보통주), `aqpln_prc_ostk`(취득예정 금액), `aqexpd_bgd`/`aqexpd_edd`(취득기간, "2026년 08월 20일" 포맷), `aq_mth`(취득방법), `cs_iv_bk`(위탁증권사), `d1_prodlm_ostk`(1일 매수주문 한도), `aq_dd`(이사회결의일), `rcept_no`

### 현재 진행 중인 프로그램 (확인됨)
- **삼성전자**: rcept 20260821000616 / 결의 2026-08-21 / **53,285,968주 · 14,999,999,992,000원(15조)** / 기간 **2026-08-24 ~ 2026-11-21** / 유가증권시장을 통한 장내 매수 / 1일한도 7,321,653주
- **SK하이닉스**: rcept 20260819000254 / 결의 2026-08-19 / **24,070,000주 · 40,004,340,000,000원(40조)** / 기간 **2026-08-20 ~ 2026-11-19** / 장내매수 / SK증권 / 1일한도 2,407,000주
- (삼성전자는 2025~2026 사이 종료된 과거 프로그램 5건이 더 있음 — 현재 진행 건만 메인, 과거는 참고)

## 3. KIND 자기주식 매매 신청/체결 (동작 확인됨) ★핵심
POST `https://kind.krx.co.kr/corpgeneral/treasurystk.do`
헤더: `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`, `X-Requested-With: XMLHttpRequest`,
`Referer: https://kind.krx.co.kr/corpgeneral/treasurystk.do?method=loadInitPage`, 일반 브라우저 UA

폼 파라미터(전부 필요):
```
method, searchGubun, pageIndex, currentPageSize(최대100), orderMode, orderStat,
isurCd, repIsuSrtCd, repIsuCd, corpName, marketType(all), comAbbrv(회사명),
trstkGubun(all), acqDispGubun(all), fromDate(YYYY-MM-DD), toDate(YYYY-MM-DD)
```
`searchGubun` → `method` 매핑:
- `decl` → `searchDeclOfTreasuryStkAcqDisp` (신고내역)
- `appl` → `searchApplOfTreasuryStkAcqDisp` (신청내역)
- `trd`  → `searchTrdOfTreasuryStkAcqDisp` (체결내역)
- `trddetail` → `searchTrdDetailOfTreasuryStkAcqDisp` (체결상세/누적) ← **현재 에러페이지 반환. 파라미터 미상. 조사 필요**

`isurCd`를 넣으면 해당 회사만 필터됨(넣지 않으면 전체 985건/10페이지). 응답은 HTML 조각.

### 컬럼 스키마 (실측)
- appl: `신청일 | 종목명 | 자사주구분(직접/신탁) | 취득처분구분 | 신고수량 | 신청가능수량`
- trd: `매매일 | 종목명 | 직접·신탁 / 취득·처분 | 신청수량 | 당일체결수량 | 체결율(%)`
- 종목명 셀에 `companysummary_open('00593')` 형태로 isurCd가 들어있음
- 페이징: `전체 <em>985</em>건 : <strong>1</strong>/10`

### ★★ 날짜 정렬 규칙 (실측으로 확정)
**신청일 = 매매일의 직전 영업일.** 자기주식 매매신청서는 매매일 전 영업일 장 종료 후 제출.
```
SK하이닉스  appl 08-19(650k) → trd 08-20(650k)
            appl 08-31(650k) → trd 09-01 (오늘, 체결 미집계)
삼성전자    appl 08-21(1.8M) → trd 08-24(1.8M)
            appl 08-31(2.0M) → trd 09-01 (오늘, 체결 미집계)
```
따라서 대시보드에서 "오늘 신청량"은 **전 영업일 appl 행**을 가져와야 한다.

### 실측 원본 데이터 (2026-08-01~09-01)
삼성전자 appl: 08-21/1,800,000/53,285,968 · 08-24~08-31 매일 2,000,000 (신청가능 51,485,968→41,485,968)
삼성전자 trd : 08-24/1,800,000 · 08-25~08-31 매일 2,000,000, 전부 체결율 100
SK하이닉스 appl: 08-19~08-31 매일 650,000 (신청가능 24,070,000→18,870,000)
SK하이닉스 trd : 08-20~08-31 매일 650,000, 전부 체결율 100

**불변식**: `신청가능수량[D] = 취득예정수량 − (D 이전까지의 누적 신청수량)`. 즉 그 날 신청 전 잔량.

## 4. 시세 (동작 확인됨)
`https://api.finance.naver.com/siseJson.naver?symbol=005930&requestType=1&startTime=20260820&endTime=20260901&timeframe=day`
→ 파이썬 리터럴 유사 배열: `[['날짜','시가','고가','저가','종가','거래량','외국인소진율'], ["20260820", 257000, ...], ...]`

## 5. 레퍼런스(raoni.xyz/buyback) — 역설계 대상
- 페이지 원본: `_ref/raoni_buyback_page.html` (인라인 <style> 13KB + Chart.js 사용)
- 백엔드 응답 스키마 샘플: `_ref/raoni_api_005930.json`, `_ref/raoni_api_000660.json`
  (그쪽 서버 API. 우리 파이프라인은 이걸 쓰지 않고 **KIND/DART/네이버에서 직접** 만든다. 숫자 교차검증용으로만 참고)
- raoni는 체결금액(`amountThousandKrw`)과 평균체결단가(`avgPrice`)를 가지고 있음. **이 소스를 우리도 찾아야 함** (KIND trddetail 또는 다른 경로)
- 디자인 토큰: `--hl-teal:#97FCE4; --hl-teal-dim:#50D2C1; --bg-0:#061E20; --surface:rgba(15,53,55,.55); --text:#E8FFFA; --text-dim:#7FA8A4; --text-muted:#4F7773; --up:#F87171; --down:#60A5FA; --warn:#FBBF24`
  배경 `radial-gradient(ellipse at top,#0F3537 0%,#061E20 60%,#03100F 100%)`

## 6. 사용자 요구 추가사항
"완료 예상"에 **(a) 현재 페이스 기준 완료 예상일**과 **(b) 공시 기준 마감일(취득기간 종료일)** 둘 다 표시.
→ 한국 증시 휴장일(공휴일) 캘린더가 필요. raoni는 "주말만 제외, 공휴일 미반영"이라고 스스로 한계를 명시함. **우리는 공휴일까지 반영해서 개선한다.**
참고: 삼성 마감일 2026-11-21은 **토요일** → 실질 마지막 매매일은 2026-11-20(금).
