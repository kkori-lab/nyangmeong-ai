#!/bin/sh
# /start의 기계적인 앞 단계: 브랜치 확인, 원격 합치기, 설정 키 점검, 검증 루프 보관, 핸드오프 생성, 작업 후보.
# 판단이 필요 없는 일을 옮겨 /start(Opus)가 이 출력만 읽게 한다. 종료 코드가 0이 아니면 /start는 출력을 보여 주고 멈춘다.
# 사용: sh scripts/start-check.sh [화면 ID]
cd "$(git rev-parse --show-toplevel)" || exit 1

branch=$(git branch --show-current)
case "$branch" in
  develop | main | "") echo "자기 이니셜 브랜치로 옮긴 뒤 다시 시작하세요(지금: ${branch:-브랜치 없음})"; exit 1 ;;
esac
name=${branch%%/*}

# 원격과 합친다. merge 커밋으로 합치고 rebase·푸시는 하지 않는다(docs/convention/git.md)
echo "## 원격"
if ! git fetch -q origin; then
  echo "fetch 실패. 합치지 않고 이어 갑니다"
else
  dirty=$(git status --porcelain | cut -c4- | sed 's/.* -> //')
  merged=0
  for ref in "origin/$branch" origin/develop; do
    git rev-parse -q --verify "$ref" >/dev/null || continue
    n=$(git rev-list --count "HEAD..$ref")
    [ "$n" = 0 ] && continue
    incoming=$(git diff --name-only "HEAD...$ref")
    if [ -n "$dirty" ]; then
      overlap=$(printf '%s\n' "$incoming" | grep -xF "$dirty")
      if [ -n "$overlap" ]; then
        echo "$ref에서 들어올 변경이 커밋하지 않은 파일과 겹쳐 합치지 않았습니다. 커밋하거나 되돌린 뒤 다시 /start 하세요:"
        printf '%s\n' "$overlap" | sed 's/^/- /'
        exit 1
      fi
    fi
    echo "$ref에서 커밋 ${n}개:"
    git log --oneline --no-merges "HEAD..$ref" | head -20 | sed 's/^/- /'
    if ! git merge -q --no-edit "$ref"; then
      echo "충돌이 났습니다. merge --abort 하지 않고 그대로 둡니다. 충돌 파일:"
      git diff --name-only --diff-filter=U | sed 's/^/- /'
      exit 1
    fi
    merged=1
  done
  [ "$merged" = 0 ] && echo "들어올 커밋 없음"
fi

# 예시 파일의 키 중 실제 파일에 없거나 값이 빈 것. 값은 출력하지 않는다
echo "## 설정 키"
check_keys() {
  [ -f "$1" ] || return 0
  missing=$(sed 's/\r$//' "$1" | grep -E '^[A-Za-z_][A-Za-z0-9_.-]*[[:space:]]*=' | sed 's/[[:space:]]*=.*//' | while IFS= read -r k; do
    case "$k" in DMS_MCP_URL | FIGMA_FILE_URL | dms.mcp-url) continue ;; esac
    re=$(printf '%s' "$k" | sed 's/\./\\./g')
    v=$(sed 's/\r$//' "$2" 2>/dev/null | grep -E "^$re[[:space:]]*=" | tail -1 | sed -e 's/^[^=]*=[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/')
    [ -n "$v" ] || printf '%s ' "$k"
  done)
  [ -n "$missing" ] && echo "$2에 빠진 키: $missing(디스코드의 최신 파일로 받으세요)"
  return 0
}
check_keys .env.local.example .env.local

# 잠금이 남아 있으면 이전 세션이 /end 없이 끝난 것이다. 지우지 않고 보관한다(clear는 사람만 한다)
echo "## 검증 루프"
case "$(sh scripts/verify-loop.sh status)" in "잠금 회차"*) sh scripts/verify-loop.sh pause ;; esac
sh scripts/verify-loop.sh status

hf=handoff/$name.md
if [ ! -f "$hf" ]; then
  mkdir -p handoff
  printf '# %s 핸드오프\n\n## 지금 하는 것\n\n## 다음에 할 것\n' "$name" > "$hf"
  echo "$hf 새로 만듦"
fi
echo "## 지금 하는 것"
awk '/^## 지금 하는 것/ { f = 1; next } /^## / { f = 0 } f && NF' "$hf"
# 첫 줄의 상태로 승인 여부를 본다. "— 기획 ("이면 승인 전이다(/impl이 "— 구현 중 (승인 …"으로 바꾼다)
case "$(awk '/^## 지금 하는 것/ { f = 1; next } /^## / { f = 0 } f && NF { print; exit }' "$hf")" in
  *"— 기획 ("*) echo "기획 상태: 승인 전" ;;
  *"— 구현 중 ("*) echo "기획 상태: 구현 중" ;;
esac

echo "## PR"
if command -v gh >/dev/null; then
  gh pr list --head "$branch" --state all --limit 3 --json number,state,title \
    --jq '.[] | "#\(.number) \(.state) \(.title)"' 2>/dev/null || echo "gh 조회 실패"
else
  echo "gh 없음"
fi

echo "## 작업 후보"
mf=milestones/$name.md
if ! grep -q '^## SCR-' "$mf" 2>/dev/null; then
  echo "마일스톤 파일이 없거나 형식이 다릅니다"
elif [ -n "$1" ]; then
  id=$(printf '%s' "$1" | tr 'a-z' 'A-Z')
  case "$id" in SCR-*) ;; *) id=SCR-$id ;; esac
  grep "^## $id " "$mf" || { echo "이 화면 ID의 마일스톤이 없습니다: $id"; exit 1; }
else
  next=$(awk '/^## 다음에 할 것/ { f = 1; next } /^## / { f = 0 } f && /^- / { print; exit }' "$hf")
  echo "다음에 할 것 맨 위: ${next:-없음}"
  grep '^## SCR-.* — 진행$' "$mf" | sed 's/^/진행: /'
  echo "대기 맨 위: $(grep -m1 '^## SCR-.* — 대기$' "$mf" || echo 없음)"
fi
exit 0
