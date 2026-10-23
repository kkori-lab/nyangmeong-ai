#!/bin/sh
# /impl 검증 루프의 기준 파일 잠금. /verify 첫 실패에 기준 파일 지문을 남기고, 잠긴 동안 그 파일을 고치지 못하게 한다.
# 루프가 기획·검증 명령·테스트를 고쳐 통과하는 것을 막는다. 회차와 지문은 /verify(별도 에이전트)만 남긴다.
# 세션을 끊어도 잠금은 이어진다. /end·/start는 지우지 않고 보관(pause)하고, 다음 check·fail이 되살린다(resume).
# 보관 중에는 핸드오프·마일스톤만 고칠 수 있다. 기획이 그 안에 있으므로 첫 실패 때 사본을 떠 두고, check가 사본과 비교할 명령을 함께 낸다.
# 루프를 버리는 것(clear)은 사람이 한다.
# 프론트·백엔드 저장소에 같은 파일이 있다(PROTECTED 목록은 세 저장소 공용). 고칠 때 모두 고친다.
# 사용: sh scripts/verify-loop.sh fail "<실패 항목>" | check | status | pause | resume | clear | guard(훅 전용, stdin JSON)
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" || exit 0
LOCK=.claude/verify-loop.lock
PAUSED=.claude/verify-loop.paused
BASE=.claude/verify-loop.base
TAB=$(printf '\t')
# 잠그는 기준 파일. 없는 경로는 무시된다(프론트·백엔드·AI 공용 목록)
# scripts는 검증이 쓰는 스크립트(check.sh·verify-collect.sh 등)까지 잠근다
PROTECTED="handoff milestones AGENTS.md CLAUDE.md .claude .agents .codex scripts package.json yarn.lock eslint.config.js vite.config.js build.gradle settings.gradle gradle src/test pyproject.toml uv.lock .python-version tests"

snapshot() {
  mkdir -p .claude
  rm -rf "$BASE"
  {
    printf 'round\t0\n'
    # shellcheck disable=SC2086
    git ls-files -co --exclude-standard -- $PROTECTED | while IFS= read -r f; do
      [ -f "$f" ] || continue
      case "$f" in "$LOCK" | "$PAUSED" | "$BASE"/*) continue ;; esac
      printf 'hash\t%s\t%s\n' "$(git hash-object "$f")" "$f"
      case "$f" in
        handoff/* | milestones/*) mkdir -p "$BASE/$(dirname "$f")" && cp "$f" "$BASE/$f" ;;
      esac
    done
  } > "$LOCK"
}

# 바뀐 기준 파일. 핸드오프·마일스톤은 진행 기록도 바뀌므로 첫 실패 때 사본과 비교할 명령을 붙인다
changed() {
  [ -f "$LOCK" ] || return 0
  grep "^hash$TAB" "$LOCK" | while IFS="$TAB" read -r _ oid f; do
    now=$(git hash-object "$f" 2>/dev/null || echo deleted)
    [ "$now" = "$oid" ] && continue
    case "$f" in
      handoff/* | milestones/*) echo "$f (기획 비교: git diff --no-index $BASE/$f $f)" ;;
      *) echo "$f" ;;
    esac
  done
}

block() {
  echo "검증 루프 중에는 기준 파일($1)을 고치지 않습니다. 이 파일을 고쳐야 통과한다면 멈추고 사람에게 이유를 말하세요. 루프를 버리려면 사람이 ! sh scripts/verify-loop.sh clear 를 실행합니다." >&2
  exit 2
}

# 보관한 잠금을 되살린다. 지문은 첫 실패 때 그대로다
resume() {
  [ -f "$PAUSED" ] && mv "$PAUSED" "$LOCK"
  return 0
}

case "$1" in
  fail)
    resume
    [ -f "$LOCK" ] || snapshot
    round=$(( $(grep "^round$TAB" "$LOCK" | cut -f2) + 1 ))
    item=$(printf '%s' "$2" | tr '\t\n' '  ')
    { printf 'round\t%s\n' "$round"; grep -v "^round$TAB" "$LOCK"; printf 'fail\t%s\t%s\n' "$round" "$item"; } > "$LOCK.tmp" && mv "$LOCK.tmp" "$LOCK"
    echo "회차 $round"
    ;;
  check)
    resume
    out=$(changed)
    [ -z "$out" ] && exit 0
    echo "$out"
    exit 1
    ;;
  status)
    if [ -f "$LOCK" ]; then file=$LOCK; state=잠금
    elif [ -f "$PAUSED" ]; then file=$PAUSED; state=보관
    else echo "잠금 없음"; exit 0; fi
    echo "$state 회차 $(grep "^round$TAB" "$file" | cut -f2)"
    grep "^fail$TAB" "$file" | while IFS="$TAB" read -r _ n item; do echo "- ${n}회차: $item"; done
    ;;
  pause)
    [ -f "$LOCK" ] && mv "$LOCK" "$PAUSED"
    exit 0
    ;;
  resume)
    resume
    ;;
  clear)
    rm -rf "$LOCK" "$PAUSED" "$BASE"
    ;;
  guard)
    if [ -f "$LOCK" ]; then file=$LOCK
    elif [ -f "$PAUSED" ]; then file=$PAUSED
    else exit 0; fi
    json=$(cat)
    tool=$(printf '%s' "$json" | grep -o '"tool_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    if [ "$tool" = Bash ]; then
      case "$json" in *verify-loop.lock* | *verify-loop.paused* | *verify-loop.base*) block "$file" ;; esac
      exit 0
    fi
    # Claude: Edit·Write·MultiEdit 는 file_path, NotebookEdit 는 notebook_path. Codex: apply_patch 본문의 "*** Update File: <경로>" 줄
    # JSON 의 \\(Windows 경로 구분자)를 먼저 / 로 바꿔, 남은 \n 이 경로 끝이 되게 한다
    norm=$(printf '%s' "$json" | sed 's/\\\\/\//g')
    paths=$( { printf '%s' "$norm" | grep -oE '"(file|notebook)_path"[[:space:]]*:[[:space:]]*"[^"]*"' |
        sed -e 's/^"[a-z_]*"[[:space:]]*:[[:space:]]*"//' -e 's/"$//'
      printf '%s' "$norm" | grep -oE '\*\*\* (Add File|Update File|Delete File|Move to): [^\\"]*' | sed 's/^\*\*\* [A-Za-z ]*: //'
    } | tr 'A-Z' 'a-z')
    [ -n "$paths" ] || exit 0
    root=$(pwd -W 2>/dev/null || pwd)
    root=$(printf '%s' "$root" | tr 'A-Z\\' 'a-z/')
    printf '%s\n' "$paths" | while IFS= read -r path; do
      case "$path" in
        "$root"/*) rel=${path#"$root"/} ;;
        /*|?:/*) continue ;;
        *) rel=${path#./} ;;
      esac
      # 보관 중에는 /end·/start·/impl이 핸드오프·마일스톤을 고칠 수 있다
      case "$file:$rel" in
        "$PAUSED":handoff/* | "$PAUSED":milestones/*) continue ;;
      esac
      case "$rel" in
        handoff/*|milestones/*|.claude/*|.agents/*|.codex/*|agents.md|claude.md) block "$rel" ;;
      esac
      if grep "^hash$TAB" "$file" | cut -f3 | tr 'A-Z' 'a-z' | grep -qxF "$rel"; then block "$rel"; fi
    done || exit 2
    exit 0
    ;;
  *)
    echo "사용: sh scripts/verify-loop.sh fail \"<실패 항목>\" | check | status | pause | resume | clear | guard" >&2
    exit 2
    ;;
esac
