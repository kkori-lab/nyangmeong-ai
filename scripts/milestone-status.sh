#!/bin/sh
# milestones/<이름>.md의 마일스톤 절 제목 끝 상태(— 대기·진행·끝)를 바꾼다. /start 3번(진행·대기), /end 5번(끝·진행)이 쓴다.
# 같은 화면 ID의 절이 여럿이면(1차·2차) 세 번째 인자로 제목에 든 글자를 준다.
# 사용: sh scripts/milestone-status.sh <SCR-ID> <대기|진행|끝> [제목에 든 글자]
cd "$(git rev-parse --show-toplevel)" || exit 1
[ $# -ge 2 ] || { echo "사용: sh scripts/milestone-status.sh <SCR-ID> <대기|진행|끝> [제목에 든 글자]" >&2; exit 2; }
case "$2" in 대기 | 진행 | 끝) ;; *) echo "상태는 대기·진행·끝 중 하나입니다: $2" >&2; exit 2 ;; esac

branch=$(git branch --show-current)
mf=milestones/${branch%%/*}.md
[ -f "$mf" ] || { echo "마일스톤 파일이 없습니다: $mf" >&2; exit 1; }
id=$(printf '%s' "$1" | tr 'a-z' 'A-Z')
case "$id" in SCR-*) ;; *) id=SCR-$id ;; esac

hits=$(grep -n "^## $id .* — \(대기\|진행\|끝\)$" "$mf" | grep -F -- "${3:-}")
n=$(printf '%s' "$hits" | grep -c .)
[ "$n" = 1 ] || {
  echo "$id 절이 ${n}개입니다. 세 번째 인자로 제목에 든 글자를 주세요:" >&2
  grep "^## $id " "$mf" | sed 's/^/- /' >&2
  exit 1
}
line=${hits%%:*}
sed -i "${line}s/ — \(대기\|진행\|끝\)\$/ — $2/" "$mf"
sed -n "${line}p" "$mf"
