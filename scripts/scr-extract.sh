#!/bin/sh
# 화면설계서 HTML에서 화면 ID 하나의 부분만 글자로 뽑는다. /start 기획이 문서 전체 대신 이 결과만 읽는다.
# 화면 블록은 class="frame-bar"에서 시작하고, 그 뒤 처음 나오는 SCR ID가 그 화면이다(모든 도메인 화면설계서 공통).
# 백엔드 저장소에 같은 파일이 있다. 고칠 때 둘 다 고친다.
# 사용: sh scripts/scr-extract.sh <화면설계서.html> <SCR-ID>
[ $# = 2 ] || { echo "사용: sh scripts/scr-extract.sh <화면설계서.html> <SCR-ID>" >&2; exit 2; }
awk -v id="$2" '
  /class="frame-bar"/ { cur = ""; want = 1 }
  want && match($0, /SCR-[A-Z]+-[0-9][0-9][0-9]/) { cur = substr($0, RSTART, RLENGTH); want = 0 }
  cur == id { print }
' "$1" |
  sed -e 's/<br[^>]*>/\n/g' -e 's/<\/\(tr\|p\|div\|li\|h[1-6]\)>/\n/g' -e 's/<td[^>]*>/ | /g' \
      -e 's/<[^>]*>//g' -e 's/&nbsp;/ /g' -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&amp;/\&/g' |
  sed -e 's/[[:space:]]\{1,\}/ /g' -e 's/^ //' |
  grep -v '^[ |]*$' || { echo "$2 화면을 찾지 못했습니다: $1" >&2; exit 1; }
