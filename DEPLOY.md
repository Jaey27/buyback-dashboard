# 공개 링크 배포 운영 (GitHub Pages)

**배포는 이미 살아 있다.** 이 문서는 만드는 절차가 아니라 **운영·문제해결** 문서다.
리포를 통째로 잃었을 때의 재생성 절차만 부록 §H 에 남겨 두었다.

`dashboard.html` 은 자기완결 파일이라 파일로 전달해도 열리지만(§F), 파일은 굽는 순간의 값으로
박제된다. 매일 갱신되는 쪽이 이 링크다. 기존 `disparity-dashboard` 와 같은 패턴이다.

---

## 0. 현재 배포 상태 (2026-09-01 실측)

| 항목 | 값 |
|---|---|
| 리포 | <https://github.com/Jaey27/buyback-dashboard> · **public** · 기본 브랜치 `main` |
| 공개 URL | <https://jaey27.github.io/buyback-dashboard/> |
| Pages 소스 | `main` 브랜치 **`/docs`** · `build_type: legacy` · `https_enforced: true` |
| Pages 상태 | `status: built` · HTTP 200 · 285,024 B · 차트 3종 렌더·탭 3개 동작·콘솔 에러 0건 |
| 커밋 | 첫 커밋 `3540b1a`, 추적 파일 **31개** |
| 커밋 신원 | **리포 로컬** 설정 `Jaey27` / `Jaey27@users.noreply.github.com` (전역 미설정 — §B-0) |

(확인 명령은 §G-1.) 파이프라인은 이렇게 돈다.

| 무엇 | 어디서 | 언제 | 결과 |
|---|---|---|---|
| 수집 + 렌더 | 맥미니 `scripts/run_daily.sh` (launchd) | 평일 18:30 / 19:30 / 21:00 + 매일 08:40 | `dashboard.html`, `docs/index.html` |
| 커밋 + push | 맥미니 `publish.sh` (run_daily.sh 3단계) | **위 1·2단계가 성공했고 값이 실제로 바뀐 때만**(타임스탬프만 다르면 커밋 안 함 — §C-4) | GitHub `main` |
| 호스팅 | GitHub Pages (`main` / `/docs`) | push 후 **1~2분** | 위 공개 URL |
| 백업 | GitHub Actions | **수동 버튼만** (cron 꺼 둠) | 아래 §G-4 의 이유 |

핵심 원칙 하나만 기억하면 된다.
**`data/kind_decl_snapshots.json`(누적 원장)을 쓰는 머신은 맥미니 하나뿐이다.**
이 파일은 소급 복구가 안 되므로, 두 머신이 같이 쓰다가 충돌 해소를 잘못하면 그날 값이 영구히 사라진다.

---

## 1. 산출물이 두 벌인 이유

`render.py` 는 한 번 실행에 **같은 내용의 페이지를 두 곳에** 굽는다.

| 파일 | 용도 | git |
|---|---|---|
| `dashboard.html` | 로컬 사본. **바탕화면 바로가기가 가리키는 기존 경로** | 커밋 안 함 |
| `docs/index.html` | GitHub Pages 가 서빙하는 실제 페이지 | **커밋함** |

둘의 차이는 **stale 배너의 안내 문구 한 줄뿐**이다. 독자가 다르기 때문이다.

- 로컬 사본 → `최신화하려면 프로젝트 폴더에서 갱신 스크립트(macOS: run_daily.sh · Windows: run_daily.bat)를 실행하세요.`
- 공개 페이지 → `이 페이지는 평일 18:30(KST) 자동 갱신됩니다. 이 안내가 계속 보이면 수집이 멈춘 것입니다.`

(공개 페이지를 보는 사람은 스크립트를 돌릴 수 없다. 로컬용 문구를 그대로 내보내면
독자가 할 수 없는 일을 시키는 안내가 된다.)

관련 `render.py` 인자:

```
--docs-out PATH          docs 사본 경로 (기본 docs/index.html)
--no-docs                docs 사본을 만들지 않는다
--refresh-hint TEXT      로컬 사본 배너 안내문
--docs-refresh-hint TEXT docs 사본 배너 안내문
```

`docs/.nojekyll` 도 자동 생성된다(GitHub Pages 의 Jekyll 처리를 꺼서 `_` 로 시작하는
경로가 생겨도 그대로 서빙되게 한다).

---

## A. 맥미니가 writer 를 넘겨받기

리포도 Pages 도 이미 있다. 맥미니가 할 일은 **clone 하고, push 할 수 있게 만드는 것**뿐이다.

> ★ **순서**: clone → **§B-0(커밋 신원) → §B(인증)** → §A-3(실행 비트 커밋) → 첫 `run_daily.sh`.
> clone 직후에는 신원이 비어 있는데 `origin` 은 이미 붙어 있어서, 그 상태로 `run_daily.sh` 를
> 돌리면 3단계 `publish.sh` 가 곧바로 커밋을 시도한다(§C, §E-5). §A-3 의 `git commit` 도
> 신원이 없으면 `Author identity unknown` 으로 실패한다.
> **신원·인증을 어떤 실행보다 먼저 할 것.** 절차의 정본 순서는 MACMINI_HANDOFF.md §3 이다.

```bash
git clone https://github.com/Jaey27/buyback-dashboard.git ~/buyback-dashboard
cd ~/buyback-dashboard
git ls-files | wc -l       # 31
git remote -v              # origin  https://github.com/Jaey27/buyback-dashboard.git
git status -sb             # ## main...origin/main
```

### A-1. clone 이 가져오지 않는 것

| 없는 것 | 대처 |
|---|---|
| `.env` | 원래 리포에 없다. 맥에서 새로 만든다 — MACMINI_HANDOFF.md §2-4 |
| `dashboard.html` | `.gitignore:48`. `run_daily.sh` 한 번이면 생긴다 |
| `_ref/DESIGN_SPEC.md`, `_ref/*.html`, `_ref/raoni_api_*.json` | 남의 사이트 자산이라 제외(§D, §E-6). 파이프라인 입력이 아니다 |
| `logs/`, `data/_dart_cache/` | 부스러기. 자동 재생성 |
| **실행 비트** | `.sh` 4개가 mode `100644` 로 커밋돼 있다(Windows `core.filemode=false`) → §A-3 |
| **커밋 신원 · push 인증** | `.git/config` 와 자격증명은 clone 대상이 아니다 → **§B-0 · §B** (§A-3 보다 먼저) |

원장(`data/kind_decl_snapshots.json`)을 포함한 **운영 상태 파일 5개는 전부 clone 에 들어 있다.**
그래서 이번 이사에는 폴더 복사가 필요 없다.

### A-2. 시크릿 가드 — clone 뒤에도 한 번 확인

```bash
cd ~/buyback-dashboard
git check-ignore -v .env || echo "!!! .env 가 무시되지 않는다 - .gitignore 확인 !!!"
git grep -nIE '[0-9a-fA-F]{40}|crtfc_key=[0-9A-Za-z]{10,}|ghp_|github_pat_' \
  -- . ':(exclude)vendor' ':(exclude)*.md' || echo "OK - 키 패턴 없음"
```

`.env` 는 `.gitignore:21` 에 걸린다. 첫 커밋 전수 스캔에서 40자 hex 0건이 확인됐고,
`_ref/FINDINGS.md:12` 의 DART 키는 `<REDACTED ...>` 로 치환돼 있다. `*.md` 를 제외하는 이유는
이 문서와 MACMINI_HANDOFF.md 가 **검색 패턴 자체**를 본문에 담고 있어 자기 자신에 매칭되기 때문이다.

### A-3. 실행 비트 복구

```bash
# ★ 신원이 없으면 이 git commit 자체가 실패한다(Author identity unknown).
#   §B-0 을 이미 했으면 아래 두 줄은 생략해도 된다.
git config user.name  "Jaey27"
git config user.email "Jaey27@users.noreply.github.com"

chmod +x publish.sh scripts/*.sh
git update-index --chmod=+x publish.sh scripts/run_daily.sh \
       scripts/install_launchd.sh scripts/uninstall_launchd.sh
git commit -m "chore: mark shell scripts executable"    # §B 의 인증을 마친 뒤 push
```

> ★ 실패했을 때 git 이 안내하는 `git config --global user.email` 을 그대로 따라가면
> **개인 메일이 들어간다.** 반드시 위 noreply 값을 쓸 것(§B-0, §E-5).
> 그리고 이 커밋은 `publish.sh` 의 커밋 대상 7개 경로(§C-3)에 `.sh` 가 없으므로
> **`docs/index.html` 을 건드리지 않는다** — 이걸 push 해도 Pages 내용은 그대로다.

> launchd 경로와 `run_daily.sh` 3단계는 `bash <파일>` 로 부르므로 실행 비트 없이도 돈다.
> 막히는 건 `./publish.sh` 처럼 **직접 실행할 때뿐**이다. 인덱스에 기록해 두면 다음 머신에서는 이 단계가 사라진다.

---

## B. 신원 + 인증 — 무인 실행에서 push 가 되게 만들기

**Windows 에서 해 둔 것은 그 머신 것이다. 둘 다 맥에서 다시 해야 한다.**

### B-0. ★ 커밋 신원 (인증보다 먼저)

Windows 의 `user.name` / `user.email` 은 **전역이 아니라 리포 로컬**이다
(`git config --global user.email` → 미설정). `.git/config` 는 clone 대상이 아니므로 안 따라온다.

```bash
cd ~/buyback-dashboard
git config user.name "Jaey27"; git config user.email "Jaey27@users.noreply.github.com"
git config user.email   # 값이 나와야 한다
```

안 하면 두 가지가 일어난다.

1. 손으로 친 `git commit` 이 `Author identity unknown` 으로 실패한다(Windows 에서 실제로 났던 오류).
2. `publish.sh` 가 **커밋하지 않고 멈춘다** — `[publish][ERROR] 커밋 신원이 설정되지 않았다`
   (exit 1). `run_daily.sh` 는 그것을 `[WARN]` 으로 받고 죽지는 않지만, **그날 Pages 갱신은 통째로 빠진다.**

> ★ **예전에는 2번이 더 나빴다.** `publish.sh` 는 신원이 없으면 개인 계정 이름·이메일로
> **조용히 폴백해 커밋했고**, 그 값이 public 리포 히스토리에 영구히 박혔다(되돌리기 어렵다).
> 이번 개정에서 그 폴백을 제거하고 위의 '멈춤'으로 바꿨다(§C-5, §E-5).
> 그래도 **§B-0 을 첫 실행보다 먼저** 하는 것이 정답이다 — 안 하면 그날 갱신을 잃는다.

### B-1. 인증 방식 셋

launchd 는 로그인 셸이 아니다. **대화형 프롬프트가 뜨면 그 실행은 그냥 멈춘다.**
현재 `origin` 은 HTTPS 다. 세 가지 중 하나를 고르면 된다.

| 방식 | 무인 실행 | 만료 | 비고 |
|---|---|---|---|
| **SSH 키 (권장)** | 안정적 | 없음 | passphrase 없는 키면 프롬프트가 원천적으로 없다 |
| `gh auth` + credential helper | 대체로 됨 | 토큰 갱신됨 | 키체인 잠금 상태에 따라 프롬프트가 뜰 수 있다 |
| PAT (fine-grained) | 됨 | **있음(최대 1년)** | 만료되면 조용히 push 만 실패한다 |

### B-2. SSH (권장)

```bash
ssh-keygen -t ed25519 -C "macmini-buyback" -f ~/.ssh/id_ed25519_gh -N ""
gh ssh-key add ~/.ssh/id_ed25519_gh.pub --title "macmini-buyback"

cat >> ~/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_gh
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# 리모트를 SSH 로 전환
cd ~/buyback-dashboard
git remote set-url origin "git@github.com:$(gh api user --jq .login)/buyback-dashboard.git"

# 검증 (known_hosts 등록까지 여기서 끝내 둔다 - 무인 실행에서 물어보지 않게)
ssh -o StrictHostKeyChecking=accept-new -T git@github.com   # "successfully authenticated" 나오면 성공
git push --dry-run origin main && echo "PUSH 인증 OK"
```

> `-N ""` 는 passphrase 없는 키다. 맥미니 로컬 디스크에만 있고 권한이 `600` 이면
> 무인 배치용으로 통용되는 선택이다. passphrase 를 걸면 launchd 실행 때마다 막힌다.

### B-3. gh auth (간편)

```bash
gh auth login          # 대화형, 1회
gh auth setup-git      # git 이 gh 토큰을 쓰게 한다
git push --dry-run origin main && echo "PUSH 인증 OK"
```

> ★ **`git ls-remote origin` 으로 확인하지 마라 — 거짓 통과한다.** 이 리포는 public 이라
> `ls-remote` 는 자격증명이 하나도 없어도 익명 read 로 rc 0 을 준다(실측: 전역 config·credential
> helper 를 비운 상태에서 `refs/heads/main 3540b1a...` 정상 출력). 같은 조건에서
> `git push --dry-run` 은 `could not read Username for 'https://github.com'` 로 rc 128 이다.
> **push 능력을 검증하는 명령은 `git push --dry-run` 뿐이다.**

### B-4. PAT

GitHub → Settings → Developer settings → **Fine-grained token**
→ Repository access: `buyback-dashboard` 하나만, Permissions: **Contents: Read and write**

```bash
git config --global credential.helper osxkeychain
git push        # 1회: username=Jaey27, password=<PAT> 입력 → 키체인에 저장됨
```

> 만료일을 캘린더에 적어 둘 것. 만료되면 페이지가 조용히 멈춘다(로컬 데이터는 계속 쌓인다).

### B-5. launchd 환경에서 실제로 되는지 확인

```bash
launchctl kickstart -k "gui/$(id -u)/com.pjy.buyback-dashboard.daily"
sleep 60
tail -40 ~/buyback-dashboard/logs/run_*.log | tail -40
```

로그 끝에 `[3/3] publish.sh` 와 `[publish] 완료` 가 보이면 끝이다.

---

## C. 자동 push 는 어떻게 도는가 (`publish.sh`)

`scripts/run_daily.sh` 는 **1단계(수집) → 2단계(렌더) 가 모두 성공한 뒤에만** 3단계로
`publish.sh` 를 부른다. 즉 **빌드가 실패한 날은 push 자체가 없다.**

`publish.sh` 의 규칙:

1. **시크릿 가드** — `.env` 가 추적되고 있으면 즉시 중단(exit 1).
2. `git pull --rebase --autostash` 로 원격을 먼저 반영.
   단 **원격에 브랜치가 아직 없으면 pull 을 건너뛴다** — 웹 UI 로 빈 리포를 만들고
   `git remote add origin` 만 한 상태에서는 `couldn't find remote ref main` 으로
   첫 실행이 통째로 죽기 때문이다(`git ls-remote --exit-code --heads origin <브랜치>` 로 판정).
   그 경우 6항의 `origin/<브랜치>..HEAD` 계산도 무의미하므로 `git push -u origin <브랜치>` 를 강제한다.
   **지금은 `origin/main` 이 이미 존재하므로 이 분기를 타지 않는다** — §H 로 리포를 재생성했을 때만 쓰인다.
3. **명시한 경로만** 스테이징한다(작업 중이던 딴 파일이 딸려 올라가지 않게):
   `docs/index.html`, `docs/.nojekyll`, `data/buyback.json`,
   `data/kind_decl_snapshots.json`, `data/kind_decl_backfill.json`,
   `data/holidays_kr.json`, `data/dart_snapshot.json`
4. **실질 변경이 있을 때만 커밋한다.**
   ★ 여기서 `git diff --cached --quiet` 만 보면 안 된다. 커밋 대상 파일은 값이
   하나도 안 바뀐 실행에서도 매번 내용이 달라지기 때문이다 —
   `build_data.py:582,912` 가 `generated_at` 을, `price_source.py:273` 이
   `captured_at` 을 무조건 새로 찍고, `render.py` 가 그 payload 를 그대로
   `docs/index.html` 에 주입한다. 그대로 두면 launchd 스케줄(평일 4회 + 주말 1회
   = 주 22회)이 돌 때마다 286KB 짜리 HTML 커밋이 무기한 쌓이고 push 마다
   Pages 가 재빌드된다.
   → 그래서 `publish.sh` 는 **타임스탬프 `값`만 지운 사본**끼리 비교해
   (`generated_at` / `captured_at` / `fetched`), 그것마저 같으면 커밋하지 않고
   `git reset` 으로 스테이징을 되돌린다. 값이 실제로 바뀐 실행에서만 커밋되며,
   그 커밋이 그동안 밀린 타임스탬프 변경까지 함께 가져간다.
   (행 단위가 아니라 **값 단위**로 지운다. `docs/index.html` 은 14KB payload 가
   통째로 한 줄이라 행 단위 필터로는 실제 변경까지 가려진다.)
5. **커밋 직전 — 커밋 신원이 없으면 커밋하지 않고 멈춘다(exit 1).**
   예전에는 여기서 개인 계정 이름·이메일로 조용히 폴백했는데, 그러면 신원을 안 잡은
   머신의 무인 실행이 **개인 이메일을 public 리포 히스토리에 영구히** 박는다.
   지금은 `[publish][ERROR] 커밋 신원이 설정되지 않았다` 로 멈춘다(→ §B-0 을 먼저 하라는 뜻).
   `run_daily.sh` 는 이 실패를 `[WARN]` 으로 받고 죽지는 않지만, **그날 Pages 갱신은 빠진다.**
6. **밀린 커밋이 있으면 push 한다.** "커밋했을 때만 push" 로 짜면, 커밋은 됐는데
   네트워크로 push 만 실패한 날 이후로 영영 push 를 안 하게 된다.
   그래서 `origin/main..HEAD` 가 비어 있지 않은지로 판단한다.
7. push 가 실패하면 `pull --rebase` 후 1회 재시도.

수동 실행:

```bash
cd ~/buyback-dashboard
./publish.sh --dry-run   # 무엇이 올라갈지만 보여준다 (커밋/푸시 안 함)
./publish.sh             # 실제 커밋 + push
```

끄기: launchd plist 나 셸에서 `BUYBACK_PUBLISH=0`
강제(리포 감지 실패해도 실행): `BUYBACK_PUBLISH=1`

---

## D. 무엇을 커밋하고 무엇을 빼는가

판단 기준은 하나다. **잃어버리면 되돌릴 수 없는 것은 커밋한다.**

| 경로 | 커밋 | 근거 |
|---|:--:|---|
| `data/kind_decl_snapshots.json` | ✅ **필수** | 매 영업일 누적되는 **실측 원장**. KIND 는 과거 시점의 체결금액누계를 다시 주지 않으므로 **소급 복구가 불가능**하다. 머신이 바뀌어도 이게 따라가야 정확도가 유지된다. 원격에 사본이 있다는 것 자체가 백업이다 |
| `data/kind_decl_backfill.json` | ✅ | 가동 이전 구간(2026-08-20~08-28) 백필. 정적 파일이고 재수집 경로가 없다 |
| `data/holidays_kr.json` | ✅ | KRX 휴장일 캘린더. `short_sessions` 는 **수동 관리 항목**이라 재생성으로 복구되지 않는다 |
| `data/buyback.json` | ✅ | 렌더 입력. 네트워크 없이 재렌더·디버그하려면 필요. 20KB |
| `data/dart_snapshot.json` | ✅ | DART 취득결정 원문 요약. 숫자 교차검증의 근거 |
| `docs/index.html`, `docs/.nojekyll` | ✅ | Pages 가 서빙하는 실물 |
| `vendor/chart.umd.min.js` | ✅ | Chart.js v4.4.0 (MIT). 외부 요청 0건 자기완결의 전제 |
| `scripts/`, `*.bat`, `*.sh`, `README.md`, `_ref/FINDINGS.md`, `_ref/DART_SPEC.md` | ✅ | 코드와 **우리가 직접 쓴** 문서 |
| **`.env`** | ❌ **절대 금지** | DART OpenAPI 키. 한 번 커밋하면 히스토리에 영구히 남는다 |
| `dashboard.html` | ❌ | `docs/index.html` 과 내용이 같다. 둘 다 커밋하면 매일 286KB×2 가 쌓인다. **clone 직후에만 없고 `run_daily` 한 번이면 생긴다** — 바탕화면 바로가기가 깨진 것처럼 보여도 고장이 아니다 |
| `data/_dart_cache/` | ❌ | DART 원문 캐시. 용량만 크고 키만 있으면 재수집된다 |
| `_ref/*.html`, `_ref/raoni_api_*.json` | ❌ | 역설계용으로 **남의 사이트를 통째로 받아둔 사본**. 공개 리포에 재배포할 이유가 없다 |
| **`_ref/DESIGN_SPEC.md`** | ❌ | 형식은 우리가 쓴 스펙 문서지만 내용이 **레퍼런스 사이트 스타일시트의 97%**(유의미 111줄 중 108줄)를 그대로 옮긴 것이라 사실상 남의 CSS 재배포다. `.gitignore:61`. 로컬에는 남겨 둔다 |
| `logs/`, `__pycache__/`, `.DS_Store`, `.run_daily.lock/` | ❌ | 부스러기 |

### 실수로 `.env` 를 올렸다면

**히스토리 정리보다 키 재발급이 먼저다.** 공개 리포에 한 번 올라간 키는 이미 노출된 것으로 취급한다.

```bash
# 1) DART 사이트에서 인증키 재발급 (이게 진짜 대응)
# 2) 그 다음 히스토리에서 제거
git rm --cached .env && git commit -m "chore: drop .env" && git push
# 과거 커밋에서도 지우려면 git-filter-repo 필요 (강제 push → 협업자 있으면 조율)
```

### 리포 용량

`docs/index.html` 은 커밋된 blob 기준 **285,024 바이트**다(Windows 로컬 파일은 CRLF 라 286,070 B —
`.gitattributes` 가 add 시점에 LF 로 정규화한다. 맥에서는 애초에 LF 로 써서 차이가 없다).
이 중 205KB 는 매일 동일한
Chart.js 번들이라 git 델타 압축이 잘 먹는다. 영업일 250일 기준 **연간 수십 MB 수준**으로
예상한다(측정치가 아니라 추정이다). GitHub 권장 리포 상한 1GB, Pages 사이트 상한 1GB에
비하면 여유가 크다. 몇 년 뒤 부담되면 `git gc --aggressive` 또는 히스토리 절단을 고려한다.

---

## E. public 으로 올린 판단 — 근거와 남은 확인

**이미 public 으로 올렸다.** 아래는 그 판단의 근거이고, 3~5 는 계속 유효한 주의사항이다.

### 근거

페이지에 들어가는 값은 전부 **공개 공시·공개 시세**다.

- KRX KIND 자기주식 신고/신청/체결 내역
- DART 자기주식 취득결정 공시
- 네이버 금융 일봉

커밋 대상 **31개 파일** 전수 스캔 결과 **DART 키 패턴(40자 hex) 0건, `crtfc_key=값` 0건,
GitHub/AWS/OpenAI 토큰 패턴 0건**이었다(유일한 40-hex 매칭은 이 문서와 MACMINI_HANDOFF.md 안의
**검색 패턴 문자열 자체**다). `_ref/FINDINGS.md:12` 의 키는 `<REDACTED ...>` 로 바뀌어 있다.

### 그래도 짚어야 할 것

1. **private 리포로 해도 Pages 사이트 자체는 공개다.** 리포를 숨긴다고 페이지가 숨겨지지 않는다.
   URL 을 아는 사람은 누구나 본다(접근 제어가 붙은 Pages 는 Enterprise 기능이다).
2. **GitHub Free 플랜은 public 리포에서만 Pages 를 켤 수 있다.** private 리포에서 Pages 를
   쓰려면 **Pro 이상 유료 플랜**이 필요하다(현 시점 정책 기준 — 켜지지 않으면 이 이유다).
   즉 "코드는 숨기고 링크만 공개" 는 유료이고, 그렇게 해도 링크는 여전히 공개다.
3. **히스토리는 영구다.** 첫 커밋은 이미 났다. 앞으로 새 파일을 추가할 때마다
   §A-2 스캔을 한 번 돌릴 것 — 되돌리는 비용이 비대칭이다.
4. **로컬 절대경로에 윈도우 계정명이 남아 있다**(`C:\Users\pjy09\...` — README·스크립트·`_ref/*.md`
   합쳐 8곳). 시크릿은 아니지만 계정명이 이미 공개돼 있다. 신경 쓰이면 지금이라도 치환하라.
5. **커밋 이메일 — 처리 완료.** 첫 커밋은 noreply 로 냈고, `publish.sh` 의
   개인 Gmail 주소 폴백은 **제거했다.** 이제 신원이 없으면 커밋하지 않고
   `[publish][ERROR] 커밋 신원이 설정되지 않았다` 로 멈춘다(§C-5).
   남은 것은 운영 습관뿐이다 — **새 머신에서는 §B-0 을 첫 실행보다 먼저** 할 것.
   (그러지 않으면 개인 메일이 박히는 대신 그날 Pages 갱신이 통째로 빠진다.)
6. **남의 자산은 빼고 올린다.** `_ref/raoni_*.html`, `_ref/kind_treasury_form.html`,
   `_ref/raoni_api_*.json`, **`_ref/DESIGN_SPEC.md`** 는 정찰용으로 받아뒀거나 남의 스타일시트를
   그대로 옮긴 것이다. `.gitignore:54-61` 로 제외했다. 우리가 직접 쓴
   `_ref/FINDINGS.md` · `_ref/DART_SPEC.md` 만 올라간다.
7. **시세 데이터 재배포.** 네이버 금융 일봉에서 파생된 값이 페이지에 실린다. 개인이 만든 무료
   대시보드 수준에서 문제 삼는 경우는 드물지만, 원본 시세를 그대로 대량 재배포하는 형태는
   피하는 게 안전하다(현재는 파생 지표만 싣는다).
8. **투자 판단 면책.** 남이 보는 링크가 되는 순간 성격이 달라진다. 페이지 하단이나 README 에
   "공개 공시 기반 참고자료이며 투자 판단의 책임은 이용자에게 있다" 정도는 넣어 두는 게 좋다.
9. **Chart.js 라이선스.** MIT 이고 번들 상단에 원본 고지가 포함돼 있다. 그대로 두면 된다.
10. **검색 노출을 줄이고 싶다면** `docs/robots.txt` 를 추가하면 된다(차단이 아니라 요청일 뿐이다):
    ```bash
    printf 'User-agent: *\nDisallow: /\n' > docs/robots.txt
    ```

### 결론

**public 리포 + Pages** 로 갔다. 데이터가 전부 공개 공시라 숨길 실익이 없고,
private 은 유료인데다 어차피 페이지는 공개된다. §E-5(폴백 이메일)는 코드에서 제거해 닫았다.
남은 것은 §E-4(로컬 절대경로의 계정명)와 §E-8(면책 문구) 정도로, 둘 다 선택 사항이다.

---

## F. HTML 파일을 그냥 전달하면 어떻게 되나

### 열린다. 서버도 인터넷도 필요 없다

`docs/index.html` 을 실제로 검사한 결과다.

| 항목 | 값 |
|---|---|
| `src="http…"` / `href="http…"` / `<link>` / `<img>` | **0건** |
| `fetch(` / `XMLHttpRequest` / `@import` | **0건** |
| 파일 크기 | 285,024 바이트 (약 278KB) — Pages 응답 `Content-Length` 로 확인 |

CSS·Chart.js(205KB)·데이터(JSON)가 전부 파일 안에 인라인돼 있다. 더블클릭하면
`file://` 로 그대로 렌더된다. 오프라인에서도, 회사 방화벽 안에서도 열린다.

### 대신 데이터가 굽는 시점으로 박제된다

파일은 스스로 갱신되지 않는다(`file://` 에서는 `fetch` 가 막혀 있어 애초에 불가능하다).
그래서 **페이지가 열릴 때마다 스스로 신선도를 계산해 배너를 띄운다.**

브라우저에서 `Asia/Seoul` 기준 오늘을 구하고, 데이터 기준일(`as_of`)과의 사이에 낀
**거래일 수**(주말·`holidays_kr.json` 공휴일 제외)를 센다.

| 경과 | 표시 |
|---|---|
| 0거래일 | 배너 없음 |
| 1거래일 | 노란 배너 `전일 기준 데이터입니다.` + 상단 칩 `전일 기준` |
| 2거래일 이상 | 빨간 배너 `⚠ 데이터가 N거래일 지났습니다 — 지금 보이는 수치는 현재 값이 아닙니다.` + 칩 `N거래일 경과` |

배너에는 항상 `기준일 YYYY-MM-DD · 오늘(서울) YYYY-MM-DD` 이 함께 찍힌다.
**즉 받은 사람이 3개월 뒤에 열어도 낡은 값을 현재 값으로 오해하지 않는다.** 이게 파일 전달의
가장 큰 위험이었고, 그 부분은 막혀 있다.

(빌드 시점에도 `render.py --max-age-days 4` 가 같은 검사를 해서 콘솔에 경고를 남긴다.)

### 카톡·메일로 보낼 때

- 크기 278KB — 첨부 제한에는 전혀 안 걸린다.
- 다만 **메신저·웹메일이 `.html` 첨부를 미리보기로 열지 못하거나 아예 차단하는 경우가 있다.**
  (피싱 방지로 HTML 첨부를 막는 서비스가 있다.) 안 열린다고 하면 `.zip` 으로 싸거나 링크를 줘라.
- 모바일에서 파일로 열면 브라우저가 아니라 뷰어 앱이 잡아서 깨져 보일 수 있다.
- **결정적으로, 파일은 그 순간의 사본이다.** 상대가 계속 최신을 보길 원하면 파일이 아니라
  **링크(<https://jaey27.github.io/buyback-dashboard/>)를 줘라.** 링크는 맥미니가
  매일 갱신하고, 배너 문구도 "평일 18:30 자동 갱신" 으로 나간다.

---

## G. 운영 메모

### G-1. 페이지가 갱신되지 않을 때 (위에서부터 확인)

```bash
cd ~/buyback-dashboard
tail -60 "$(ls -t logs/run_*.log | head -1)"     # 1) 오늘 실행이 있었나, 어디서 멈췄나
git log --oneline -5                              # 2) 커밋이 되고 있나
git status -sb                                    # 3) 로컬이 origin 보다 앞서 있나(=push 실패)
git config user.email                             # 4) 신원이 비었으면 §B-0
git push --dry-run origin main                    # 5) 프롬프트가 뜨면 §B — 무인 실행은 여기서 멈춘다
                                                  #    (ls-remote 는 public 리포라 익명으로도 통과한다)
gh api repos/Jaey27/buyback-dashboard/pages/builds/latest --jq '.status, .error.message'
```

- `[3/3] publish.sh` 가 로그에 없다 → `BUYBACK_PUBLISH=0` 이거나 `git` 이 PATH 에 없다.
- 커밋은 쌓이는데 3)이 `ahead N` → **push 인증 문제**(§B). 맥에서 새로 잡았는지 볼 것.
- 커밋·push 는 됐는데 링크가 그대로 → **Pages 빌드에 1~2분.** 6)이 `building` 이면 기다리고,
  `errored` 면 `.error.message` 를 볼 것. 브라우저 강제 새로고침도 해 볼 것.

### G-2. `data/kind_decl_snapshots.json` 이 충돌했을 때

**절대 한쪽을 통째로 버리지 마라.** 두 파일은 서로 다른 날짜를 갖고 있을 수 있고,
버린 쪽의 날짜는 영구히 추정치로 떨어진다. 합집합으로 병합한다.

```bash
cd ~/buyback-dashboard
# :2 / :3 은 충돌한 두 버전이다. rebase 중에는 ours/theirs 의 의미가 뒤집히지만
# 아래 병합은 대칭이라(양쪽 날짜를 다 살리고 captured_at 이 늦은 쪽을 채택) 상관없다.
git show :2:data/kind_decl_snapshots.json > /tmp/side_a.json
git show :3:data/kind_decl_snapshots.json > /tmp/side_b.json
python3 - <<'EOF'
import json
a = json.load(open("/tmp/side_a.json"))
b = json.load(open("/tmp/side_b.json"))
for key, dates in b.items():
    slot = a.setdefault(key, {})
    for d, v in dates.items():
        # 같은 (프로그램, as_of) 가 양쪽에 있으면 나중에 찍은 것을 쓴다(더 정확한 집계)
        if d not in slot or v.get("captured_at", "") > slot[d].get("captured_at", ""):
            slot[d] = v
json.dump(a, open("data/kind_decl_snapshots.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, sort_keys=True)
print("merged keys:", len(a))
EOF
git add data/kind_decl_snapshots.json && git rebase --continue
```

### G-3. 시간·시각을 바꾸려면

- 맥미니 스케줄: `scripts/install_launchd.sh` 의 시각을 고치고 다시 실행(교체 등록).
- 배너 문구: `render.py --docs-refresh-hint "..."` 또는 `run_daily.sh` 의 `REFRESH_HINT`.

### G-4. GitHub Actions 를 스케줄로 돌리지 않는 이유

`.github/workflows/update.yml` 은 **`workflow_dispatch`(수동 버튼)만** 켜져 있다.

1. **누적 원장의 writer 는 하나여야 한다.** 두 머신이 같은 날 `kind_decl_snapshots.json` 을
   쓰면 rebase 충돌이 나고, 해소를 잘못하면 그날의 실측값이 사라진다. 되돌릴 방법이 없다.
2. **러너는 미국 IP다.** KIND/DART/네이버는 한국 IP 를 전제로 굴러간다. 차단되거나 다른 응답이
   올 수 있고, 그 결과가 원장에 들어가면 조용히 오염된다.
3. 맥미니는 이미 **하루 4번**(18:30 / 19:30 / 21:00 / 다음날 08:40) 재시도한다. 한 번 실패로
   그날 값을 잃는 구조가 아니다.

맥미니가 며칠 죽어 있었던 게 확실할 때만 Actions 탭에서 수동 실행한다.

> ★ **현재 이 리포에는 시크릿이 하나도 없다**(`gh secret list --repo Jaey27/buyback-dashboard`
> → 빈 출력). 워크플로 Build 스텝은 `DART_API_KEY: ${{ secrets.DART_API_KEY }}` 에 의존하므로,
> 지금 `Run workflow` 를 누르면 키가 빈 문자열이 되어 `require_key()` 의 `DartError` 로
> **반드시 실패한다.** 즉 이 복구 경로는 아래를 먼저 하기 전까지 쓸 수 없다.

```bash
gh secret set DART_API_KEY --repo Jaey27/buyback-dashboard   # 프롬프트에 키를 붙여넣는다
                                                             # (--body 로 주면 셸 히스토리에 남는다)
gh api -X PUT "repos/$(gh api user --jq .login)/buyback-dashboard/actions/permissions/workflow" \
  -f default_workflow_permissions=write
gh workflow run "Update dashboard (manual backup)"
```

> ★ Actions 를 돌린 뒤에는 **맥미니에서 `git pull --rebase` 를 먼저** 하고 `run_daily.sh` 를
> 돌려라. 안 그러면 다음 push 때 원장이 충돌한다(→ G-2).

### G-5. 줄바꿈

`.gitattributes` 가 `*.sh` 를 LF 로 고정한다. Windows 의 `core.autocrlf=true` 를 거쳐 CRLF 로
체크아웃되면 맥에서 `bad interpreter: /bin/bash^M` 로 죽기 때문이다.
반대로 `*.bat` 은 CRLF 로 고정한다(cmd.exe 가 배치 파일을 바이트 오프셋으로 다시 읽는다).

**그래서 clone 경로에는 줄바꿈 문제가 없다.** `^M` 은 clone 대신 AirDrop/USB/복붙으로 옮겼을 때만 나온다.
같은 정규화 때문에 로컬 파일 크기와 커밋된 blob 크기가 다를 수 있다(§D 리포 용량).

---

## H. 부록 — 리포를 통째로 잃었을 때 재생성

리포를 지웠거나 접근이 막힌 경우에만 쓴다. **평소에는 §A.**
(`publish.sh` 가 `여기는 git 리포가 아니다` / `origin 리모트가 없다` 로 죽으면서 이 절을
가리키는 경우가 그것이다.)
작업 트리(특히 `data/kind_decl_snapshots.json`)가 살아 있는 머신에서 실행할 것.

```bash
cd ~/buyback-dashboard && git init -b main 2>/dev/null || true

# 프리플라이트 — 한 번 커밋되면 히스토리에 영구히 남는다
git check-ignore -v .env || { echo "!!! .env 가 무시되지 않는다 - 멈춰라 !!!"; exit 1; }
git add -A && git status --porcelain | sort        # 올라갈 목록을 눈으로 확인
git diff --cached -- . ':(exclude)vendor' ':(exclude)*.md' \
  | grep -nE '[0-9a-fA-F]{40}|crtfc_key=[0-9A-Za-z]{10,}|ghp_|github_pat_' \
  && echo "!!! 위 라인을 확인하라 !!!" || echo "OK - 키 패턴 없음"

git update-index --chmod=+x publish.sh scripts/*.sh
git config user.name "Jaey27"; git config user.email "Jaey27@users.noreply.github.com"
git commit -m "init: buyback dashboard pipeline + docs/"
gh repo create buyback-dashboard --public --source=. --remote=origin --push
gh api -X POST repos/Jaey27/buyback-dashboard/pages \
  -f "source[branch]=main" -f "source[path]=/docs"
```

`gh` 가 없으면 `brew install gh && gh auth login`. API 로 Pages 켜기가 실패하면 웹에서
**Settings → Pages → Source: `main` / `/docs` → Save**. 확인은 §G-1.
