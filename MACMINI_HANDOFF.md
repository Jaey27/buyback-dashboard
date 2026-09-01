# 자사주 매입 대시보드 — 맥미니 이전 핸드오프

최종 갱신: 2026-09-01 · 이전 사유: **정확도가 "매 영업일 18시 이후 실행"에 걸려 있는데**
현재 Windows 쪽은 자동 실행이 아예 등록되어 있지 않고 바탕화면 바로가기로 수동 실행만 한다.
사람이 하루라도 잊으면 그날 수치가 영구히 추정치로 떨어진다. 상시 전원인 맥미니로 옮겨 자동화한다.

---

## 0. 이 문서 사용법

**이 프로젝트는 이제 GitHub 리포다.** 맥미니에서 `git clone
https://github.com/Jaey27/buyback-dashboard.git ~/buyback-dashboard` 한 뒤,
리포 안에 들어 있는 이 문서를 열어 세션에 붙여넣고 아래처럼 지시하면 된다.

```
~/buyback-dashboard 를 clone 해 뒀어. 그 안의 MACMINI_HANDOFF.md 대로
자사주 대시보드를 이 맥미니로 이전해줘. 섹션 2의 선행 조건부터 순서대로 진행해줘.
```

clone 이 **가져오지 않는 것**이 있다 — 목록과 대처는 §3-1.

> ★ **이 개정본이 origin 에 push 되어 있어야 위 지시가 성립한다.** 리포에 커밋된
> MACMINI_HANDOFF.md · DEPLOY.md 가 개정 전 버전이면, 맥에서 clone 한 문서에는
> §3-2(신원·인증)도 `BUYBACK_PUBLISH=0` 검증도 없어서 첫 `run_daily.sh` 가 개인 이메일로
> 커밋을 만든다(§6-20). **Windows 에서 두 문서를 먼저 커밋·push 한 뒤에 맥에서 clone 할 것.**
> 확인: `git log origin/main -1 --stat | grep -E 'HANDOFF|DEPLOY'`

**이건 신규 개발이 아니라 "완성되어 Windows에서 가동 검증된 시스템의 이전"임.** 코드는 그대로 두고
환경만 옮기는 작업이므로 동작을 바꾸는 리팩터링은 하지 말 것. macOS용 셸/plist는 이미 작성되어 있고
**정적 검증(`bash -n`, plistlib 파싱) + GNU bash 에서의 락·publish 시나리오 실행까지 통과한 상태**다
— 다만 **맥에서 실제로 실행한 적은 없다.** 무엇을 확인했고 무엇이 미검증인지는 §8에 그대로 적어 두었다.

---

## 1. 무엇을 옮기는가 (시스템 개요)

KRX **KIND**(자기주식 신고/신청/체결) + **DART**(자기주식 취득결정·발행주식총수) +
**네이버 금융**(일봉)을 직접 긁어 삼성전자·SK하이닉스의 자사주 매입 진행률을
**외부 요청 0건의 자기완결 `dashboard.html` 한 장**으로 굽는다.

- **대상**: 삼성전자 005930 (2026-08-24~11-21, 53,285,968주 / 15조원),
  SK하이닉스 000660 (2026-08-20~11-19, 24,070,000주 / 40조원)
- **현재 상태(2026-09-01)**: `data/buyback.json` as_of 2026-09-01, `invariants_passed: true`.
  005930 daily 7행 / 000660 daily 9행. 불변식 게이트(수량·금액 항등식 + 영업일 항등식 +
  마감일 보정 + 휴장일 커버리지) 통과. Windows에서 `run_daily.bat` 가동 검증 완료.
- **배포 상태(2026-09-01)**: 리포 <https://github.com/Jaey27/buyback-dashboard>(public, 첫 커밋
  `3540b1a`·31개 파일) + Pages <https://jaey27.github.io/buyback-dashboard/>(`main` `/docs`,
  build_type `legacy`)가 **이미 살아 있다** — `status=built`, HTTP 200, 285,024 B, 콘솔 에러 0건.
  즉 맥미니가 할 일은 "만들기"가 아니라 **이 리포의 writer 역할을 넘겨받는 것**이다
  (§3-2 신원·인증 → §3-6 첫 push).

### ★★ 이 프로젝트를 옮기는 단 하나의 이유

유가증권시장 × 직접취득 조합은 KIND `trddetail` 의 **체결금액누계 칸이 구조적으로 공란**이다.
따라서 일별 체결금액·평균단가의 정확값을 얻는 유일한 경로는
**`decl`(신고내역)의 '체결금액누계'를 매 영업일 스냅샷해 전일 대비 차분**하는 것이다
(`data/kind_decl_snapshots.json` 에 누적).

- KIND는 **당일 체결분을 18시 이후에 집계**한다.
- 18시 이후 실행한 날 → `amount_source = kind_decl_snapshot` (**정확**)
- 거른 날 → **그 날짜만** `estimated_hl2`(고가+저가)/2 가중 배분 추정치로 떨어진다.
  실측 오차 005930 MAE 0.383% / MAX 1.082%, 000660 MAE 0.784% / MAX 1.596%.

**왜 소급 복구가 안 되는가**: KIND decl이 주는 것은 "지금 이 순간의 프로그램 누계" 한 개뿐이다.
과거 날짜의 누계를 되묻는 API가 없다. D일 누계를 그날 안에 찍어 두지 않으면
D일 값 = (D 누계 − D-1 누계) 를 나중에 재구성할 방법이 사라진다.
현재 원장에 2026-08-31 as_of가 회사별로 **딱 한 개씩** 들어 있는 이유가 이것이다.

### 모듈 구조 (전부 그대로 이식됨, 수정 불필요)

```
buyback-dashboard/
  scripts/build_data.py    수집 → 불변식 게이트 → data/buyback.json
  scripts/render.py        buyback.json → dashboard.html + docs/index.html
  scripts/dart_source.py   DART OpenAPI (취득결정·발행주식총수)
  scripts/price_source.py  KIND decl/appl/trd/trddetail + 일별 체결금액 차분
  scripts/market_data.py   네이버 일봉 + KRX 휴장일 캘린더 + 영업일 계산
  scripts/run_daily.sh     ★ macOS 엔트리포인트 (run_daily.bat 의 mac 판)
  scripts/install_launchd.sh / uninstall_launchd.sh
  publish.sh               성공한 실행만 GitHub push (origin 이 이미 붙어 있다 — DEPLOY.md)
  vendor/chart.umd.min.js  ★ Chart.js v4.4.0, 205,222 bytes — render 의 필수 입력
  data/  logs/  docs/  _ref/
```

---

## 2. 선행 조건 (이거 안 하면 사고 남)

### 2-0. Xcode Command Line Tools (= `git`) — §3-1 의 하드 선행조건

이 이전의 **1단계 명령이 `git clone`** 이다. 새 맥미니에는 git 이 없을 수 있고, 그러면
`git` 을 치는 순간 GUI 설치 다이얼로그가 떠서 절차가 통째로 멈춘다.

```bash
git --version                 # 버전이 나오면 이미 있다
xcode-select --install        # 없으면 설치 (GUI 다이얼로그 → 완료까지 몇 분)
```

`gh`(GitHub CLI)도 §3-2 의 인증에서 쓴다 — 없으면 `brew install gh`.
(`run_daily.sh` 도 git 이 PATH 에 없으면 publish 를 건너뛰며 `[WARN]` 을 남긴다 — §6-16.)

### 2-1. ⚠ Windows 쪽 실행을 멈출 것 — 중복 "발송"이 아니라 **원장이 갈라진다**

이 프로젝트에는 텔레그램 발송이 없다. 따라서 두 대가 동시에 돌아도 **중복 발송 사고는 없다.**
대신 훨씬 조용하고 나쁜 일이 생긴다 — **두 머신이 각자의 `data/kind_decl_snapshots.json` 을 갖게 되고,
서로 다른 날짜 집합을 축적한다.** 나중에 한쪽을 다른 쪽으로 덮어쓰면 덮인 쪽 날짜들이 통째로 사라지고,
그 날짜들은 §1의 이유로 영구히 추정치가 된다.

이제 양쪽이 같은 리포를 공유하므로 이 갈라짐은 **맥 쪽에서는** `git merge conflict` 로 터진다 — 상세는 §6-2.
**단 Windows 쪽은 다르다**: `run_daily.bat` 에는 git·publish 호출이 아예 없어(전수 검색 0건)
Windows 실행은 **자동 push 를 하지 않는다.** 즉 Windows 에서 갈라진 원장은 충돌로 드러나지도 않고
그냥 그 머신 로컬에만 남아 조용히 유실된다.

**현재 Windows에는 작업 스케줄러가 등록되어 있지 않다.** (`schtasks /Query /TN "BuybackDashboard"`
→ `ERROR: The system cannot find the file specified.` 로 확인함.) 실행 경로는 바탕화면 바로가기 2개뿐이다:

| 바로가기 | 하는 일 |
|---|---|
| `자사주 대시보드 갱신.lnk` | `run_daily.bat` 실행 |
| `자사주 대시보드 열기.lnk` | `dashboard.html` 열기 |

→ **끌 스케줄이 없다. 대신 "이전 완료 판정(§4)이 끝날 때까지 갱신 바로가기를 누르지 않는다"** 가
이 프로젝트의 선행 조건이다. 판정이 끝나면 갱신 바로가기는 지우거나 이름에 `[사용중지]` 를 붙여 둘 것.
읽기 전용인 '열기' 바로가기는 그냥 둬도 무해하다(단, 그 파일은 이제 갱신되지 않는다).

> 롤백이 필요하면 Windows에서 `run_daily.bat` 을 다시 돌리면 된다. 단 그 순간부터 두 머신의 원장이
> 갈라지기 시작하므로, **롤백할 거면 맥미니의 launchd를 먼저 끄고**(§5 `uninstall_launchd.sh`) 해야 한다.
>
> ★ 그리고 **`run_daily.bat` 은 push 를 하지 않는다**(스크립트에 git 호출이 한 줄도 없다).
> 그래서 Windows 에서 롤백 실행한 날의 원장 항목은 origin 에 올라가지 않고, 맥이 pull 해도
> 존재하지 않는다 — **충돌로 드러나지 않고 조용히 사라진다.** 롤백 실행했다면 그 직후
> Git Bash 에서 `bash publish.sh` 를 직접 돌려 원장을 origin 에 올릴 것.

### 2-2. Python 3.7 이상 (정적 확정) — 다만 Homebrew 3.11+ 권장

정적 감사 결론은 **최소 3.7** 이다. 5개 모듈 전부 `from __future__ import annotations` 를 갖고 있어
`set[date] | None` 같은 PEP 604/585 표기가 런타임 평가되지 않고, `ast.parse(feature_version=(3,6))` 까지
통과하며, 3.8~3.12 전용 문법·API(match, `datetime.UTC`, zoneinfo, `removeprefix`, dict `|` merge,
walrus, `functools.cache`)는 전수 검색 결과 0건이다. 유일한 바인딩 제약은 `sys.stdout.reconfigure`(3.7+).

즉 **macOS 기본 python3(3.9.6)로도 문법·표준라이브러리상 돌아간다** — etf-tracker와 달리 3.9에서
즉시 크래시하지 않는다. 그래도 Apple 배포판은 pip 설치 위치가 지저분하고 OS 업데이트로 사라질 수 있어
Homebrew를 권장한다.

```bash
python3 --version
brew install python@3.13     # Homebrew 없으면 https://brew.sh 먼저
```

### 2-3. 타임존을 Asia/Seoul 로 맞출 것

```bash
date +%Z                                   # KST 여야 한다
sudo systemsetup -gettimezone
sudo systemsetup -settimezone Asia/Seoul
```

이유를 코드 위치로 명시한다:

- `scripts/price_source.py:352` 의 `today = date.today().isoformat()` 이 `fetch_exec_detail()` 안에서
  `p_to = min(prog["period_to"] or today, today)` (:357)로 **KIND/네이버 조회 상한**을 정한다.
  이 함수에는 `today` 파라미터 자체가 없어 `build_data` 가 KST 기준일을 넘길 통로가 없다.
  **맥 TZ가 KST보다 뒤면 당일 체결분이 조회 범위에서 통째로 빠진다.**
- `scripts/render.py:1126` 의 stale 판정(`--max-age-days`)도 로컬 `date.today()` 다.
- `run_daily.sh` 가 `export TZ=Asia/Seoul` 로 막아 두므로 **스크립트 경유 실행은 안전**하다.
  하지만 `python3 scripts/build_data.py` 를 손으로 직접 치면 시스템 TZ가 그대로 노출된다.
- launchd `StartCalendarInterval` 은 **시스템 로컬 시각으로만 발화하고 TZ 환경변수를 무시한다.**
  맥이 UTC면 18:30 항목이 KST 익일 03:30에 발화한다. 이건 스크립트가 못 막는다.

### 2-4. DART 인증키 — 맥에서 `.env` 를 새로 만들 것 (키 값은 이 문서에 없다)

`scripts/dart_source.py:76-90` 의 키 탐색 순서는 다음과 같다.

1. `C:\Users\pjy09\_stock_tools\_dart\config.json` 의 `crtfc_key` ← **맥에는 이 경로가 없다**
2. 프로젝트 루트 `.env` 의 `DART_API_KEY=...`
3. 환경변수 `DART_API_KEY`

1은 `try/except Exception: pass` 로 감싸여 있어 맥에서 조용히 실패하고 2로 폴백한다.
**Windows의 그 `config.json` 을 열어 `crtfc_key` 값을 복사한 뒤, 맥미니의
`~/buyback-dashboard/.env` 에 `DART_API_KEY=<복사한 값>` 한 줄로 넣을 것.**
launchd는 로그인 셸의 환경변수를 물려주지 않으므로 3번 방식은 무인 실행에서 동작하지 않는다 —
**`.env` 가 유일한 현실적 경로다.**

> **Windows 에는 `.env` 파일 자체가 없다** — 지금까지 키는 위 1번 `config.json` 에서만 읽어 왔다.
> 즉 `.env` 는 '옮기는 파일'도 'clone 되는 파일'도 아니라 **맥에서 새로 만드는 파일**이다(§3-1).
> 키 값만 안전한 경로로 가져와 손으로 적을 것 — 채팅·공개 리포·스크린샷에 붙여넣지 말 것.
> `.env` 는 `.gitignore:21-23` 대상이라 만든 뒤에도 git 으로 따라가지 않는다.
>
> 키가 없으면 `require_key()` 가 예외를 던지는데, 그 에러 메시지 1번 항목에 여전히 Windows 경로가
> 찍힌다(코드를 안 고쳤다). 맥에서는 그 줄을 무시하고 2)/3)만 보면 된다. 다만 이제는 그 지점까지
> 가기 전에 **`run_daily.sh` 사전점검이 exit 3 으로 먼저 막는다**(§6-18).

---

## 3. 이전 절차

> **★ 순서 자체가 안전장치다.** clone 직후의 작업 트리는 `origin` 이 이미 붙어 있는데
> **커밋 신원은 비어 있다**(신원은 리포 로컬 설정이라 clone 대상이 아니다 — §6-20).
> 그 상태에서 `run_daily.sh` 를 돌리면 3단계 `publish.sh` 가 커밋을 시도한다.
> 그래서 이 문서는 **§3-2(신원·인증)를 어떤 실행보다 앞에** 두고, §3-5 의 검증 실행은
> `BUYBACK_PUBLISH=0` 으로 push 경로를 아예 타지 않게 한다. 순서를 바꾸지 말 것.

### 3-1. 파일 옮기기 — `git clone` 이 1순위 경로다

```bash
git clone https://github.com/Jaey27/buyback-dashboard.git ~/buyback-dashboard
cd ~/buyback-dashboard && git ls-files | wc -l     # 31 이어야 한다
```

첫 커밋 `3540b1a` 의 31개 파일에 **운영에 필요한 것이 전부 들어 있다** — 손으로 고를 파일이 없다.
코드 5개 모듈 · `publish.sh` · `vendor/chart.umd.min.js`(205,222 B, `render.py:21`/`:1136-1138` 의
**필수 입력**) · `docs/` 실물 · `.gitignore`/`.gitattributes`/`.github/` · 그리고 상태 파일 5개:
**`kind_decl_snapshots.json`**(실측 원장, 프로그램 키 5개 · 진행 중 2건은 as_of 2026-08-31 각 1개) ·
`kind_decl_backfill.json`(2026-08-20~08-28 백필, 재생성 불가) ·
`holidays_kr.json`(휴장일 52건 + short_sessions 1건, **2025-01-01~2027-12-31** 커버) ·
`buyback.json`(렌더 입력) · `dart_snapshot.json`(교차검증 근거).

**clone 이 가져오지 않는 것 — 파일 기준으로는 위 네 줄이 전부이고, 파일이 아닌 것 둘이 더 있다:**

| 없는 것 | 대처 |
|---|---|
| `.env` | 원래 Windows 에도 없다. **§2-4 대로 맥에서 새로 만든다.** 안 만들면 `run_daily.sh` 사전점검이 exit 3 |
| `dashboard.html` | `.gitignore:48`. **`run_daily.sh` 한 번 돌리면 생긴다**(§6-19). 여는 수단은 §3-8 |
| `_ref/DESIGN_SPEC.md`, `_ref/*.html`, `_ref/raoni_api_*.json` | 남의 사이트 자산이라 공개 리포에서 제외(`.gitignore:54-61`). 파이프라인 입력이 아니라 없어도 무관. Windows 로컬에는 남아 있다 |
| `logs/`, `data/_dart_cache/`, `__pycache__/` | 부스러기. 자동 재생성 |
| **실행 비트** | `.sh` 4개가 인덱스에 mode `100644` 로 들어 있다(Windows `core.filemode=false`) → **§3-4** |
| **커밋 신원 · push 인증** | `.git/config` 와 자격증명은 clone 대상이 아니다 → **§3-2**. 이게 이 이전 작업에서 가장 사고 나기 쉬운 자리다 |

Windows 전용이라 맥에서 안 도는 것(clone 에는 들어오지만 쓰지 않는다):
`run_daily.bat` / `update.bat`, `scripts/verify_dart.py` / `scripts/verify_price_source.py`(§6-13).

> **줄바꿈**: `.gitattributes` 의 `* text=auto eol=lf` + `*.sh text eol=lf` 덕분에
> **clone 하면 `.sh` 가 자동으로 LF 로 체크아웃된다.** 이 경로에서는 걱정할 것이 없다.
> `bad interpreter: /bin/bash^M` 는 **clone 대신 AirDrop/USB/복붙으로 옮겼을 때만** 나온다.
> 그 경로를 탔다면 `python3 -c "print(open('scripts/run_daily.sh','rb').read().count(b'\r'))"` → `0` 확인.

### 3-2. ★ 커밋 신원 + push 인증 — **어떤 실행보다 먼저**

리포도 Pages 도 이미 살아 있다. 맥미니가 할 일은 "만들기"가 아니라 **이 리포에 push 할 수 있게
되는 것**이다. 그리고 그 준비는 **첫 `run_daily.sh` 보다 앞서야 한다** — 이유는 아래 두 번째 경고 상자.

```bash
cd ~/buyback-dashboard

# 1) 리모트 확인 (clone 했다면 이미 붙어 있다)
git remote -v          # origin  https://github.com/Jaey27/buyback-dashboard.git
git status -sb         # ## main...origin/main
git check-ignore -v .env   # .gitignore:21 을 가리켜야 정상. 출력이 없으면 여기서 멈춰라

# 2) ★ 커밋 신원 — clone 은 이것을 가져오지 않는다 (§6-20)
git config user.name  "Jaey27"
git config user.email "Jaey27@users.noreply.github.com"   # 개인 메일이 공개 리포에 안 박히게
git config user.email                                     # 값이 나와야 한다

# 3) 인증 — Windows 의 인증은 이 맥에 안 따라온다 (§6-21)
gh auth login && gh auth setup-git      # 또는 DEPLOY.md §B-2 의 SSH 키(무인 실행에는 이쪽이 안전)

# 4) ★ push 인증 검증 — 반드시 push 로 확인한다
git push --dry-run origin main && echo "PUSH 인증 OK"
```

> ★ **`git ls-remote origin` 으로 인증을 확인하지 마라 — 거짓 통과한다.**
> 이 리포는 public 이라 `ls-remote` 는 자격증명이 하나도 없어도 익명 read 로 성공한다
> (실측: 전역 config·credential helper 를 비운 상태에서 `ls-remote` → rc 0,
> `refs/heads/main 3540b1a...` 정상 출력). 같은 조건에서 `git push --dry-run` 은
> `could not read Username for 'https://github.com'` 로 실패한다.
> **push 능력을 검증하는 명령은 `git push --dry-run` 뿐이다.**

> ★★ **이 절을 건너뛰고 `run_daily.sh` 를 먼저 돌리면 사고가 난다.**
> clone 직후 신원은 비어 있는데 `origin` 은 붙어 있어 `run_daily.sh` 3단계 조건
> (`git -C ... remote get-url origin`)이 **항상 참**이다. 예전 `publish.sh` 는 신원이 없으면
> 사용자의 개인 Gmail 주소로 **조용히 폴백해 커밋**했고, 그 커밋이 다음 push 때
> public 리포에 영구히 박혔다. 지금은 `publish.sh` 가 신원이 없으면 커밋하지 않고
> `[publish][ERROR]` 로 멈추도록 고쳐 두었지만(§6-20), 그러면 그날 Pages 갱신이 통째로 빠진다.
> **막히든 박히든 둘 다 손해다. 순서를 지키는 게 답이다.**

### 3-3. 의존성 설치

**venv 로 통일한다.** §2-2 가 권장하는 Homebrew `python@3.13` 은 PEP 668 의
externally-managed 환경이라 전역 `pip install` 이 `error: externally-managed-environment`
로 거부될 수 있다. venv 를 쓰면 그 문제가 사라지고, §3-7 의 launchd 절대경로(§6-7)와도
바로 이어진다.

```bash
cd ~/buyback-dashboard
python3 -m venv .venv
.venv/bin/python3 -m pip install --upgrade pip
.venv/bin/python3 -m pip install -r requirements.txt
.venv/bin/python3 -c 'import requests; print(requests.__version__)'

# ★ 손으로 부르는 run_daily.sh 도 이 venv 를 쓰게 만든다 (아래 경고 상자)
echo 'export BUYBACK_PYTHON="$HOME/buyback-dashboard/.venv/bin/python3"' >> ~/.zshrc
export BUYBACK_PYTHON="$HOME/buyback-dashboard/.venv/bin/python3"   # 지금 이 셸에도 즉시 적용
```

> ★ **`run_daily.sh` 는 저절로 venv 를 찾지 않는다.** `scripts/run_daily.sh:46` 은
> `PY="${BUYBACK_PYTHON:-python3}"` 다. `BUYBACK_PYTHON` 을 채워 주는 곳은
> **`install_launchd.sh` 가 굽는 plist 의 `EnvironmentVariables` 뿐**이므로
> **자동(launchd) 실행만 자동으로 올바른 인터프리터를 쓴다.** 손으로 `bash scripts/run_daily.sh`
> 를 치면 셸에 `BUYBACK_PYTHON` 이 없는 한 macOS 시스템 python3(3.9.6)를 쓰고,
> 거기엔 requests 가 없으니 사전점검이 `[ERROR] requests 모듈 없음` 으로 **exit 3** 한다
> — 방금 설치를 마친 직후라 원인을 오해하기 딱 좋다. 위 `~/.zshrc` 한 줄이 그것을 막는다.
> 이 문서의 수동 명령이 `BUYBACK_PYTHON=... bash scripts/run_daily.sh` 처럼 매번 앞에
> 변수를 붙이는 것도 같은 이유다(새 셸·다른 셸에서도 확실하게 하려고).

> 굳이 전역 설치를 유지하겠다면 `python3 -m pip install -r requirements.txt` 이고,
> 거부되면 `python3 -m pip install --break-system-packages -r requirements.txt` 가 필요하다.
> 그 경우 `BUYBACK_PYTHON` 을 안 잡아도 되고, §3-7 은 `BUYBACK_PYTHON=` 없이
> 그냥 `scripts/install_launchd.sh` 로 실행한다.

이후 이 문서의 `python3 ...` 수동 명령은 전부 `.venv/bin/python3 ...` 로 읽을 것.

`requirements.txt` 는 `requests>=2.31` **한 줄이 전부**다. 실제 import 전수 조사 결과 서드파티는
`requests` 하나뿐이며 `dart_source.py:32` 와 `price_source.py:63` 에만 쓰인다. 나머지는 표준 라이브러리.

**python.org 배포판을 쓴다면** `/Applications/Python\ 3.x/Install\ Certificates.command` 를 한 번 실행할 것
— 안 하면 DART/KIND 는 다 되는데 시세 단계만 골라 죽는다(이유는 §6-10). Homebrew python3는 대개 무관.

### 3-4. 실행 권한

`.sh` 4개는 **인덱스에 mode `100644`(실행 비트 없음)로 커밋돼 있어** clone 해도 안 붙는다(§6-22).

```bash
cd ~/buyback-dashboard
chmod +x scripts/*.sh publish.sh
git update-index --chmod=+x scripts/run_daily.sh scripts/install_launchd.sh \
                            scripts/uninstall_launchd.sh publish.sh
git commit -m "chore: mark shell scripts executable"   # push 는 §3-6 에서
```

> 이 `git commit` 은 **§3-2 의 신원 설정이 끝나 있어야** 성공한다. 안 되어 있으면
> `Author identity unknown / fatal: unable to auto-detect email address` 로 exit 128 이다
> (전역 신원도 미설정임을 확인했다: `git config --global user.email` → rc 1).
> ★ 그 에러 메시지는 `git config --global user.email` 을 안내하는데, **그대로 따라가면
> 개인 메일이 들어간다.** 반드시 §3-2 의 `Jaey27@users.noreply.github.com` 값을 쓸 것.

### 3-5. 검증 — 자동 등록 전에 손으로 한 번 (**push 없이**)

```bash
cd ~/buyback-dashboard

# ① 원장이 제대로 따라왔는가 (as_of 목록이 Windows에서와 같아야 한다)
.venv/bin/python3 -c "
import json
s=json.load(open('data/kind_decl_snapshots.json',encoding='utf-8'))
for k,v in s.items(): print(k, sorted(v))
"
# 기대: '000660|2026-08-20' ['2026-08-31'] / '005930|2026-08-24' ['2026-08-31'] + 과거 프로그램 3건

# ② 휴장일 캘린더 커버리지
.venv/bin/python3 -c "
import json; d=json.load(open('data/holidays_kr.json',encoding='utf-8'))
print(d['covers'], len(d['holidays']),'건')"
# 기대: {'from': '2025-01-01', 'to': '2027-12-31'} 52 건

# ③ 실제 파이프라인 1회 — ★ BUYBACK_PUBLISH=0 (수집 + 렌더까지만. 커밋도 push 도 하지 않는다)
BUYBACK_PUBLISH=0 BUYBACK_PYTHON="$PWD/.venv/bin/python3" bash scripts/run_daily.sh
echo "exit=$?"

# ④ 산출물 확인
ls -l dashboard.html docs/index.html
open dashboard.html          # 브라우저로 눈으로 확인
```

③ 이 `exit=0` 이고 `[OK] done` 이 찍혀야 한다. 로그는 `logs/run_YYYYmmdd_HHMMSS.log`.

> **왜 `BUYBACK_PUBLISH=0` 인가**: 기본값 `auto` 는 `origin` 만 있으면 3단계로 내려가
> `publish.sh` 를 부른다. clone 직후 `origin` 은 항상 있으므로, 이 검증 실행이 그대로
> 커밋과 push 를 시도하게 된다. 인증을 §3-2 에서 이미 잡았더라도 **검증 단계에서
> 원격을 건드릴 이유가 없다.** push 를 포함한 실주행은 §3-6 에서 따로 한다.

> `run_daily.sh` 가 하는 일: TZ 고정 → 로그 준비 → 중복 실행 락(PID + 부팅ID + 나이 3중 판정) →
> 사전점검(python / requests / 필수 4파일 / 원장 존재 / **DART 인증키** / publish 강제 시 git 존재) →
> `[1/2] build_data.py` → **실패하면 render를 건너뛰고 exit 1** → `[2/2] render.py --max-age-days 4`
> → `[3/3] publish.sh`(선택 — **건너뛰면 그 이유를 [WARN] 으로 남긴다**) → 60일 지난 로그 삭제.

### 3-6. 첫 실주행 + push (여기서 처음으로 원격을 건드린다)

```bash
cd ~/buyback-dashboard
BUYBACK_PYTHON="$PWD/.venv/bin/python3" bash scripts/run_daily.sh   # 이번엔 3단계 publish 까지 탄다
echo "exit=$?"

git log -1 --format='%an <%ae>  %s'   # ★ Jaey27 <Jaey27@users.noreply.github.com> 여야 한다
git status -sb                        # 'ahead N' 이 남아 있으면 push 가 실패한 것 → §3-2 의 인증
git push                              # 보통은 'Everything up-to-date' — publish.sh 가 이미
                                      # 밀린 커밋을 전부 push 하기 때문이다(DEPLOY.md §C-6)

sleep 90
gh api repos/Jaey27/buyback-dashboard/pages/builds/latest --jq '.status'   # built
curl -sI https://jaey27.github.io/buyback-dashboard/ | head -1              # HTTP/2 200
```

> **값이 안 바뀐 날에는 `publish.sh` 가 데이터 커밋을 만들지 않는다**(타임스탬프만 다르면
> 커밋 생략 — §6-15). 같은 날 Windows 에서 이미 push 한 상태라면 여기서
> `타임스탬프(generated_at/captured_at)만 갱신됨` 로그가 정상이고, 그때 push 되는 것은
> §3-4 의 실행 비트 커밋 하나뿐이다. **Pages 콘텐츠가 안 바뀌는 것도 정상이다** —
> `.sh` 파일 모드는 `docs/index.html` 과 무관하다. 링크의 기준일이 바뀌는지는
> **다음 영업일 데이터 push** 로 판정한다(§4 마지막 항목).

### 3-7. launchd 등록 (자동 실행 켜기)

```bash
cd ~/buyback-dashboard
BUYBACK_PYTHON=$PWD/.venv/bin/python3 scripts/install_launchd.sh   # §3-3 의 venv 를 그대로 넘긴다
launchctl list | grep buyback-dashboard        # 항목이 보이면 등록됨
plutil -lint ~/Library/LaunchAgents/com.pjy.buyback-dashboard.daily.plist   # OK 여야 한다
```

> 전역 설치를 택했다면 `BUYBACK_PYTHON=` 없이 `scripts/install_launchd.sh` 로 실행한다.
> 스크립트는 고른 파이썬을 그 자리에서 실행해 `sys.executable`(shim 이 아닌 실제 인터프리터
> 경로)로 바꿔 plist 에 박고, plist 를 쓴 뒤 `plutil -lint` 로 먼저 검사한다.

등록되는 스케줄은 라벨 `com.pjy.buyback-dashboard.daily` 하나, `StartCalendarInterval` 16개 항목이다.

| 시각 | 요일 | 역할 |
|---|---|---|
| 18:30 | 월~금 | 1차 — KIND 18시 집계 직후, 여유 30분 |
| 19:30 | 월~금 | 2차 — 1차가 네트워크/서버 문제로 실패했을 때 |
| 21:00 | 월~금 | 3차 — 저녁 마지막 기회 |
| 08:40 | **매일**(Weekday 키 없음 = launchd가 '매일'로 해석) | 저녁에 맥이 꺼져 있었을 때의 복구 그물 |

**아침 08:40이 왜 복구가 되는가**: `snapshot_decl()` 은 as_of 키를 `today` 가 아니라
**trddetail의 마지막 체결일**로 잡는다. 따라서 D일 값은 D일 18:00부터 **다음 영업일 18:00(다음 집계) 전까지**
언제 찍어도 `as_of=D` 로 정확히 귀속된다. 즉 D일 값을 잃으려면 **약 24시간 창을 통째로** 놓쳐야 한다.
"18:30 한 번을 놓치면 그날은 끝"이 아니다.

**재시도가 안전한 이유**: `snapshot_decl()` 은 `store.setdefault(key,{})[as_of] = {...}` 로
조건 없이 덮어쓴다(last-write-wins). 같은 날 몇 번을 돌려도 as_of 항목은 1개만 남고 누적이 꼬이지 않으며,
나중 실행이 항상 더 정확한 값으로 갱신한다. (오프라인 스텁 테스트로 확인)

### 3-8. 맥에서 대시보드 여는 수단 만들기

Windows 에는 `자사주 대시보드 열기.lnk` 바로가기가 있었다(§2-1). 그 기능이 맥에도 있어야 한다.

```bash
# 로컬 파일을 여는 심볼릭 링크 (dashboard.html 은 §3-5 ③ 실행 이후에 존재한다)
ln -sf ~/buyback-dashboard/dashboard.html ~/Desktop/자사주_대시보드.html

# 그냥 명령으로 열어도 된다
open ~/buyback-dashboard/dashboard.html
```

**다른 기기에서도 볼 거면 로컬 파일이 아니라 공개 링크를 북마크하는 쪽이 낫다** —
<https://jaey27.github.io/buyback-dashboard/> 는 맥미니가 매일 갱신하고, stale 배너 문구도
공개 독자용("평일 18:30 자동 갱신됩니다")으로 나간다(DEPLOY.md §1).

---

## 4. 이전 완료 판정 체크리스트

**순서대로 볼 것.** 앞의 다섯 개는 첫 `run_daily.sh` 실행 **전에** 끝나 있어야 한다(§3-2).

- [ ] Windows 갱신 바로가기를 이 판정이 끝날 때까지 누르지 않기로 합의됨 (§2-1)
- [ ] `git --version` 이 동작 (없으면 `xcode-select --install`, §2-0)
- [ ] `git ls-files | wc -l` 이 **31**, `git remote -v` 가 `origin ...Jaey27/buyback-dashboard.git`
- [ ] **★ 커밋 신원 — 첫 실행 전에!** `git config user.email` 이
      `Jaey27@users.noreply.github.com` 을 뱉음. clone 은 안 가져온다 (§3-2, §6-20)
- [ ] **★ push 인증 — 첫 실행 전에!** `git push --dry-run origin main` 이 프롬프트 없이 성공 (§3-2, §6-21)
      (**`git ls-remote` 로 확인하지 말 것** — public 리포라 자격증명이 하나도 없어도 통과한다)
- [ ] `date +%Z` 가 `KST`
- [ ] 시스템 `python3 --version` 이 3.7 이상 (권장 3.11+). 다만 파이프라인이 실제로 쓰는 것은
      `.venv/bin/python3 --version` 이다(§3-3)
- [ ] `.env` 에 `DART_API_KEY=` 가 채워져 있음 (Windows `config.json` 에서 복사, §2-4)
- [ ] **키가 실제로 로드되는가** — 파일 존재만으로는 부족하다. 아래가 `True` 여야 한다:
      `.venv/bin/python3 -c "import sys;sys.path.insert(0,'scripts');import dart_source as d;print(bool(d.DART_KEY))"`
      (★ `python3` 로 치면 requests 가 없어 `ModuleNotFoundError` 로 죽는다 — `dart_source.py:32`
      가 최상위에서 requests 를 import 한다. 반드시 venv 인터프리터로 칠 것.
      `dart_source` 는 키가 비어도 import 시점에 죽지 않고 첫 API 호출의 `require_key()` 에서야
      예외를 던진다. 이제 `run_daily.sh` 사전점검이 이 검사를 해서 exit 3 으로 막는다.)
- [ ] `git check-ignore -v .env` 가 `.gitignore:21` 을 가리킴 — 출력이 없으면 **public 리포에
      DART 인증키가 커밋된다.** 여기서 멈출 것
- [ ] `data/kind_decl_snapshots.json` 의 as_of 목록이 Windows에서와 **동일** (§3-5 ①)
- [ ] `vendor/chart.umd.min.js` 가 205,222 bytes 로 존재
- [ ] `BUYBACK_PUBLISH=0 BUYBACK_PYTHON=$PWD/.venv/bin/python3 bash scripts/run_daily.sh` 가
      exit 0, `dashboard.html` + `docs/index.html` 생성
      (`dashboard.html` 은 clone 직후엔 없는 게 정상 — 이 실행이 만든다, §6-19)
- [ ] 브라우저로 `dashboard.html` 을 열었을 때 stale 배너가 뜨지 않음 (뜨면 데이터가 낡은 것)
- [ ] 맥에서 대시보드를 여는 수단이 있음 — 데스크톱 심볼릭 링크 또는 공개 링크 북마크 (§3-8)
- [ ] **★ 첫 push 뒤 커밋 저자 확인** `git log origin/main -1 --format='%an <%ae>'` 가
      `Jaey27 <Jaey27@users.noreply.github.com>` — **개인 Gmail 주소가 보이면 즉시 멈추고
      메인 세션에 알릴 것**(public 리포 히스토리는 되돌리기 어렵다, §6-20)
- [ ] **첫 push 뒤 Pages 빌드 성공**
      `gh api repos/Jaey27/buyback-dashboard/pages/builds/latest --jq '.status'` 가 `built`
      (**push 후 1~2분 기다릴 것** — 즉시 안 바뀐다고 실패로 보지 말 것, §6-23)
- [ ] `launchctl list | grep buyback-dashboard` 에 항목 표시
- [ ] `plutil -lint ...plist` 가 `OK`
- [ ] **★ 다음 영업일 18:30 이후** — 최종 판정. 그 날짜의 `amount_source` 가 `kind_decl_snapshot`
      이고, <https://jaey27.github.io/buyback-dashboard/> 의 기준일이 그 날짜로 바뀜

> ★ **"링크의 기준일이 바뀜" 을 그 전 단계의 판정으로 쓰지 말 것 — 정상인데도 실패로 읽힌다.**
> `publish.sh` 는 값이 실제로 바뀐 실행에서만 커밋한다(타임스탬프만 다르면 커밋 자체를 안 한다 — §6-15).
> 그리고 §3-4 의 실행 비트 커밋은 `publish.sh` 의 커밋 대상 7개 경로에 `.sh` 가 없어
> `docs/index.html` 을 건드리지 않는다. 즉 **첫 push 로는 Pages 내용이 안 바뀌는 게 맞다.**
> 기준일 변화는 **새 영업일의 데이터 push** 에서만 확인할 수 있다.

마지막 항목 확인 명령:

```bash
.venv/bin/python3 -c "
import json
d=json.load(open('data/buyback.json',encoding='utf-8'))
print('as_of', d['as_of'])
for t,c in d['companies'].items():
    for r in c['daily'][-3:]:
        print(t, r['date'], r.get('amount_source'))
"
```

`estimated_hl2` 가 나오면 그날 18시 이후 스냅샷이 안 찍힌 것이다. 마지막 행(오늘)의 `amount_source` 가
`None` 인 것은 정상 — 아직 체결이 집계되지 않은 잠정 행이다.

---

## 5. 운영 명령

```bash
cd ~/buyback-dashboard

# ★ BUYBACK_PYTHON 을 ~/.zshrc 에 넣어 뒀으면(§3-3) 앞의 변수 지정은 생략해도 된다.
BUYBACK_PYTHON=$PWD/.venv/bin/python3 bash scripts/run_daily.sh   # 수동 갱신 (수집 + 렌더 + push)
BUYBACK_PUBLISH=0 BUYBACK_PYTHON=$PWD/.venv/bin/python3 bash scripts/run_daily.sh   # push 없이

.venv/bin/python3 scripts/build_data.py                # 수집만
.venv/bin/python3 scripts/build_data.py --dry-run      # 파일 안 씀
.venv/bin/python3 scripts/render.py --max-age-days 4   # 렌더만
.venv/bin/python3 scripts/market_data.py holidays 2025 2026 2027 2028   # 휴장일 캘린더 연장

open ~/buyback-dashboard/dashboard.html            # 로컬 대시보드 열기 (§3-8)
open https://jaey27.github.io/buyback-dashboard/   # 공개 페이지

launchctl list | grep buyback-dashboard                          # 등록 확인
launchctl kickstart -k gui/$(id -u)/com.pjy.buyback-dashboard.daily   # 즉시 1회 실행
scripts/uninstall_launchd.sh                                     # 자동 실행 중단(bootout + disable)

tail -f logs/launchd.out.log                 # launchd 표준출력 (10MB 넘으면 자동 절단)
ls -lt logs/run_*.log | head                 # 실행별 상세 로그 (60일 후 자동 삭제)
rm -rf .run_daily.lock                       # 락이 남아 계속 skip 될 때만
```

`run_daily.sh` 조정 환경변수:

| 변수 | 기본 | 뜻 |
|---|---|---|
| `BUYBACK_PYTHON` | `python3` | 쓸 파이썬. **launchd는 PATH를 안 물려주므로 plist가 절대경로를 박아 넘긴다.** 반대로 손수 실행할 때는 셸이 이 값을 갖고 있어야 venv 를 쓴다(§3-3) |
| `BUYBACK_MAX_AGE` | `4` | `render.py --max-age-days` |
| `BUYBACK_TZ` | `Asia/Seoul` | 스크립트가 `export TZ` 로 강제 |
| `BUYBACK_LOG_KEEP` | `60` | `logs/run_*.log` 보관 일수 |
| `SKIP_IF_HOLIDAY` | `0` | 1이면 KRX 휴장일에 아무것도 안 함. **기본 0을 권장**(§6-5) |
| `REFRESH_HINT` | (render 기본값) | 페이지 stale 배너 안내문 주입 |
| `BUYBACK_NO_LOCK` | `0` | 1이면 중복 실행 락 미사용(디버깅용) |
| `BUYBACK_LOCK_MAX_MIN` | `120` | 락을 강제 회수하는 나이(분). PID가 살아 있어도 이보다 오래된 락은 '재사용된 PID'로 보고 빼앗는다(§6-9) |
| `BUYBACK_PUBLISH` | `auto` | `0` 끄기 / `1` 강제. git 리포이고 origin이 있으면 성공 후 push. **clone 한 트리에는 origin 이 항상 있으므로 `auto` 는 사실상 '항상 켜짐'이다** — 검증 실행에는 `0` 을 명시할 것(§3-5). 건너뛰면 이유를 `[WARN]` 으로 남긴다(§6-16). `1` 인데 git 이 없으면 사전점검 exit 3 |

종료코드: `0` 정상·휴장일skip·중복실행skip / `1` build 실패(**render 안 함**) / `2` render 실패 / `3` 사전점검 실패.

### 슬립·전원 (맥미니는 상시 AC)

```bash
sudo pmset -a sleep 0          # 시스템 슬립 끔
sudo pmset -a disksleep 0
sudo pmset -a standby 0        # 딥 슬립 방지
sudo pmset -a autorestart 1    # ★ 정전 후 자동 시작
sudo pmset -a womp 1           # 네트워크 깨우기
sudo pmset repeat wakeorpoweron MTWRF 18:20:00   # 보험 — 18:30 잡 10분 전 강제 기상
pmset -g custom; pmset -g sched
```

launchd는 cron과 달리 **잠든 맥을 깨워 놓친 잡을 실행한다.** 단 여러 시각을 한꺼번에 놓쳤으면
깨어난 뒤 1회만 실행하고, **완전 종료(shutdown) 상태면 아예 못 돈다** — 그래서 `autorestart 1` 이 필요하다.

### GitHub Pages — 넘겨받은 뒤의 확인·문제 해결

**리포 생성·Pages 활성화는 이미 끝났다.** 맥미니가 writer 를 넘겨받는 절차는 **§3-2(신원·인증)와
§3-6(첫 push)** 이다 — 그쪽이 순서상 앞이라 거기에 두었다. 여기는 그 뒤의 확인·문제 해결만 둔다.

```bash
cd ~/buyback-dashboard

git status -sb                        # 'ahead N' 이면 push 가 밀려 있다 → 인증 문제(§3-2)
git log origin/main -1 --format='%an <%ae>  %ad  %s'   # 저자가 noreply 인지, 언제 올랐는지
git push --dry-run origin main        # 인증이 살아 있는지 (ls-remote 로는 확인되지 않는다)
gh api repos/Jaey27/buyback-dashboard/pages/builds/latest --jq '.status, .error.message'
curl -sI https://jaey27.github.io/buyback-dashboard/ | head -1
```

`run_daily.sh` 3단계가 수집·렌더 성공 후에만 `publish.sh` 를 부른다. 자세한 것(인증 3안, 커밋 대상
판단표, 원장 충돌 병합 레시피, **리포를 잃었을 때의 재생성 절차**)은 **[DEPLOY.md](DEPLOY.md)** 에 있다.

### GitHub Actions 백업 워크플로 — **현재 상태로는 동작하지 않는다**

`.github/workflows/update.yml` 은 `workflow_dispatch`(수동 버튼)만 켜 둔 백업 경로다.
맥미니가 며칠 죽어 있었던 게 확실할 때만 Actions 탭에서 `Run workflow` 로 한 번 돌린다
(스케줄로 돌리지 않는 이유는 DEPLOY.md §G-4 — 원장의 writer 는 하나여야 한다).

**다만 지금 이 리포에는 시크릿이 하나도 없다**(`gh secret list --repo Jaey27/buyback-dashboard`
→ 빈 출력). 워크플로의 Build 스텝은 `DART_API_KEY: ${{ secrets.DART_API_KEY }}` 에 의존하므로,
지금 버튼을 누르면 키가 빈 문자열이 되어 `require_key()` 에서 `DartError` 로 **반드시 실패한다.**
쓸 생각이면 먼저 시크릿을 넣을 것(값이 셸 히스토리에 남지 않게 프롬프트로 입력):

```bash
gh secret set DART_API_KEY --repo Jaey27/buyback-dashboard   # 프롬프트에 키를 붙여넣는다
```

> ★ Actions 를 한 번이라도 돌렸다면 **맥미니에서 `git pull --rebase` 를 먼저** 하고
> `run_daily.sh` 를 돌릴 것. 안 그러면 다음 push 때 원장이 충돌한다(§6-2, DEPLOY.md §G-2).
> 러너는 미국 IP라 KIND/DART/네이버 응답이 다를 수 있으니 값은 맥미니 결과와 한 번 대조할 것.

---

## 6. 함정 목록

### 6-1. ★ `data/kind_decl_snapshots.json` 을 두고 오면 되돌릴 수 없다
KIND는 "지금 이 순간의 누계"만 준다. 과거 날짜의 누계를 되묻는 API가 없으므로,
원장을 잃으면 그 날짜들의 정확값은 **영원히** 추정치(`estimated_hl2`)로 남는다.
백필(`kind_decl_backfill.json`)도 마찬가지로 재생성 불가한 정적 자산이다.

### 6-2. ★ 두 머신이 동시에 돌면 `kind_decl_snapshots.json` 이 merge conflict 를 낸다
이 프로젝트는 텔레그램 발송이 없어 "같은 리포트가 두 번 간다" 같은 사고는 없다.
대신 각 머신이 서로 다른 날짜 집합을 축적한다. **맥미니와 Actions 처럼 둘 다 push 하는 쪽끼리는**
그 갈라짐이 다음 `git pull --rebase` 에서 **충돌**로 나타난다 — 이 파일은 JSON 이라
git 이 자동 병합하지 못한다.

★ **Windows 는 이 충돌 경로에조차 오지 않는다.** `run_daily.bat` 에는 git·publish 호출이
한 줄도 없어(전수 검색 0건) 자동 push 를 하지 않기 때문이다. Windows 에서 돌린 날의 원장은
그 머신에만 남고 origin 에는 없다 — **충돌로 드러나지 않고 조용히 유실된다.** 그래서 Windows
에서 롤백 실행을 했다면 그 직후 Git Bash 에서 `bash publish.sh` 를 직접 돌려야 한다(§2-1). 여기서 `--ours` / `--theirs` 로 한쪽을 채택하면
버린 쪽 날짜가 **영구히** `estimated_hl2` 로 떨어진다(§1).
→ 반드시 **DEPLOY.md §G-2 의 합집합 병합 스니펫**(양쪽 날짜를 다 살리고 같은 키는
`captured_at` 이 늦은 쪽 채택)을 쓸 것. 애초에 writer 를 한 대로 유지하는 게 정답이다(§2-1).

### 6-3. ★ `vendor/chart.umd.min.js` 를 빼먹으면 render가 exit 1
`render.py:21` 이 `ROOT/vendor/chart.umd.min.js` 경로를 잡고 `:1136-1138` 이 그것을 읽어 인라인한다.
파일이 없거나 안에 `Chart` 문자열이 없으면 즉시 실패한다. **README §4 파일구조 트리에 이 디렉터리가
빠져 있어서** 폴더를 손으로 골라 옮기면 놓치기 쉽다. `run_daily.sh` 사전점검이 exit 3으로 잡아 주긴 한다.

### 6-4. ★ 타임존이 KST가 아니면 당일 체결분이 통째로 빠진다
`price_source.py:352` 의 `date.today()` 가 `fetch_exec_detail` 의 조회 상한(`:357`)을 정하는데
`build_data` 가 KST 기준일을 넘길 통로가 없다(함수에 `today` 파라미터 자체가 없다).
`run_daily.sh` 의 `export TZ=Asia/Seoul` 이 이를 우회하지만, **launchd의 발화 시각은 시스템 로컬 시각**이라
스크립트가 못 막는다. 근본 해법은 `fetch_exec_detail` 에 `today` 파라미터를 추가하는 것이지만
이번 이전 범위에서는 코드를 손대지 않았다.

### 6-5. 휴장일에는 그냥 돌려도 된다 — 오히려 그게 낫다
`assemble()` 의 `last_day = min(today, deadline_bd)` → `business_days_list()` 가 휴장일을 애초에 제외하므로
daily[]에 오늘 행이 생기지 않는다. 결과는 직전 영업일과 완전히 동일한 **무해한 no-op(exit 0)** 이고
불변식 (5) '모든 date가 영업일'에도 걸리지 않는다(2026-09-24~27 추석+주말 구간으로 실측 확인).
`SKIP_IF_HOLIDAY` 기본값이 `0`(휴장일에도 실행)인 것은 의도된 것이다 — **휴장일 실행이 전날 값을
다시 스냅샷해 두는 복구 기회**가 되기 때문이다. 로그 위생 때문에 1로 바꾸고 싶으면 그 복구 기회를 포기하는 것.

### 6-6. ★ FileVault + LaunchAgent 조합 (pmset보다 중요)
이 등록은 **LaunchAgent(`gui/$UID`)** 라 "사용자가 로그인한 세션"에서만 돈다.
FileVault가 켜진 채 정전 후 재부팅되면 맥이 로그인 화면에 멈춰 있고 **잡이 영영 안 돈다.**
대응은 셋 중 하나 — (a) FileVault 끄기, (b) 자동 로그인 켜기(시스템 설정 > 사용자 및 그룹 > 자동 로그인),
(c) LaunchDaemon으로 전환(단 `.env` 경로와 사용자 컨텍스트가 달라져 스크립트 수정 필요).
상시 무인 운용이면 (a)+(b) 조합이 현실적. **이전 전에 맥미니의 FileVault/자동 로그인 상태를 확인할 것.**

### 6-7. ★ launchd는 PATH도 환경변수도 물려주지 않는다
`python3` 를 못 찾는 것이 macOS에서 가장 흔한 실패다. `install_launchd.sh` 가 plist의
`EnvironmentVariables` 에 `BUYBACK_PYTHON` 절대경로와 `PATH` 를 박아 넘긴다.
§3-3 대로 venv를 썼다면 `BUYBACK_PYTHON=$PWD/.venv/bin/python3 scripts/install_launchd.sh` 로 넘길 것
(§3-7). ★ 거꾸로, **plist 밖에서는 아무도 `BUYBACK_PYTHON` 을 채워 주지 않는다.**
손으로 `bash scripts/run_daily.sh` 를 치면 `run_daily.sh:46` 의 기본값 `python3`(시스템 3.9.6)가
잡혀 requests 가 없어 exit 3 이 난다 — §3-3 의 `~/.zshrc` 한 줄이 그것을 막는다.
`install_launchd.sh` 는 넘겨받은 파이썬을 그 자리에서 실행해 `sys.executable` 로 바꿔 박으므로,
pyenv/asdf 의 shim 경로를 주더라도 plist 에는 실제 인터프리터 절대경로가 들어간다.
같은 이유로 **DART 키를 환경변수로만 두면 launchd 실행에서 못 읽는다** → `.env` 필수(§2-4).

### 6-8. ★ `run_daily.sh` 의 build 가드를 절대 지우지 말 것
`"$PY" scripts/build_data.py || rc=$?` 후 `rc != 0` 이면 render를 건너뛰고 exit 1 한다
(`run_daily.bat:26` 의 `if errorlevel 1 goto build_failed` 와 같은 역할).
없으면 수집이 실패해도 낡은 `data/buyback.json` 으로 **'겉보기 멀쩡한' 페이지**를 찍어
현재 값이 아닌 수치를 현재 값처럼 보여준다. `build_data.main()` 의 종료코드는 0(정상 또는 일부 회사만 실패) /
1(그 외 예외) / 2(불변식 게이트 실패, buyback.json 미생성)이며 가드가 1과 2를 모두 잡는다.

### 6-9. 중복 실행 락은 `mkdir` 원자성 기반이다
macOS에는 util-linux의 `flock(1)` 이 없다. 그래서 `mkdir "$PROJECT_DIR/.run_daily.lock"` 의 성공 여부를
락으로 쓴다. 락 디렉터리 안에 `PID` 와 `부팅 식별자`(macOS `sysctl -n kern.boottime`)를 2행으로 적는다.
수동으로 지우려면 `rm -rf .run_daily.lock`. 중복 실행이면 exit 0(스케줄러 알람 억제).

★ 회수 판정을 PID 하나로만 하면 안 된다. SIGKILL/정전으로 락이 남은 뒤 그 PID **번호를 무관한
프로세스가 재사용**하면, 이후 모든 실행이 "이미 실행 중"으로 보고 exit 0 으로 조용히 건너뛴다 —
exit 0 이라 launchd 도 실패로 보지 않아 **파이프라인이 영구히 멈춘다.** 그래서 3중으로 본다:

1. PID가 죽었다 → 회수
2. 락을 잡은 부팅과 지금 부팅이 다르다(재부팅 이후 남은 락) → 회수
3. 락 나이가 `BUYBACK_LOCK_MAX_MIN`(기본 120)분을 넘었다 → **PID가 살아 있어도** 회수하고 [WARN]

정상 실행은 길어야 수 분이므로 120분은 안전한 여유다. 회수 사유는 로그에 그대로 남는다.

### 6-10. python.org 빌드의 CA 문제는 시세 단계만 골라 죽인다
`market_data.fetch_ohlcv()` 만 `urllib.request`(시스템 CA)로 `api.finance.naver.com` https를 친다.
나머지(DART/KIND)는 `requests`(certifi 번들)를 쓴다. 그래서 CA 미설치 시
**DART/KIND는 전부 성공하는데 `build_data.py:321` 에서만 `CERTIFICATE_VERIFY_FAILED`** 가 나는
헷갈리는 모습이 된다. `Install Certificates.command` 를 한 번 돌릴 것(§3-3). Homebrew python3는 대개 무관.

### 6-11. 휴장일 캘린더는 2027-12-31까지만 덮는다
커버리지 밖 날짜로 영업일을 계산하면 공휴일이 통째로 빠져 ETA가 조용히 낙관 편향되므로,
`market_data` 가 그 즉시 `HolidayCoverageError` 를 던지고 빌드 게이트가 막는다(**설계된 실패**).
2027년 하반기에 `python3 scripts/market_data.py holidays 2026 2027 2028 2029` 로 연장할 것.
`short_sessions`(수능일 등 수동 항목 1건)는 재수집해도 보존된다(`market_data.py:226-232`).

### 6-12. 결함 아님 — 특정 날짜만 추정치로 표시되면 trddetail lag를 의심할 것
`snapshot_decl()` 의 as_of는 trddetail의 최신 날짜에 의존한다. trddetail이 decl보다 하루 뒤처지면
전일 키가 당일 누계로 덮어써져 2일치가 뭉칠 수 있다(오프라인 재현됨).
다만 저가~고가 ±15% 밴드 게이트(`_price_band_bad_dates()`)가 **그 날짜만** 걸러 `estimated_hl2` 로
강등하므로 **틀린 '정확값'이 페이지에 실리는 경로는 없다.** 현재 원장에서는 lag가 관측되지 않았다(표본 1회).

### 6-13. 수동 검증 스크립트 2개는 맥에서 안 돈다
`scripts/verify_dart.py:4,8` 과 `scripts/verify_price_source.py:4` 가
`C:\Users\pjy09\buyback-dashboard\...` 절대경로를 `sys.path.insert`/`open` 에 박고 있다.
파이프라인 입력이 아니라 우선순위는 낮지만, 맥에서 검증을 돌리려면 `__file__` 기반으로 고쳐야 한다.
(파이프라인 본체 5개는 전부 `__file__` 기반이라 이식 문제가 없다.)

### 6-14. 로컬 파일 크기와 GitHub 에 올라간 크기가 다른 건 정상이다
`Path.write_text()` 는 `newline=None` 기본값이라 Windows에서 CRLF, macOS에서 LF로 쓴다
(`buyback.json`, `dashboard.html`, `docs/index.html`). `.gitattributes` 의 `* text=auto eol=lf` 가
add 시점에 LF 로 정규화하므로, Windows 로컬 `docs/index.html` 은 286,070 B 인데
커밋된 blob 과 Pages 응답은 **285,024 B** 다(차이 1,046 B = CRLF 줄 수). 손상이 아니다.
**맥에서는 render 가 애초에 LF 로 쓰므로 이 차이 자체가 사라진다** — 즉 맥으로 옮긴 뒤
`docs/index.html` 이 통째로 diff 처럼 보이는 일은 없다. (첫 커밋은 이미 났다.)

### 6-15. ★ '바뀐 게 없으면 커밋 안 함'은 그냥은 성립하지 않는다
커밋 대상 파일은 값이 하나도 안 바뀐 실행에서도 매번 내용이 달라진다 —
`build_data.py:582,912` 가 `generated_at` 을, `price_source.py:273` 이 `captured_at` 을
무조건 새로 찍고, `render.py` 가 그 payload 를 그대로 `docs/index.html` 에 주입한다.
따라서 `git diff --cached --quiet` 는 **절대 참이 되지 않는다.** 그대로 두면 launchd 스케줄
(평일 4회 + 주말 1회 = 주 22회)마다 286KB HTML 커밋이 무기한 쌓이고 push 마다 Pages 가 재빌드된다.
→ `publish.sh` 가 **타임스탬프 `값`만 지운 사본**끼리 비교해(값 단위. `docs/index.html` 은
14KB payload 가 한 줄이라 행 단위 필터로는 실제 변경까지 가려진다) 실질 변경이 있을 때만 커밋한다.
자세한 규칙은 DEPLOY.md §C-4.

### 6-16. publish 를 건너뛰면 반드시 로그에 이유가 남는다
clone 했다면 `origin` 은 이미 붙어 있다. 그래도 Xcode CLT 미설치로 `git` 이 PATH 에 없거나
인증이 안 잡혔으면(§6-21), 대시보드는 매일 정상 빌드되는데 GitHub Pages 만 영영 갱신되지 않는다.
`run_daily.sh` 3단계가 이제 그 이유를 `[WARN] publish 생략 — ...` 로 남긴다.
`BUYBACK_PUBLISH=1` 로 강제해 놓고 git 이 없으면 사전점검이 exit 3 으로 즉시 멈춘다.

### 6-17. uninstall 은 disable 까지 건다
`launchctl bootout` 만으로는 '지금 이 부팅 세션'에서만 내려간다. plist 가
`~/Library/LaunchAgents` 에 남아 있으면 다음 로그인 때 launchd 가 다시 읽어 자동으로 되살린다.
그래서 `uninstall_launchd.sh` 는 `bootout` 뒤에 `launchctl disable` 까지 부른다.
다시 켤 때 `install_launchd.sh` 가 `bootstrap` 전에 `launchctl enable` 로 되돌리므로
재설치 경로는 그대로다. plist 파일 자체를 지우려면 `rm ~/Library/LaunchAgents/com.pjy.buyback-dashboard.daily.plist`.

### 6-18. ★ DART 인증키가 없으면 사전점검이 exit 3 으로 먼저 막는다
`dart_source` 는 키가 비어도 import 시점(`DART_KEY = _load_key()`)에는 죽지 않고
첫 API 호출의 `require_key()` 에서야 예외를 던진다. 그래서 예전에는 `.env` 를 안 만든 채 돌리면
매 실행이 `[1/2] build_data.py` 단계의 깊숙한 예외로만 실패했다.
이제 `run_daily.sh` 사전점검이 `d.DART_KEY` 가 비었는지 직접 보고 **exit 3** 으로 즉시 멈추며,
`.env` 를 확인하라는 메시지를 남긴다(§2-4). §4 체크리스트에도 같은 확인 항목을 넣어 두었다.

### 6-19. clone 직후에는 `dashboard.html` 이 없다 — 고장이 아니다
`docs/index.html` 과 내용이 같아 중복 커밋을 피하려고 `.gitignore:48` 로 뺐다. 그래서 바탕화면
바로가기·북마크를 그리로 걸어 두면 "파일을 찾을 수 없음"으로 **깨진 것처럼 보인다.**
§3-5 ③ 을 한 번 돌리면 생긴다. 그 전에는 `open docs/index.html` 로 보면 된다.
맥에서의 열람 수단(데스크톱 심볼릭 링크 / 공개 링크 북마크)은 §3-8 에서 만든다.

### 6-20. ★ 커밋 신원은 **리포 로컬** 설정이라 clone 에 안 따라온다
Windows 쪽 `user.name` / `user.email` 은 전역이 아니라 이 리포 안에만 박혀 있고
(`git config --global user.email` → 미설정), `.git/config` 는 clone 대상이 아니다.
안 하면 손으로 친 `git commit` 이 `Author identity unknown` 으로 실패한다 — 실제로 났던 오류다.
그래서 §3-4(실행 비트 커밋)는 **§3-2 이후**에 있다.

★ 더 조용한 쪽이 위험했다. 예전 `publish.sh` 는 커밋 직전에 신원이 없으면 **자동으로**
개인 계정 이름·이메일로 폴백해 커밋했다. 무인 실행은 실패하지 않고 대신
**개인 이메일이 public 리포 커밋에 영구히 박힌다.** 실증으로 재현된 경로다
(전역 config 를 비운 fresh clone + 로컬 bare origin 으로 `publish.sh` 실주행 →
`git log -1 --format='%an <%ae>'` 가 그 개인 계정으로 찍혔다).

**이번 개정에서 그 폴백을 없앴다.** 지금 `publish.sh` 는 `user.name`/`user.email` 이
둘 다 있는지 먼저 보고, 없으면 **커밋하지 않고** `[publish][ERROR] 커밋 신원이 설정되지 않았다`
로 exit 1 한다(`run_daily.sh` 는 그것을 `[WARN]` 으로 받고 죽지는 않는다).
즉 이제는 개인 메일이 박히는 대신 **그날 Pages 갱신이 빠진다** — 그래도 손해이므로
**§3-2 를 첫 실행 전에** 끝내는 것이 정답이다.

### 6-21. ★ 맥미니는 자기 git 인증이 따로 필요하다
Windows 의 인증은 그 머신 것이다(현재 `credential.helper=manager` — Windows 전용).
맥에서 `gh auth login && gh auth setup-git` 이나 SSH 키를 **새로** 잡아야 한다(§3-2, DEPLOY.md §B).
안 하면 대시보드는 매일 정상 빌드되는데 push 만 실패해 Pages 가 영영 멈춘다.
무인 실행에는 **passphrase 없는 SSH 키**가 안전하다 — launchd 는 프롬프트가 뜨면 그 실행이 멈춘다.

★ **인증 확인을 `git ls-remote origin` 으로 하면 안 된다 — 거짓 통과한다.**
이 리포는 public 이라 `ls-remote` 는 자격증명이 전혀 없어도 익명 read 로 rc 0 을 준다(실측).
같은 조건에서 `git push --dry-run` 은 `could not read Username for 'https://github.com'` 로
rc 128 이다. **검증 명령은 `git push --dry-run origin main` 을 쓸 것.**

### 6-22. `.sh` 의 실행 비트가 인덱스에 없다 (mode `100644`)
Windows 가 `core.filemode=false` 라 chmod 를 추적하지 못해 `.sh` 4개가 전부 `100644` 로 커밋됐다.
**clone 해도 실행 비트가 안 붙는다.** launchd 경로와 `run_daily.sh` 3단계는 `bash <파일>` 로
부르므로 무관하고, `./publish.sh` 처럼 직접 실행할 때만 `permission denied` 다. 고치는 법은 §3-4.

### 6-23. Pages 는 push 직후에 안 바뀐다 (빌드에 1~2분)
push 성공 ≠ 링크 갱신. 그 사이 새로고침하면 이전 내용이 보이는데 push 실패로 오인하지 말 것.
브라우저 강제 새로고침(⌘⇧R)까지 해 보고, 실제 상태는
`gh api repos/Jaey27/buyback-dashboard/pages/builds/latest --jq '.status, .error.message'` 로 본다.

---

## 7. 참고 문서

| 파일 | 내용 |
|---|---|
| `README.md` | 매일 갱신 절차, 왜 매 영업일 실행이 정확도의 전제인가, 파일 구조, 유지보수, 데이터 해석 메모 |
| `DEPLOY.md` | 배포 **운영** 문서 — 현재 배포 상태·인증 3안·`publish.sh` 동작·커밋 대상 판단표·원장 충돌 병합(§G-2)·리포 재생성(§H) |
| `_ref/FINDINGS.md` | KIND/DART/네이버 API 스펙, 실측 원본 데이터, **신청일=매매일 직전 영업일** 규칙 |
| `_ref/DART_SPEC.md` | DART 필드 스펙 |
| `.github/workflows/update.yml` | Actions 수동 백업 워크플로(버튼 전용). **현재 리포 시크릿이 없어 그대로는 실패한다** — §5 마지막 절, DEPLOY.md §G-4 |
| `_ref/DESIGN_SPEC.md` | 페이지 디자인 스펙. **리포에 없다**(`.gitignore:61` — 내용이 레퍼런스 사이트 스타일시트의 97%라 공개 재배포하지 않는다). Windows 로컬에만 있다 |

---

## 8. 이 문서에서 검증하지 않은 것 (정직하게)

- **macOS에서 실제로 실행한 것은 하나도 없다.** 맥 기본 `/bin/bash` 3.2 실동작·launchd 등록/발화·
  `plutil -lint`·TZ 반영·SSL·PEP 668 거부 여부는 전부 정적 추론이거나 Windows의 GNU bash 5.2 실행 결과다.
  (bash 4 전용 문법 — `declare -A` / `mapfile` / `readarray` / `${var^^}` / `${var,,}` — 은
  전수 검색 결과 **0건**이다. 인덱스 배열은 `publish.sh:55`(`PATHS=(`)와 `:84`(`"${PATHS[@]}"`)에서
  쓰지만 인덱스 배열은 bash 2.0 부터라 3.2 에서 문제없다. 결론(3.2 호환)은 유효하다.)
- **다만 아래는 Windows의 GNU bash 5.2에서 실제로 돌려 확인했다**(macOS 고유 부분은 여전히 미검증):
  - `.sh` 4개 `bash -n` 통과, CR=0 확인
  - 중복 실행 락 6개 케이스 — 락 없음 / 죽은 PID / pid 파일 없음 / **살아있는 무관한 PID(SKIP)** /
    **나이 초과(강제 회수)** / **부팅 식별자 불일치(강제 회수)**
  - `publish.sh` 5개 시나리오 — 빈 bare origin 최초 push / 타임스탬프만 변경(커밋 안 함) /
    14KB 한 줄 payload 안쪽의 실제 값 변경(커밋+push) / `--dry-run` / 변경 없음
  - `.gitignore` 전수 대조 — `.env`·`.env.local`·`.env.production`·`.env.bak` 전부 IGNORED,
    `.env.example` 은 통과, 커밋해야 할 13개 경로 전부 통과
  - `install_launchd.sh` 의 파이썬 경로 보정 — shim 을 넘기면 `sys.executable` 로 치환되는 것 확인
- plist는 Python `plistlib.loads()` / `xml.dom.minidom` 으로만 파싱 검증했다(16개 `StartCalendarInterval`,
  전부 integer). 맥에서 `plutil -lint` 를 한 번 돌릴 것 — 이제 `install_launchd.sh` 가 등록 전에 자동으로 돌린다.
- **macOS 전용 명령은 하나도 실행해 보지 못했다** — `launchctl bootstrap/bootout/enable/disable`,
  `plutil -lint`, `sysctl -n kern.boottime`, BSD `stat -f %m`. 스크립트는 이들이 없거나 실패해도
  죽지 않게 짜여 있다(`|| true`, 숫자 검증, 값이 비면 해당 판정을 건너뜀). 첫 설치 때 눈으로 확인할 것.
- `shellcheck` 이 개발 환경에 없어 lint를 못 돌렸다. 맥에서 `brew install shellcheck &&
  shellcheck -s bash scripts/run_daily.sh` 를 한 번 돌려볼 것.
- macOS 기본 python3(3.9.6)에서 실제로 import 되는지 실행 확인은 안 했다(정적으로는 3.7까지 내려간다).
- 18:00~18:30 사이 KIND decl 반영 지연이 있는지는 실측하지 않았다. README·FINDINGS의 '18시 이후 집계'
  기술을 근거로 18:30을 1차로 잡았다. **첫 주 운용 로그로 확인할 것.**
- **GitHub 쪽은 이제 실측이다** — 리포 생성·첫 push·Pages 활성화·HTTP 200·차트 렌더까지 Windows 에서
  확인했다. 다만 **맥에서의 clone·인증·push 는 여전히 미검증**이다(§6-21). 첫 push 는 §3-6 으로 확인할 것.
- **`publish.sh` 의 신원 가드는 이번 개정에서 새로 넣은 코드다**(폴백 이메일 제거 — §6-20).
  GNU bash 5.2 에서 "신원 없음 → exit 1, 커밋 안 함" / "신원 있음 → 정상 커밋" 두 경로를 확인했지만
  **맥에서는 아직 안 돌려 봤다.**
- launchd 무인 실행에서 gh credential helper나 키체인이 프롬프트를 띄우는지 미확인 — 그래서 SSH를 권장한다.
- 두 머신이 같은 날 원장을 써서 실제로 merge conflict 를 낸 적은 없다(§6-2). 병합 스니펫(DEPLOY.md §G-2)은
  오프라인 재현으로만 검증했다.
