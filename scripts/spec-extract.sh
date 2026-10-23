#!/bin/sh
# 기능명세서 엑셀의 "기능 목록" 시트에서 화면 ID 하나의 행만 글자로 뽑는다. /start 기획이 문서 전체 대신 이 결과만 읽는다.
# 명세서마다 시트 순서, 공유 문자열(sharedStrings) 여부, x: 접두사, 숫자 문자 참조(&#50836;)가 달라서 시트 이름("기능 목록")과 머리글("화면 ID")로 찾는다.
# 화면 ID 칸은 병합 셀이라 첫 행에만 값이 있다. 빈 칸은 위 행의 화면 ID를 이어 쓴다.
# 프론트엔드 저장소에 같은 파일이 있다. 고칠 때 둘 다 고친다.
# 사용: sh scripts/spec-extract.sh <기능명세서.xlsx> <SCR-ID>
[ $# = 2 ] || { echo "사용: sh scripts/spec-extract.sh <기능명세서.xlsx> <SCR-ID>" >&2; exit 2; }
[ -f "$1" ] || { echo "파일이 없습니다: $1" >&2; exit 2; }
command -v unzip >/dev/null || { echo "unzip이 필요합니다" >&2; exit 2; }

# 태그 하나를 한 줄로. 글자 안의 줄바꿈은 \001로 남긴다
tags() { unzip -p "$1" "$2" 2>/dev/null | tr -d '\r' | tr '\n' '\001' | tr '<' '\n'; }

rid=$(tags "$1" xl/workbook.xml | grep -E '^([A-Za-z]+:)?sheet ' | grep 'name="기능 목록"' |
  sed -n 's/.* r:id="\([^"]*\)".*/\1/p' | head -1)
[ -n "$rid" ] || { echo "\"기능 목록\" 시트가 없습니다: $1" >&2; exit 1; }
sheet=$(tags "$1" xl/_rels/workbook.xml.rels | grep "Id=\"$rid\"" |
  sed -n 's/.*Target="\([^"]*\)".*/\1/p' | head -1)
case "$sheet" in /*) sheet=${sheet#/} ;; *) sheet="xl/$sheet" ;; esac

# 바이트 단위로 처리해야 숫자 문자 참조를 UTF-8로 직접 만들 수 있다
{ tags "$1" xl/sharedStrings.xml; printf '
@@SHEET@@
'; tags "$1" "$sheet"; } | LC_ALL=C awk -v id="$2" '
  BEGIN { for (i = 0; i < 16; i++) hex[substr("0123456789abcdef", i + 1, 1)] = i }
  function utf8(n) {
    if (n < 128) return sprintf("%c", n)
    if (n < 2048) return sprintf("%c%c", 192 + int(n / 64), 128 + n % 64)
    if (n < 65536) return sprintf("%c%c%c", 224 + int(n / 4096), 128 + int(n / 64) % 64, 128 + n % 64)
    return sprintf("%c%c%c%c", 240 + int(n / 262144), 128 + int(n / 4096) % 64, 128 + int(n / 64) % 64, 128 + n % 64)
  }
  function num(s,   n, i) {
    s = tolower(s)
    if (substr(s, 1, 1) != "x") return s + 0
    n = 0; for (i = 2; i <= length(s); i++) n = n * 16 + hex[substr(s, i, 1)]
    return n
  }
  function dec(s,   out, i, j, e) {
    out = ""
    while (i = index(s, "&")) {
      out = out substr(s, 1, i - 1); s = substr(s, i); j = index(s, ";")
      e = (j > 1 && j < 12) ? substr(s, 2, j - 2) : ""
      if (e == "lt") out = out "<"
      else if (e == "gt") out = out ">"
      else if (e == "quot") out = out "\""
      else if (e == "apos") out = out "\047"
      else if (e == "amp") out = out "&"
      else if (e ~ /^#[0-9]+$/ || e ~ /^#[xX][0-9a-fA-F]+$/) { e = num(substr(e, 2)); out = out (e == 10 ? "\001" : utf8(e)) }
      else { out = out "&"; s = substr(s, 2); continue }
      s = substr(s, j + 1)
    }
    return out s
  }
  function tag(   t, e) { t = $0; e = (substr(t, 1, 1) == "/"); if (e) t = substr(t, 2); sub(/[ >\/].*/, "", t); sub(/^[A-Za-z]+:/, "", t); return (e ? "/" : "") t }
  function body(   s) { s = $0; if (!sub(/^[^>]*>/, "", s)) return ""; return dec(s) }
  function attr(n,   s) { s = $0; if (!match(s, " " n "=\"[^\"]*\"")) return ""; s = substr(s, RSTART, RLENGTH); sub(/^[^"]*"/, "", s); sub(/"$/, "", s); return s }
  function closed() { return $0 ~ /\/>[\001]*$/ }
  function clean(s) { gsub(/\001/, "\n  ", s); gsub(/[ \t]+\n/, "\n", s); sub(/^[ \t\n]+/, "", s); sub(/[ \t\n]+$/, "", s); return s }
  function endcell() { cell[col] = (ctype == "s" ? ss[val + 0] : val); incell = 0 }
  function sortcols(   i, j, x) {
    for (i = 2; i <= n; i++) {
      x = cols[i]
      for (j = i - 1; j > 0 && (length(cols[j]) > length(x) || (length(cols[j]) == length(x) && cols[j] > x)); j--) cols[j + 1] = cols[j]
      cols[j + 1] = x
    }
  }
  function joinrow(   i, s) { s = ""; for (i = 1; i <= n; i++) s = s (i > 1 ? " | " : "") clean(cell[cols[i]]); return s }
  function endrow(   c, sc, any) {
    if (!hcol) {
      for (c in cell) if (clean(cell[c]) == "화면 ID") hcol = c
      if (hcol) { n = 0; for (c in cell) if (clean(cell[c]) != "") cols[++n] = c; sortcols(); header = joinrow() }
    } else {
      sc = clean(cell[hcol]); if (sc != "") cur = sc
      if (index(cur, id)) {
        any = 0; for (c in cell) if (clean(cell[c]) != "") any = 1
        if (any) { if (!shown) { print header; shown = 1 } print joinrow(); found = 1 }
      }
    }
    split("", cell)
  }

  $0 == "@@SHEET@@" { sheet = 1; next }
  !sheet {
    t = tag()
    if (t == "si") { si = ""; skip = 0 }
    else if (t == "rPh") skip = 1
    else if (t == "/rPh") skip = 0
    else if (t == "t" && !skip) si = si body()
    else if (t == "/si") ss[nss++] = si
    next
  }
  {
    t = tag()
    if (t == "row") { split("", cell); if (closed()) endrow() }
    else if (t == "/row") endrow()
    else if (t == "c") { col = attr("r"); sub(/[0-9]+$/, "", col); ctype = attr("t"); val = ""; incell = 1; if (closed()) endcell() }
    else if (t == "v" && incell) val = body()
    else if (t == "t" && incell) val = val body()
    else if (t == "/c" && incell) endcell()
  }
  END {
    if (!hcol) { print "머리글에 \"화면 ID\" 칸이 없습니다" > "/dev/stderr"; exit 1 }
    if (!found) { print id " 화면을 찾지 못했습니다" > "/dev/stderr"; exit 1 }
  }
'
