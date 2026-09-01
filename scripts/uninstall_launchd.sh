#!/bin/bash
# ---------------------------------------------------------------------------
#  launchd 등록 해제 (자동 갱신 중단). 다시 켜려면 scripts/install_launchd.sh
#
#  ★ 해제하면 그날부터 KIND decl 누계 스냅샷이 끊기고, 안 찍은 날짜는
#    영구히 추정치(estimated_hl2)로 떨어진다. 소급 복구가 안 되므로
#    "잠깐 꺼둔다"는 생각으로 오래 두지 말 것. 임시 중단이면 차라리
#    scripts/run_daily.sh 를 수동으로 매일 저녁 한 번 돌리는 편이 낫다.
# ---------------------------------------------------------------------------
set -uo pipefail

LABEL="com.pjy.buyback-dashboard.daily"
LA="${BUYBACK_LAUNCHD_OUTDIR:-$HOME/Library/LaunchAgents}"
PLIST="$LA/$LABEL.plist"
UID_NUM="$(id -u)"

if launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null; then
  echo "해제: $LABEL"
elif launchctl unload "$PLIST" 2>/dev/null; then
  echo "해제(legacy): $LABEL"
else
  echo "이미 해제됨: $LABEL"
fi

# ★ bootout 은 '지금 이 부팅 세션'에서만 내린다. plist 를 ~/Library/LaunchAgents 에
#   남겨 두면 다음 로그인/재부팅 때 launchd 가 그 디렉터리를 다시 스캔해 잡을
#   자동으로 되살린다. 사용자가 "껐다"고 믿는 것과 실제가 어긋나므로 disable 까지 건다.
#   (install_launchd.sh 가 bootstrap 전에 `launchctl enable` 로 되돌린다.)
if launchctl disable "gui/$UID_NUM/$LABEL" 2>/dev/null; then
  echo "영구 해제: launchctl disable gui/$UID_NUM/$LABEL — 다음 로그인에도 다시 켜지지 않는다."
else
  echo "[주의] launchctl disable 이 실패했다(구버전 macOS 등)." >&2
  echo "       이 경우 bootout 은 현재 부팅 세션에만 적용되고, 다음 로그인 때" >&2
  echo "       launchd 가 plist 를 다시 읽어 자동으로 되살린다." >&2
  echo "       확실히 끄려면:  rm \"$PLIST\"" >&2
fi

echo "plist 파일은 $PLIST 에 남아 있다 (파일까지 지우려면 rm \"$PLIST\")"
echo "다시 켜기: $(cd -- "$(dirname -- "$0")" && pwd -P)/install_launchd.sh"
