#!/bin/bash
# ---------------------------------------------------------------------------
#  buyback-dashboard : docs/index.html + 누적 원장을 GitHub 로 push
#
#  역할은 하나다. "빌드가 성공해서 실제로 값이 바뀐 파일이 있을 때만" 커밋하고 push 한다.
#  수집/렌더는 여기서 하지 않는다 → 반드시 run_daily.sh 가 성공한 뒤에 부른다.
#
#      ./run_daily.sh && ./publish.sh
#
#  (run_daily.sh 안에서 마지막 줄로 불러도 된다. 두 번 불려도 두 번째는
#   "변경 없음"으로 끝나므로 빈 커밋이 생기지 않는다.)
#
#  ★ '변경 없음' 판정은 `git diff --cached --quiet` 만으로 하면 안 된다.
#    커밋 대상 파일은 값이 하나도 안 바뀐 실행에서도 매번 내용이 달라진다:
#      build_data.py:582,912  "generated_at" 를 무조건 새로 찍는다
#      price_source.py:273    스냅샷을 쓸 때마다 "captured_at" 을 무조건 갱신한다
#      render.py              그 payload 를 그대로 docs/index.html 에 주입한다
#    그대로 두면 launchd 스케줄(평일 4회 + 주말 1회 = 주 22회)이 돌 때마다
#    286KB 짜리 docs/index.html 커밋이 무기한 쌓이고 push 마다 Pages 가 재빌드된다.
#    → 타임스탬프 '값'만 지운 사본끼리 비교해서, 그것마저 같으면 커밋하지 않는다.
#
#  옵션
#    --dry-run   커밋/푸시 없이 무엇이 올라갈지만 보여준다
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

# set -e 아래에서 `[ ... ] && VAR=1` 은 조건이 거짓일 때 리스트 전체가 1을 반환한다.
# 위치에 따라 스크립트가 조용히 끝날 수 있으므로 if 문으로 쓴다.
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then DRY_RUN=1; fi

log() { printf '[publish] %s\n' "$*"; }
die() { printf '[publish][ERROR] %s\n' "$*" >&2; exit 1; }

# --- 0. git 리포인가 -------------------------------------------------------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || die "여기는 git 리포가 아니다. DEPLOY.md §H (리포 재생성)을 먼저 하라."

git remote get-url origin >/dev/null 2>&1 \
  || die "origin 리모트가 없다. DEPLOY.md §H (리포 재생성)을 먼저 하라."

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[ "$BRANCH" = "HEAD" ] && die "detached HEAD 상태다. 'git switch main' 후 다시 실행하라."

# --- 1. 시크릿 가드 (무조건 먼저) ------------------------------------------
#  .gitignore 를 누가 고쳐서 .env 가 추적되기 시작하면 여기서 멈춘다.
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  die ".env 가 git 에 추적되고 있다. 'git rm --cached .env' 로 빼고 .gitignore 를 확인하라."
fi

# --- 2. 커밋 대상 -----------------------------------------------------------
#  명시한 경로만 스테이징한다(작업 중이던 딴 파일이 딸려 올라가지 않게).
PATHS=(
  docs/index.html
  docs/.nojekyll
  data/buyback.json
  data/kind_decl_snapshots.json    # ★ 누적 원장 — 이게 핵심이다
  data/kind_decl_backfill.json
  data/holidays_kr.json
  data/dart_snapshot.json
)

# 빌드 산출물이 있는지 확인 (run_daily 를 안 돌리고 부른 경우 잡는다)
[ -f docs/index.html ] || die "docs/index.html 이 없다. run_daily.sh 를 먼저 실행하라."

# --- 3. 원격 먼저 반영 ------------------------------------------------------
#  Actions 백업 커밋이나 다른 머신의 커밋이 있을 수 있다.
#  ★ 웹 UI 로 빈 리포를 만들고 `git remote add origin` 만 한 상태에서는 원격에
#    브랜치가 아직 없다. 그 때 pull 하면 `couldn't find remote ref main` 으로
#    통째로 die 하므로(첫 자동 실행이 여기서 죽는다), 존재 여부를 먼저 본다.
REMOTE_HAS_BRANCH=0
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  REMOTE_HAS_BRANCH=1
  log "원격 반영 중 (pull --rebase)"
  git pull --rebase --autostash origin "$BRANCH" || die "pull --rebase 실패. 수동으로 충돌을 풀어라."
else
  log "원격에 $BRANCH 브랜치가 아직 없다 — pull 을 건너뛰고 최초 push 로 진행한다."
fi

# --- 4. 변경분만 스테이징 ---------------------------------------------------
STAGED=0
for f in "${PATHS[@]}"; do
  [ -f "$f" ] || continue
  git add -- "$f"
done

# ★ 실질 변경 판정 (헤더의 설명 참조)
#   타임스탬프 '값'만 지운 사본끼리 비교한다. 행 단위 필터로는 안 된다 —
#   docs/index.html 은 14KB 짜리 payload 가 통째로 한 줄에 들어 있어서,
#   그 줄을 통으로 버리면 실제 값 변경까지 같이 가려진다.
TS_RE='s/"(generated_at|captured_at|fetched)"([[:space:]]*:[[:space:]]*)"[^"]*"/"\1"\2"~TS~"/g'

# 0 = 실질 변경 있음(커밋해야 함) · 1 = 타임스탬프만 바뀜
has_substantive_change() {
  local f
  for f in $(git diff --cached --name-only); do
    # HEAD 가 없거나(최초 커밋) 새 파일이면 git show 가 비어 나오므로 자동으로 '변경 있음'
    if ! diff -q \
         <(git show ":$f" 2>/dev/null | sed -E "$TS_RE") \
         <(git show "HEAD:$f" 2>/dev/null | sed -E "$TS_RE") >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

if git diff --cached --quiet; then
  log "커밋할 변경 없음"
  # 참고용: 커밋 대상 밖에서 바뀐 게 있으면 알려만 준다(막지는 않는다).
  if ! git diff --quiet; then
    log "(참고) 커밋 대상 밖에 수정된 파일이 있다: $(git diff --name-only | tr '\n' ' ')"
  fi
elif ! has_substantive_change; then
  log "타임스탬프(generated_at/captured_at)만 갱신됨 — 커밋하지 않는다."
  log "  (다음 실행에서 값이 실제로 바뀌면 그 때 이 변경까지 함께 커밋된다)"
  git reset -q
else
  log "커밋 대상:"
  git diff --cached --name-only | sed 's/^/  /'

  if [ "$DRY_RUN" = "1" ]; then
    log "--dry-run 이므로 여기서 멈춘다."
    git reset -q
    exit 0
  fi

  # ★ 커밋 신원이 없으면 커밋하지 않는다.
  #   예전에는 여기서 개인 계정 이름/이메일로 조용히 폴백했는데,
  #   그러면 신원을 안 잡은 머신의 무인 실행이 개인 이메일을 public 리포 커밋에
  #   영구히 박아 버린다(되돌릴 수 없다). 멈춰서 알려주는 쪽이 낫다.
  if ! git config user.name >/dev/null 2>&1 || ! git config user.email >/dev/null 2>&1; then
    die "커밋 신원이 설정되지 않았다(clone 은 이걸 가져오지 않는다).
             다음 두 줄을 먼저 실행하라 — 개인 메일을 쓰지 말 것:
               git config user.name  \"Jaey27\"
               git config user.email \"Jaey27@users.noreply.github.com\"
             자세한 것은 DEPLOY.md §B-0 / MACMINI_HANDOFF.md §3-2."
  fi

  STAMP="$(date '+%Y-%m-%d %H:%M %Z')"
  git commit -q -m "data: daily update ${STAMP}"
fi

# --- 5. 밀린 커밋이 있으면 push ---------------------------------------------
#  ★ "커밋했을 때만 push" 로 짜면 안 된다. 커밋은 됐는데 push 가 네트워크로
#    실패한 날이 있으면, 그 다음 실행부터는 '변경 없음'이라 push 를 영영 안 한다.
#    그래서 '로컬이 origin 보다 앞서 있는가'로 판단한다(4 항의 pull 이 방금
#    origin/$BRANCH 를 갱신해 두었다).
#  ★ 원격에 브랜치가 없으면 origin/$BRANCH 가 없어서 rev-list 가 0 을 돌려준다.
#    그대로 두면 최초 push 가 영원히 '생략'되므로 이 경우만 따로 강제한다.
if [ "$REMOTE_HAS_BRANCH" = "0" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    log "--dry-run: 최초 push 대상 ($BRANCH) — 푸시하지 않음"
    exit 0
  fi
  log "최초 push - git push -u origin $BRANCH"
  git push -u origin "$BRANCH"
  log "완료 - $(git remote get-url origin) / ${BRANCH}"
  exit 0
fi

AHEAD="$(git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0)"
if [ "$AHEAD" = "0" ]; then
  log "origin 과 동일 - push 생략"
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  log "--dry-run: push 대기 중인 커밋 ${AHEAD}개 (푸시하지 않음)"
  exit 0
fi

log "push 대기 커밋 ${AHEAD}개"
if ! git push origin "$BRANCH"; then
  log "push 실패 - pull --rebase 후 1회 재시도"
  git pull --rebase --autostash origin "$BRANCH"
  git push origin "$BRANCH"
fi

log "완료 - $(git remote get-url origin) / ${BRANCH}"
