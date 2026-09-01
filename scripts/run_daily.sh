#!/bin/bash
# ---------------------------------------------------------------------------
#  buyback-dashboard : 매일 갱신 엔트리포인트 (macOS / Linux)
#  run_daily.bat 의 macOS 판. 동작·순서·가드는 .bat 과 100% 동일하게 유지할 것.
#
#   1) scripts/build_data.py : KIND + DART + 네이버 -> data/buyback.json
#                              불변식 게이트 실패 -> exit 2 -> 여기서 중단(render 안 함)
#   2) scripts/render.py     : buyback.json        -> dashboard.html (+ docs/index.html)
#
#  ★ 1단계 종료코드 가드는 반드시 있어야 한다. 없으면 수집이 실패해도 2단계가
#    낡은 buyback.json 을 읽어 '겉보기 멀쩡한' 페이지를 찍는다(현재 값이 아닌데
#    현재 값처럼 보인다).
#
#  ★ 평일 18:00(KST) 이후에 돌려야 한다. KIND 는 당일 체결분을 18시 이후에 집계하고,
#    그날의 정확한 체결금액은 decl '체결금액누계' 스냅샷의 전일 대비 차분으로만 얻는다
#    (data/kind_decl_snapshots.json). 거른 날은 그 날짜만 영구히 추정치로 떨어지며
#    나중에 소급 복구할 수 없다.
#
#  환경변수
#    BUYBACK_PYTHON   쓸 파이썬 (기본 python3). launchd plist 가 절대경로로 넣어준다.
#    SKIP_IF_HOLIDAY  1 이면 KRX 휴장일(주말·공휴일)에는 아무것도 하지 않고 exit 0.
#                     기본 0 = 휴장일에도 실행(무해한 no-op 이며, 전날 값을 다시
#                     스냅샷해 두는 복구 기회가 되므로 기본은 끄지 않는다).
#    BUYBACK_MAX_AGE  render.py --max-age-days (기본 4)
#    BUYBACK_TZ       타임존 (기본 Asia/Seoul). ★ KST 가 아니면 '오늘'이 어긋난다.
#    BUYBACK_LOG_KEEP logs/run_*.log 보관 일수 (기본 60)
#    REFRESH_HINT     페이지 stale 배너 안내문 (미지정이면 render.py 기본값)
#    BUYBACK_NO_LOCK  1 이면 중복 실행 락을 쓰지 않는다(수동 디버깅용)
#    BUYBACK_LOCK_MAX_MIN  락을 강제 회수하는 나이(분, 기본 120). PID 가 살아 있어도
#                     이보다 오래된 락은 '재사용된 PID' 로 보고 빼앗는다.
#    BUYBACK_PUBLISH  auto(기본) = git 리포이고 origin 이 있으면 성공 후 publish.sh 로
#                     docs/index.html + 누적 원장을 GitHub 에 push (Pages 갱신).
#                     0 = 하지 않음 · 1 = 강제. 자세한 내용은 DEPLOY.md.
#
#  종료코드: 0 정상/휴장일 skip/중복실행 skip · 1 build 실패 · 2 render 실패
#            · 3 사전점검 실패
# ---------------------------------------------------------------------------
set -euo pipefail

# ---- 위치 확정 -------------------------------------------------------------
# cron/launchd 는 임의의 cwd 로 띄운다. 심볼릭 링크로 걸어도 실제 위치로 내려간다.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_DIR"

PY="${BUYBACK_PYTHON:-python3}"
MAX_AGE="${BUYBACK_MAX_AGE:-4}"
LOG_DIR="$PROJECT_DIR/logs"
LOG_KEEP="${BUYBACK_LOG_KEEP:-60}"
LOCK_DIR="$PROJECT_DIR/.run_daily.lock"
LOCK_MAX_MIN="${BUYBACK_LOCK_MAX_MIN:-120}"

# ★ 파이프라인의 '오늘'은 KST 여야 한다. build_data.py 는 자체 KST 를 쓰지만
#   price_source.fetch_exec_detail() 과 render.py 의 stale 판정은 시스템 로컬
#   date.today() 를 쓴다. 맥미니 TZ 가 KST 가 아니면 하루 어긋난다.
export TZ="${BUYBACK_TZ:-Asia/Seoul}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export PYTHONUTF8="${PYTHONUTF8:-1}"

mkdir -p "$LOG_DIR"

# launchd 의 StandardOutPath/StandardErrorPath 는 무한히 append 된다.
# 주 5회 × 4시각이면 1년에 1,000회가 넘으므로 10MB 를 넘으면 잘라낸다.
for f in "$LOG_DIR/launchd.out.log" "$LOG_DIR/launchd.err.log"; do
  if [ -f "$f" ] && [ "$(wc -c <"$f" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    : >"$f"
  fi
done

# 실행 1회당 로그 1개. 화면(launchd 로그)과 파일 양쪽으로 흘린다.
RUN_LOG="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$RUN_LOG") 2>&1

stamp() { date "+%Y-%m-%d %H:%M:%S %Z"; }

echo "============================================"
echo "[$(stamp)] buyback-dashboard update"
echo "  project : $PROJECT_DIR"
echo "  python  : $PY ($("$PY" -V 2>&1 || echo 'NOT FOUND'))"
echo "  TZ      : $TZ"
echo "  log     : $RUN_LOG"
echo "============================================"

# ---- 중복 실행 락 ----------------------------------------------------------
# macOS 에는 util-linux 의 flock(1) 이 없다. mkdir 은 APFS/HFS+ 에서 원자적이므로
# 디렉터리 생성 성공 여부를 락으로 쓴다.
#
# ★ PID 만으로 판정하면 안 된다. SIGKILL/정전으로 락이 남은 뒤 그 PID 번호를
#   무관한 프로세스가 재사용하면, 이후 모든 실행이 "이미 실행 중"으로 보고
#   exit 0 으로 조용히 건너뛴다 — launchd 도 실패로 보지 않으므로 파이프라인이
#   영구히 멈추고, 이 프로젝트에서 하루를 거르면 그 날짜는 영영 추정치가 된다.
#   그래서 회수 판정을 3중으로 둔다.
#     (1) PID 가 죽었다            → 회수
#     (2) 락을 잡은 부팅과 지금 부팅이 다르다(재부팅 이후 남은 락) → 회수
#     (3) 락 나이가 BUYBACK_LOCK_MAX_MIN 분을 넘었다 → PID 가 살아 있어도 회수
#   정상 실행은 길어야 수 분이므로 (3) 의 기본 120분은 안전한 여유다.

# 부팅 식별자 — 재부팅 이후의 PID 재사용을 배제하는 데 쓴다.
#   macOS: sysctl kern.boottime · Linux: /proc/stat 의 btime · 둘 다 없으면 빈 문자열
boot_id() {
  sysctl -n kern.boottime 2>/dev/null \
    || awk '/^btime/{print $2}' /proc/stat 2>/dev/null \
    || true
}

# 락 디렉터리의 나이(분). 알 수 없으면 -1.
#   stat 은 BSD(-f %m) 와 GNU(-c %Y) 의 문법이 다르므로 둘 다 시도한다.
lock_age_min() {
  local m now
  # BSD(macOS) 먼저. GNU stat 은 -f 를 '파일시스템 정보'로 해석해 엉뚱한 문자열을
  # stdout 으로 흘리므로, 숫자가 아니면 GNU 문법으로 다시 시도한다.
  m="$(stat -f %m "$LOCK_DIR" 2>/dev/null || true)"
  case "$m" in ''|*[!0-9]*) m="$(stat -c %Y "$LOCK_DIR" 2>/dev/null || true)" ;; esac
  case "$m" in ''|*[!0-9]*) echo -1; return 0 ;; esac
  now="$(date +%s)"
  echo $(( (now - m) / 60 ))
}

if [ "${BUYBACK_NO_LOCK:-0}" != "1" ]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    OLD_PID=""
    OLD_BOOT=""
    if [ -f "$LOCK_DIR/pid" ]; then
      OLD_PID="$(sed -n 1p "$LOCK_DIR/pid" 2>/dev/null || true)"
      OLD_BOOT="$(sed -n 2p "$LOCK_DIR/pid" 2>/dev/null || true)"
    fi
    NOW_BOOT="$(boot_id)"
    AGE_MIN="$(lock_age_min)"

    STEAL=""
    if [ -z "$OLD_PID" ]; then
      STEAL="pid 파일이 없다"
    elif ! kill -0 "$OLD_PID" 2>/dev/null; then
      STEAL="pid $OLD_PID 가 죽어 있다"
    elif [ -n "$NOW_BOOT" ] && [ -n "$OLD_BOOT" ] && [ "$NOW_BOOT" != "$OLD_BOOT" ]; then
      STEAL="재부팅 이전에 잡힌 락이다 (pid $OLD_PID 는 재사용된 번호다)"
    elif [ "$AGE_MIN" -ge 0 ] && [ "$AGE_MIN" -ge "$LOCK_MAX_MIN" ]; then
      STEAL="락이 ${AGE_MIN}분째 잡혀 있다 (한도 ${LOCK_MAX_MIN}분). pid $OLD_PID 는 살아 있으나 무관한 프로세스로 본다"
    fi

    if [ -z "$STEAL" ]; then
      echo "[$(stamp)] [SKIP] 이미 실행 중이다 (pid $OLD_PID, 락 ${AGE_MIN}분 경과). 이번 실행은 건너뛴다."
      exit 0
    fi
    echo "[$(stamp)] [WARN] 락 강제 회수 — $STEAL : $LOCK_DIR" >&2
    rm -rf "$LOCK_DIR"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      echo "[$(stamp)] [SKIP] 락 경합 — 이번 실행은 건너뛴다." >&2
      exit 0
    fi
  fi
  # 1행 PID / 2행 부팅 식별자. 위 (2) 판정이 이 2행을 읽는다.
  printf '%s\n%s\n' "$$" "$(boot_id)" >"$LOCK_DIR/pid"
  trap 'rm -rf "$LOCK_DIR"' EXIT HUP INT TERM
fi

# ---- 사전 점검 -------------------------------------------------------------
# launchd/cron 은 로그인 셸의 PATH 를 물려받지 않는다. python3 를 못 찾는 것이
# 이 파이프라인에서 가장 흔한 macOS 실패 원인이므로 먼저 잡는다.
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[$(stamp)] [ERROR] python 실행 파일을 찾을 수 없다: $PY" >&2
  echo "          BUYBACK_PYTHON=/opt/homebrew/bin/python3 처럼 절대경로를 주라." >&2
  exit 3
fi
if ! "$PY" -c 'import requests' >/dev/null 2>&1; then
  echo "[$(stamp)] [ERROR] requests 모듈 없음. '$PY -m pip install -r requirements.txt' 먼저." >&2
  exit 3
fi
for f in scripts/build_data.py scripts/render.py data/holidays_kr.json vendor/chart.umd.min.js; do
  if [ ! -f "$PROJECT_DIR/$f" ]; then
    echo "[$(stamp)] [ERROR] 필수 파일 없음: $PROJECT_DIR/$f" >&2
    exit 3
  fi
done
# ★ 스냅샷 원장이 없으면 그동안 쌓은 '정확값'을 잃은 상태다. 죽이진 않되 크게 경고한다.
if [ ! -f "$PROJECT_DIR/data/kind_decl_snapshots.json" ]; then
  echo "[$(stamp)] [WARN] data/kind_decl_snapshots.json 이 없다 — 이전 머신에서 옮겨오지" >&2
  echo "          않았다면 과거 일자들이 영구히 추정치(estimated_hl2)로 남는다." >&2
fi

# ★ DART 인증키. 없으면 dart_source 는 import 시점에는 죽지 않고 첫 API 호출의
#   require_key() 에서 예외를 던지므로, 여기서 잡지 않으면 매 실행이 [1/2] build 단계의
#   깊숙한 예외 메시지로만 실패한다. 맥에는 config.json 경로가 없어 .env 가 유일한 통로다.
rc=0
"$PY" -c 'import sys; sys.path.insert(0, "scripts"); import dart_source as d; sys.exit(0 if d.DART_KEY else 4)' >/dev/null 2>&1 || rc=$?
if [ "$rc" -eq 4 ]; then
  echo "[$(stamp)] [ERROR] DART 인증키를 찾지 못했다." >&2
  echo "          $PROJECT_DIR/.env 에 DART_API_KEY=<키> 한 줄을 넣어라 (.env.example 참고)." >&2
  echo "          자세한 내용은 MACMINI_HANDOFF.md §2-4." >&2
  exit 3
elif [ "$rc" -ne 0 ]; then
  echo "[$(stamp)] [WARN] dart_source 를 import 하지 못해 인증키 사전점검을 건너뛴다 (rc=$rc)." >&2
fi

# ★ publish 를 강제(BUYBACK_PUBLISH=1)해 놓고 git 이 없으면 지금 알려준다.
#   auto(기본)에서는 git 부재를 '리포가 아님'과 같이 취급해 경고만 하고 계속 간다
#   — 공개 페이지 갱신이 안 될 뿐 대시보드 자체는 정상적으로 굽히기 때문이다.
if [ "${BUYBACK_PUBLISH:-auto}" != "0" ] && [ -f "$PROJECT_DIR/publish.sh" ] \
   && ! command -v git >/dev/null 2>&1; then
  if [ "${BUYBACK_PUBLISH:-auto}" = "1" ]; then
    echo "[$(stamp)] [ERROR] BUYBACK_PUBLISH=1 인데 git 이 PATH 에 없다." >&2
    echo "          Xcode Command Line Tools 를 설치하라: xcode-select --install" >&2
    exit 3
  fi
  echo "[$(stamp)] [WARN] git 이 PATH 에 없다 — GitHub Pages push(3단계)는 건너뛴다." >&2
fi

# ---- 휴장일 게이트 (기본 OFF) ---------------------------------------------
# 기준일은 반드시 KST 로 판정한다. 맥의 로컬 타임존이 KST 가 아니어도
# build_data.py 와 같은 날짜를 보게 하기 위해서다.
if [ "${SKIP_IF_HOLIDAY:-0}" = "1" ]; then
  rc=0
  "$PY" - <<'PYEOF' || rc=$?
import sys, datetime as dt
sys.path.insert(0, "scripts")
import market_data as md
kst = dt.timezone(dt.timedelta(hours=9))
d = dt.datetime.now(kst).date()
sys.exit(0 if md.is_business_day(d) else 9)
PYEOF
  if [ "$rc" -eq 9 ]; then
    echo "[$(stamp)] KRX 휴장일 — SKIP_IF_HOLIDAY=1 이므로 아무것도 하지 않는다."
    exit 0
  elif [ "$rc" -ne 0 ]; then
    echo "[$(stamp)] 휴장일 판정 실패(rc=$rc) — 안전하게 그대로 실행한다." >&2
  fi
fi

# ---- 1단계 : 수집 + 불변식 게이트 -----------------------------------------
echo
echo "--- [1/2] build_data.py ---"
rc=0
"$PY" scripts/build_data.py || rc=$?
if [ "$rc" -ne 0 ]; then
  echo >&2
  echo "[$(stamp)] [ERROR] build_data.py 실패 (exit $rc) — dashboard.html 을 다시 굽지 않는다." >&2
  echo "          data/buyback.json 은 직전 실행 값 그대로다." >&2
  echo "          로그: $RUN_LOG" >&2
  exit 1
fi

# ---- 2단계 : 렌더 ----------------------------------------------------------
echo
echo "--- [2/2] render.py ---"
rc=0
if [ -n "${REFRESH_HINT:-}" ]; then
  "$PY" scripts/render.py --max-age-days "$MAX_AGE" --refresh-hint "$REFRESH_HINT" || rc=$?
else
  "$PY" scripts/render.py --max-age-days "$MAX_AGE" || rc=$?
fi
if [ "$rc" -ne 0 ]; then
  echo >&2
  echo "[$(stamp)] [ERROR] render.py 실패 (exit $rc). 로그: $RUN_LOG" >&2
  exit 2
fi

# ---- 3단계(선택) : GitHub Pages 로 push -----------------------------------
# 빌드와 렌더가 모두 성공한 뒤에만 여기 온다(= 성공했을 때만 push).
#
# ★ 주의: 커밋 대상 파일은 값이 하나도 안 바뀐 날에도 매 실행마다 내용이 달라진다
#   (build_data.py:582,912 의 generated_at, price_source.py:273 의 captured_at 이
#   무조건 새로 찍히고, render 는 그 payload 를 그대로 HTML 에 넣는다).
#   그래서 publish.sh 는 `git diff --cached --quiet` 만으로 판단하지 않고
#   '타임스탬프 값을 지운 사본'끼리 비교해 실질 변경이 있을 때만 커밋한다.
#   그 판정이 없으면 launchd 가 도는 주 22회마다 286KB HTML 커밋이 무기한 쌓인다.
PUBLISH="${BUYBACK_PUBLISH:-auto}"
if [ "$PUBLISH" = "0" ]; then
  :   # 명시적으로 껐다 — 로그를 남기지 않는다
elif [ ! -f "$PROJECT_DIR/publish.sh" ]; then
  echo "[$(stamp)] [WARN] publish 생략 — publish.sh 가 없다 (BUYBACK_PUBLISH=$PUBLISH)." >&2
elif [ "$PUBLISH" = "1" ] || git -C "$PROJECT_DIR" remote get-url origin >/dev/null 2>&1; then
  echo
  echo "--- [3/3] publish.sh (GitHub Pages) ---"
  rc=0
  bash "$PROJECT_DIR/publish.sh" || rc=$?
  if [ "$rc" -ne 0 ]; then
    # push 실패는 치명적이지 않다. 데이터는 로컬에 남았고, 다음 실행이
    # '밀린 커밋'을 다시 push 한다. 그래서 여기서 죽이지 않는다.
    echo "[$(stamp)] [WARN] publish.sh 실패 (exit $rc) — 공개 페이지는 갱신되지 않았다." >&2
    echo "          로컬 데이터는 정상. 다음 실행이 다시 push 를 시도한다." >&2
  fi
else
  # ★ 여기서 아무 말도 하지 않으면, origin 을 안 붙였거나 git 이 없을 때
  #   대시보드는 매일 정상 빌드되는데 공개 페이지만 영영 갱신되지 않고
  #   로그에 이유가 한 줄도 남지 않는다.
  if ! command -v git >/dev/null 2>&1; then
    reason="git 이 PATH 에 없다 (xcode-select --install)"
  elif ! git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    reason="여기는 git 리포가 아니다 (git init 을 아직 안 했다)"
  else
    reason="origin 리모트가 없다 (git remote add origin ...)"
  fi
  echo "[$(stamp)] [WARN] publish 생략 — $reason (BUYBACK_PUBLISH=$PUBLISH)." >&2
  echo "          로컬 대시보드는 정상이나 GitHub Pages 는 갱신되지 않는다. DEPLOY.md 참고." >&2
fi

# ---- 로그 정리 -------------------------------------------------------------
find "$LOG_DIR" -name 'run_*.log' -type f -mtime "+$LOG_KEEP" -delete 2>/dev/null || true

echo
echo "[$(stamp)] [OK] done - $PROJECT_DIR/dashboard.html"
exit 0
