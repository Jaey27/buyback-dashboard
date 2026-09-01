# 자사주 매입 진행률 대시보드 (삼성전자 · SK하이닉스)

KRX **KIND**(자기주식 신고/신청/체결) + **DART**(자기주식 취득결정·발행주식총수) + **네이버 금융**(일봉)을
직접 수집해 `dashboard.html` 한 장으로 굽는다. 외부 요청 0건의 자기완결 HTML이라 브라우저로 열기만 하면 된다.

---

## 1. 매일 갱신 (핵심)

```bat
run_daily.bat
```

바탕화면 바로가기 두 개를 만들어 두었다.

- **`자사주 대시보드 갱신.lnk`** → `run_daily.bat` 실행
- **`자사주 대시보드 열기.lnk`** → `dashboard.html` 열기

> `run_daily.bat` / `update.bat` 은 **ASCII 전용**으로 유지할 것. cmd.exe 는 배치 파일을
> 바이트 오프셋으로 다시 읽기 때문에, `chcp 65001` 뒤에 한글이 있으면 블록 파싱이 깨진다
> (`if errorlevel 1 (...)` 안이 특히 잘 깨진다). 한글 메시지는 Python 쪽에서 출력한다.

내부 동작:

| 단계 | 명령 | 실패 시 |
|---|---|---|
| 1 | `python scripts\build_data.py` | **exit 1 → render 를 건너뛴다** |
| 2 | `python scripts\render.py --max-age-days 4` | exit 1 |

> ★ 1단계 errorlevel 가드가 반드시 필요하다. 없으면 수집이 실패해도 2단계가 **낡은 `buyback.json`**
> 을 그대로 읽어 겉보기 멀쩡한 페이지를 찍어낸다. 이 경우 페이지는 현재 값이 아닌데도 현재 값처럼 보인다.

### 왜 '매 영업일' 실행이 정확도의 전제인가

유가증권시장 × 직접취득 조합은 KIND `trddetail` 의 **체결금액누계 칸이 구조적으로 공란**이다.
따라서 일별 체결금액을 정확히 얻는 유일한 방법은 **`decl` 의 체결금액누계를 매 영업일 스냅샷해
전일 대비 차분**하는 것이다(`data/kind_decl_snapshots.json`).

- 실행한 날 → `amount_source = kind_decl_snapshot` (**정확**)
- 거른 날 → 그 날짜만 `estimated_hl2` (고가+저가)/2 가중 배분 **추정치**로 떨어진다
  (전 기간이 아니라 **그 날짜만** 떨어지도록 고쳐 두었다)
- 파이프라인 가동 이전 구간(2026-08-20~08-28)은 `data/kind_decl_backfill.json` 로 메웠고,
  프로그램 누계를 KIND 원본과 원 단위까지 대조해 두었다.

추정기의 실제 오차는 **매 빌드에서 실측 대조로 다시 계산**한다(하드코딩 아님).
현재 값: 005930 MAE 0.383% / MAX 1.082%, 000660 MAE 0.784% / MAX 1.596%.

---

## 2. 자동 실행 등록 (Windows 작업 스케줄러)

KIND 는 **당일 체결분을 18시 이후** 집계한다. 18시 이전에 돌리면 전일까지만 확정된다.
→ **평일 18:30 KST** 를 권장한다.

관리자 PowerShell/명령 프롬프트에서 한 번만:

```bat
schtasks /Create /TN "BuybackDashboard" /TR "\"C:\Users\pjy09\buyback-dashboard\run_daily.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:30 /F
```

확인 / 즉시 실행 / 삭제:

```bat
schtasks /Query  /TN "BuybackDashboard" /V /FO LIST
schtasks /Run    /TN "BuybackDashboard"
schtasks /Delete /TN "BuybackDashboard" /F
```

> 공휴일에도 실행되지만 KIND 에 새 데이터가 없을 뿐이라 무해하다.
> 실행을 며칠 걸러도 그 날짜들만 추정치로 떨어지고 나머지는 그대로 정확하다.

---

## 3. 설치

```bat
pip install -r requirements.txt
```

DART OpenAPI 인증키는 **소스에 넣지 않는다.** 아래 중 하나면 된다(위에서부터 우선):

1. `C:\Users\pjy09\_stock_tools\_dart\config.json` 의 `crtfc_key` ← 현재 이 경로를 쓰고 있다
2. 프로젝트 루트 `.env` 의 `DART_API_KEY=...` (`.env.example` 참고, `.gitignore` 에 포함됨)
3. 환경변수 `DART_API_KEY`

셋 다 없으면 첫 API 호출에서 무엇을 설정해야 하는지 알려주는 예외가 난다.

---

## 4. 파일 구조

```
buyback-dashboard/
├── run_daily.bat              # ★ 매일 실행하는 단일 엔트리포인트
├── update.bat                 # run_daily.bat 별칭(수동 갱신용)
├── requirements.txt
├── .env.example / .gitignore
├── publish.sh                 # 성공한 실행만 GitHub 로 commit + push (DEPLOY.md)
├── dashboard.html             # 로컬 산출물 (자기완결, 외부 요청 0건, git 제외)
├── docs/                      # ★ GitHub Pages 가 서빙하는 공개 페이지
│   ├── index.html             #   dashboard.html 과 같은 내용 (갱신 안내문만 다름)
│   └── .nojekyll
├── .github/workflows/update.yml  # Actions 백업 (수동 버튼 전용 - 이유는 DEPLOY.md §G-4)
├── scripts/
│   ├── build_data.py          # 수집 → 불변식 게이트 → data/buyback.json
│   ├── render.py              # buyback.json → dashboard.html
│   ├── dart_source.py         # DART OpenAPI
│   ├── price_source.py        # KIND 신고/신청/체결 + 일별 체결금액
│   └── market_data.py         # 네이버 일봉 + KRX 휴장일 캘린더 + 영업일 계산
├── data/
│   ├── buyback.json           # 렌더 입력 (build 산출물)
│   ├── holidays_kr.json       # KRX 휴장일 + short_sessions(수능일 등 단축일)
│   ├── kind_decl_snapshots.json  # 매 실행마다 누적되는 실측 스냅샷
│   └── kind_decl_backfill.json   # 가동 전 구간 백필(출처·검증근거 파일 내 기록)
└── _ref/                      # 정찰 결과·레퍼런스 (파이프라인 입력 아님, 검증용)
```

---

## 4-1. 공개 링크 (GitHub Pages)

`render.py` 는 한 번 실행에 **`dashboard.html`(로컬)** 과 **`docs/index.html`(공개)** 을
같이 굽는다. 내용은 같고 stale 배너의 안내 문구 한 줄만 다르다(로컬은 "스크립트를 실행하세요",
공개 페이지는 "평일 18:30 자동 갱신됩니다"). 바탕화면 바로가기가 가리키는
`dashboard.html` 경로는 그대로다.

`run_daily.sh` 는 수집·렌더가 모두 성공한 뒤에만 `publish.sh` 를 불러 커밋+push 한다
(값이 실제로 바뀌었을 때만 커밋한다 — 매 실행 갱신되는 `generated_at`·`captured_at` 만
다른 경우는 커밋하지 않는다. 판정 방식은 DEPLOY.md §C-4). 리포 생성·Pages 켜기·인증·커밋 대상 판단·공개 여부 검토는
**[DEPLOY.md](DEPLOY.md)** 에 전부 정리해 두었다.

```
https://<아이디>.github.io/buyback-dashboard/
```

> `docs/index.html` 은 커밋하지만 `dashboard.html` 은 커밋하지 않는다(같은 내용을 매일 두 벌
> 쌓지 않기 위해서다). clone 직후에는 `dashboard.html` 이 없고, `run_daily` 를 한 번 돌리면 생긴다.

---

## 5. 유지보수 시 주의

### 휴장일 캘린더 커버리지
`data/holidays_kr.json` 은 현재 **2025-01-01 ~ 2027-12-31** 만 덮는다.
커버리지 밖 날짜로 영업일을 계산하면 공휴일이 통째로 빠져 ETA 가 조용히 낙관 편향되므로,
`market_data` 가 그 즉시 `HolidayCoverageError` 를 던지고 빌드 게이트도 이를 잡는다.
연도를 늘리려면:

```bat
python scripts\market_data.py holidays 2025 2026 2027 2028
```

(`short_sessions` 는 수동 관리 항목이며 재수집해도 보존된다.)

### 종목 추가·교체
`scripts/build_data.py` 의 `TICKERS` 와 `scripts/dart_source.py` 의 `CORPS` 만 고치면 된다.
페이지의 종목 목록은 `Object.keys(D.companies)` 로 데이터에서 유도하므로 렌더 쪽은 손댈 필요가 없다.
(회사가 1곳이면 '비교' 탭이 자동으로 사라진다.)

### 프로그램이 끝났을 때
진행 중 프로그램이 없으면 예외로 죽지 않고 **마지막으로 종료된 프로그램의 최종 결산**을 보여준다.
회사 단위로 실패가 격리되므로 한 종목의 프로그램이 끝나도 나머지 종목의 갱신은 계속된다.
(모든 종목이 실패할 때만 `exit 2` 로 `buyback.json` 을 쓰지 않는다.)

### 불변식 게이트
`build_data.check_invariants()` 를 통과하지 못한 회사는 결과에서 제외되고 실패로 기록된다.
수량·금액 항등식뿐 아니라 **영업일 항등식**(`elapsed + left == total`,
`margin == left − eta`), **마감일 보정 정합성**, **휴장일 커버리지**까지 검사한다.

---

## 6. 데이터 해석 메모

- **신청일 = 매매일의 직전 영업일.** 자기주식 매매신청서는 매매일 전 영업일 장 종료 후 제출된다.
  화면의 '오늘 신청량'은 전 영업일 `appl` 행에서 온다.
- 진행률 바의 **빗금 구간**은 오늘 신청분이 전량 체결된다고 가정한 **잠정** 값이다(확정치와 색으로 분리).
- **취득 목적이 다르면 '발행주식 대비'를 직접 비교할 수 없다.** 소각은 발행주식수를 실제로 줄이지만
  임직원 보상 재원은 줄이지 않는다. 비교표는 소각 여부가 같을 때만 그 행을 강조한다.
- SK하이닉스의 실질 마지막 매매일 **2026-11-19 는 2027학년도 수능일**이라 증시가 10:00 개장 ·
  16:30 폐장으로 순연된다(휴장 아님 → 영업일 계산에는 반영하지 않고 각주로만 표시).
- 잔여 금액(추정)이 공시 취득예정금액을 넘으면 `amount_headroom_krw` 가 음수가 되고 경고가 붙는다.
  초과 매입에는 정정공시가 필요하다.
