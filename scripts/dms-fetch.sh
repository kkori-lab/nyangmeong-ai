#!/bin/sh
# DMS 문서를 .cache/dms/에 받아 두고(있으면 건너뜀) 화면 ID 하나만 뽑는다. /start 4번이 쓴다.
# DMS 검색과 다운로드 링크는 MCP라 /start가 구한다. 캐시에 없을 때만 링크를 준다.
# 파일 이름에 "기능명세서"가 있으면 spec-extract.sh, "화면설계서"가 있으면 scr-extract.sh로 뽑는다.
# 종료 코드: 3 캐시에 없고 링크도 없음(get_download_url로 링크를 구해 다시 부른다)
# 사용: sh scripts/dms-fetch.sh <파일명> <SCR-ID> [다운로드 링크]
cd "$(git rev-parse --show-toplevel)" || exit 1
[ $# -ge 2 ] || { echo "사용: sh scripts/dms-fetch.sh <파일명> <SCR-ID> [다운로드 링크]" >&2; exit 2; }
case "$1" in */* | *..*) echo "파일명에 경로를 넣지 않습니다: $1" >&2; exit 2 ;; esac
file=.cache/dms/$1

if [ ! -f "$file" ]; then
  [ -n "$3" ] || { echo "캐시에 없습니다: $file (다운로드 링크를 세 번째 인자로 주세요)"; exit 3; }
  mkdir -p .cache/dms
  curl -sSf -o "$file.part" "$3" || { rm -f "$file.part"; echo "내려받기 실패: $1" >&2; exit 1; }
  mv "$file.part" "$file"
fi

case "$1" in
  *기능명세서*) sh scripts/spec-extract.sh "$file" "$2" ;;
  *화면설계서*) sh scripts/scr-extract.sh "$file" "$2" ;;
  *) echo "기능명세서·화면설계서가 아닙니다. 받기만 했습니다: $file" ;;
esac
