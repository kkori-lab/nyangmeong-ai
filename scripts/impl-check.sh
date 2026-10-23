#!/bin/sh
# /impl 1번의 기계적인 확인: "지금 하는 것"에 기획이 있는지, 답(결정:)이 없는 질문이 있는지.
# approve를 주면 확인이 통과했을 때 첫 줄의 상태를 "구현 중 (승인 <시각>, …)"으로 바꾼다.
# 종료 코드: 0 진행 가능, 3 기획 없음, 4 답 없는 질문 있음
# 사용: sh scripts/impl-check.sh [approve]
cd "$(git rev-parse --show-toplevel)" || exit 1
branch=$(git branch --show-current)
hf=handoff/${branch%%/*}.md

section() { awk '/^## 지금 하는 것/ { f = 1; next } /^## / { f = 0 } f' "$hf" 2>/dev/null; }
if ! section | grep -q '완료 조건\|새 의존성:'; then
  echo "기획이 없습니다. /start로 기획부터 하세요"
  exit 3
fi

# 질문 줄 다음에 다음 질문(또는 절 끝)보다 먼저 "결정:"이 나와야 답한 것이다
open=$(section | awk '
  /질문/ && !/결정:/ { if (q != "") print q; q = $0; next }
  /결정:/ { q = "" }
  END { if (q != "") print q }')
if [ -n "$open" ]; then
  echo "답이 없는 질문:"
  printf '%s\n' "$open"
  exit 4
fi

head=$(section | grep -m1 .)
echo "상태 줄: $head"
[ "$1" = approve ] || exit 0
case "$head" in
  *"— 구현 중 ("*) echo "이미 구현 중입니다" ;;
  *"— 기획 ("*)
    now=$(date '+%Y-%m-%d %H:%M')
    line=$(grep -n -m1 -F -- "$head" "$hf" | cut -d: -f1)
    sed -i "${line}s/ — 기획 (/ — 구현 중 (승인 $now, /" "$hf"
    echo "바꿈: $(sed -n "${line}p" "$hf")"
    ;;
  *) echo "상태 줄에 \"— 기획 (\"가 없어 바꾸지 않았습니다. 손으로 \"— 구현 중 (승인 $(date '+%Y-%m-%d %H:%M'))\"을 붙이세요" ;;
esac
exit 0
