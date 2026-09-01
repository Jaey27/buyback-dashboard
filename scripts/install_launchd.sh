#!/bin/bash
# ---------------------------------------------------------------------------
#  macOS launchd 등록 — 평일 18:30 / 19:30 / 21:00 + 매일 08:40
#  재실행하면 기존 등록을 교체한다. 해제: scripts/uninstall_launchd.sh
#
#  launchd 를 쓰는 이유(cron 대신):
#   - 맥이 잠들어 있던 시각을 놓쳐도 깨어난 뒤 한 번 실행해 준다(cron 은 그냥 건너뛴다)
#   - 로그인 세션 단위라 사용자 권한·홈 경로(.env)를 그대로 쓴다
#
#  ★ 시각을 정한 근거 (README §1 참조)
#   KIND 는 당일 체결분을 18시 이후에 집계한다. 일별 체결금액의 정확값은
#   decl(신고내역)의 '체결금액누계'를 매일 찍어 차분해서만 얻어지고
#   (data/kind_decl_snapshots.json), 거른 날은 영구히 추정치로 떨어진다.
#     18:30  1차 — 18시 집계 직후, 여유 30분
#     19:30  2차 — 1차가 네트워크/서버 문제로 실패했을 때
#     21:00  3차 — 저녁 시간대 마지막 기회
#     08:40  다음날 아침 — 저녁에 맥이 꺼져 있었을 때의 복구용 (매일)
#   ★ 08:40 이 왜 복구가 되는가: D일 값을 담은 decl 누계는 D일 18:00 부터
#     D+1 영업일 18:00(다음 집계) 전까지 그대로 남아 있고, 스냅샷의 as_of 는
#     trddetail 의 마지막 체결일(=D)로 잡힌다. 즉 D일 값을 놓치는 조건은
#     "약 24시간 창을 통째로 놓치는 것"이지 "18:30 한 번을 놓치는 것"이 아니다.
#   ★ 재시도가 안전한 이유: snapshot_decl() 은 (종목|프로그램시작일) → as_of 키에
#     그대로 덮어쓴다(last-write-wins). 같은 날 몇 번을 돌려도 누적이 꼬이지 않고,
#     나중 실행이 항상 더 정확한 값으로 갱신한다.
#
#  개발/검증용 환경변수 (macOS 에서는 쓸 일 없음)
#    BUYBACK_LAUNCHD_DRYRUN=1   plist 만 만들고 launchctl 을 호출하지 않는다
#    BUYBACK_LAUNCHD_OUTDIR=... plist 출력 디렉터리 (기본 ~/Library/LaunchAgents)
#    BUYBACK_PYTHON=...         쓸 파이썬 절대경로 (기본 command -v python3)
# ---------------------------------------------------------------------------
set -euo pipefail

# pwd -P 로 심볼릭 링크를 풀어 둔다. run_daily.sh:41 이 같은 방식으로 자기 위치를
# 잡으므로 이걸 맞춰 두지 않으면 두 스크립트가 서로 다른 경로 문자열을 쓰게 되고,
# 심링크를 통해 설치하면 링크 경로가 plist 4곳(ProgramArguments·WorkingDirectory·
# StandardOutPath·StandardErrorPath)에 영구히 박힌다.
PROJECT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
LABEL="com.pjy.buyback-dashboard.daily"
DRY_RUN="${BUYBACK_LAUNCHD_DRYRUN:-0}"
LA="${BUYBACK_LAUNCHD_OUTDIR:-$HOME/Library/LaunchAgents}"
PLIST="$LA/$LABEL.plist"

PY="${BUYBACK_PYTHON:-$(command -v python3 || true)}"
if [ -z "$PY" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    PY="/usr/bin/python3"
  else
    echo "python3 를 찾을 수 없다. brew install python@3.13 후 다시 실행하라." >&2
    exit 1
  fi
fi

# ★ command -v 로 고른 경로는 '설치 시점의 대화형 셸 PATH' 에서 온 것이다.
#   pyenv/asdf/conda 를 쓰는 맥이면 ~/.pyenv/shims/python3 같은 shim 이 잡히는데,
#   shim 은 launchd 의 최소 환경(PATH·쉘 초기화 없음)에서 버전 해석에 실패할 수 있다.
#   그래서 여기서 한 번 실행해 실제 인터프리터 경로(sys.executable)로 바꿔 박는다.
if [ "$DRY_RUN" != "1" ]; then
  PY_REAL="$("$PY" -c 'import sys; print(sys.executable)' 2>/dev/null || true)"
  if [ -z "$PY_REAL" ]; then
    echo "'$PY' 를 실행할 수 없다(파이썬이 아니거나 깨져 있다)." >&2
    echo "BUYBACK_PYTHON=/opt/homebrew/bin/python3 처럼 절대경로를 주고 다시 실행하라." >&2
    exit 1
  fi
  if [ "$PY_REAL" != "$PY" ]; then
    echo "python 경로 보정: $PY  ->  $PY_REAL"
    PY="$PY_REAL"
  fi
  case "$PY" in
    */shims/*|*/.pyenv/*|*/.asdf/*)
      echo "[경고] shim 으로 보이는 경로가 plist 에 박힌다: $PY" >&2
      echo "        launchd 의 최소 환경에서는 shim 이 버전 해석에 실패할 수 있다." >&2
      echo "        BUYBACK_PYTHON=/opt/homebrew/bin/python3 로 다시 실행하는 것을 권한다." >&2
      ;;
  esac
  # requests 가 없으면 run_daily.sh 가 매 실행 exit 3 으로 죽는다. 지금 알려준다.
  if ! "$PY" -c 'import requests' >/dev/null 2>&1; then
    echo "[경고] '$PY' 에 requests 가 없다. 등록은 하지만 실행은 exit 3 으로 죽는다." >&2
    echo "        '$PY -m pip install -r $PROJECT_DIR/requirements.txt' 를 먼저 하라." >&2
  fi
fi

mkdir -p "$LA" "$PROJECT_DIR/logs"
chmod +x "$PROJECT_DIR/scripts/run_daily.sh" 2>/dev/null || true

# 평일(월=1 ~ 금=5) 저녁 3회 + 매일 아침 1회.
# Weekday 키를 빼면 launchd 는 '매일'로 해석한다 → 아침 항목은 주말에도 돈다
# (주말 실행은 무해한 no-op 이면서, 금요일 저녁을 통째로 놓쳤을 때의 복구가 된다).
build_intervals() {
  for wd in 1 2 3 4 5; do
    for hm in "18 30" "19 30" "21 0"; do
      # shellcheck disable=SC2086
      set -- $hm
      printf '        <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>%s</integer><key>Minute</key><integer>%s</integer></dict>\n' "$wd" "$1" "$2"
    done
  done
  printf '        <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>40</integer></dict>\n'
}

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/scripts/run_daily.sh</string>
    </array>
    <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>BUYBACK_PYTHON</key><string>$PY</string>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>BUYBACK_TZ</key><string>Asia/Seoul</string>
        <key>SKIP_IF_HOLIDAY</key><string>0</string>
        <key>PYTHONIOENCODING</key><string>utf-8</string>
    </dict>
    <key>StandardOutPath</key><string>$PROJECT_DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/launchd.err.log</string>
    <key>RunAtLoad</key><false/>
    <key>ProcessType</key><string>Background</string>
    <key>StartCalendarInterval</key>
    <array>
$(build_intervals)
    </array>
</dict>
</plist>
PLIST

echo "plist 작성: $PLIST"

# ★ launchctl 을 부르기 전에 plist 유효성부터 본다. 깨진 plist 로 bootstrap 하면
#   launchctl 의 오류 메시지가 원인을 전혀 가리키지 않는다.
if command -v plutil >/dev/null 2>&1; then
  if ! plutil -lint "$PLIST"; then
    echo "plist 가 유효하지 않다: $PLIST — launchctl 을 호출하지 않고 중단한다." >&2
    exit 1
  fi
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "(DRYRUN — launchctl 호출 생략)"
  exit 0
fi

# 최신 API(bootstrap/bootout) 우선, 실패하면 legacy(load/unload) 로 폴백.
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
# uninstall_launchd.sh 가 `launchctl disable` 로 영구 해제해 둔 상태일 수 있다.
# disable 된 서비스는 bootstrap 이 거부되므로 먼저 풀어 준다.
launchctl enable "gui/$UID_NUM/$LABEL" 2>/dev/null || true
# bootout 직후 잡 정리가 끝나기 전에 bootstrap 하면 EEXIST 로 튄다.
sleep 1

# ★ stderr 를 2>/dev/null 로 버리면 재설치 실패의 진짜 원인
#   (Service already loaded / Operation not permitted / Load failed: 5 …)이
#   사용자에게 영영 보이지 않는다. 변수에 받아 폴백 전에 출력한다.
if ! BOOTSTRAP_ERR="$(launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>&1)"; then
  echo "launchctl bootstrap 실패: ${BOOTSTRAP_ERR:-(메시지 없음)}" >&2
  echo "legacy(load/unload) 로 폴백한다." >&2
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
fi
echo "등록: $LABEL"

echo
echo "=== 등록 확인 ==="
launchctl list | grep -E 'buyback-dashboard' || echo "(목록에 없으면 등록 실패 — 위 오류 확인)"

echo
echo "실행 시각: 월~금 18:30 / 19:30 / 21:00  +  매일 08:40"
echo "★ StartCalendarInterval 은 '시스템 로컬 시각'으로 발화한다(TZ 환경변수 무시)."
echo "   지금 이 맥의 타임존: $(date +%Z) ($(date +%z))"
echo "   확인:  sudo systemsetup -gettimezone"
echo "   설정:  sudo systemsetup -settimezone Asia/Seoul"
echo "   → KST 가 아니면 '발화 시각'이 어긋난다(데이터의 기준일은 스크립트가 TZ=Asia/Seoul"
echo "     로 고정하므로 안전). 자세한 내용은 MACMINI_HANDOFF.md 참조."
echo "수동 즉시 실행: launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo "로그:          tail -f $PROJECT_DIR/logs/launchd.out.log"
echo "해제:          $PROJECT_DIR/scripts/uninstall_launchd.sh"
