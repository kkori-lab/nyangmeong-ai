#!/bin/sh
# docs/api/*.md에서 기능 ID(또는 화면 ID)가 든 API 행과 그 행의 요청·응답 DTO 절만 뽑는다. /start 기획이 파일 전체 대신 이 결과만 읽는다.
# 기능 ID 칸은 "MYP-030-03·09~12·17, MYP-031-06"처럼 묶어 적는다. ·는 나열, ~는 범위다. "COM-009"처럼 화면 ID만 적은 행도 있다.
# DTO 절 안의 필드 타입이 같은 파일의 다른 DTO 절이면 그 절도 함께 뽑는다(두 단계까지).
# 사용: sh scripts/api-row.sh <기능 ID 또는 화면 ID>   예: FN-MYP-031-02, MYP-031-02, SCR-MYP-031
cd "$(git rev-parse --show-toplevel)" || exit 1
[ $# = 1 ] || { echo "사용: sh scripts/api-row.sh <기능 ID 또는 화면 ID>" >&2; exit 2; }
q=$(printf '%s' "$1" | tr 'a-z' 'A-Z' | sed 's/^\(FN\|SCR\)-//')

found=0
for f in docs/api/*.md; do
  rows=$(awk -F'|' -v q="$q" '
    # "09~12" → 9 10 11 12 를 set 에 넣는다
    function addnums(s, set,   parts, i, a, b, k) {
      n = split(s, parts, "·")
      for (i = 1; i <= n; i++) {
        if (parts[i] !~ /^[0-9]+(~[0-9]+)?$/) continue
        if (index(parts[i], "~")) { split(parts[i], ab, "~"); a = ab[1] + 0; b = ab[2] + 0 } else { a = parts[i] + 0; b = a }
        for (k = a; k <= b; k++) set[k] = 1
      }
    }
    function hit(col,   toks, t, i, m, dom, rest, segs, scr, fns, sset, fset) {
      gsub(/\([^)]*\)/, "", col)
      m = split(col, toks, ",")
      for (i = 1; i <= m; i++) {
        t = toks[i]; gsub(/[[:space:]]|FN-|SCR-/, "", t)
        if (t !~ /^[A-Z]+-[0-9]/) continue
        dom = substr(t, 1, index(t, "-") - 1); rest = substr(t, index(t, "-") + 1)
        if (split(rest, segs, "-") == 1) {
          # 화면 ID만: MAN-006·007
          delete sset; addnums(segs[1], sset)
          if (qfn == "" && qdom == dom && ((qscr + 0) in sset)) return 1
        } else {
          if (qdom != dom || (segs[1] + 0) != (qscr + 0)) continue
          if (qfn == "") return 1
          delete fset; addnums(segs[2], fset)
          if ((qfn + 0) in fset) return 1
        }
      }
      return 0
    }
    BEGIN { n = split(q, qp, "-"); qdom = qp[1]; qscr = qp[2]; qfn = (n >= 3 ? qp[3] : "") }
    /^\| (GET|POST|PUT|PATCH|DELETE) / && hit($5) { print }
  ' "$f")
  [ -n "$rows" ] || continue
  found=1
  echo "## $f"
  sed -n '/^| 메서드 /{p;n;p;q}' "$f"
  printf '%s\n' "$rows"

  # 행의 요청·응답 DTO 이름(Page<…>·List<…> 껍데기는 벗긴다)
  want=$(printf '%s\n' "$rows" | awk -F'|' '{ print $7; print $8 }' | grep -oE '[A-Z][A-Za-z0-9]+' | grep -vxE 'Page|List|Map|Set|Void|String|Long|Integer|Boolean' | sort -u)
  shown=""
  depth=0
  while [ -n "$want" ] && [ "$depth" -lt 3 ]; do
    next=""
    for d in $want; do
      case " $shown " in *" $d "*) continue ;; esac
      body=$(awk -v h="### $d" '$0 == h { f = 1; print; next } f && /^#{2,3} / { exit } f' "$f")
      [ -n "$body" ] || continue
      shown="$shown $d"
      printf '\n%s\n' "$body"
      # 필드 타입 칸에서 같은 파일의 다른 DTO
      next="$next $(printf '%s\n' "$body" | awk -F'|' '/^\| [a-z]/ { print $3 }' | grep -oE '[A-Z][A-Za-z0-9]+(Request|Response|Summary|Item|Line|Detail|Dto)' | sort -u | tr '\n' ' ')"
    done
    want=$next
    depth=$((depth + 1))
  done
  for d in $(printf '%s\n' "$rows" | awk -F'|' '{ print $7; print $8 }' | grep -oE '[A-Z][A-Za-z0-9]+' | grep -vxE 'Page|List|Map|Set|Void|String|Long|Integer|Boolean' | sort -u); do
    case " $shown " in *" $d "*) ;; *) echo "(DTO 절 없음: $d)" ;; esac
  done
  echo
done
[ "$found" = 1 ] || { echo "docs/api에 $1 행이 없습니다"; exit 1; }
