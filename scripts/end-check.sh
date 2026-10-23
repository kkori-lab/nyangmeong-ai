#!/bin/sh
# /end의 기계적인 단계: 검증 명령(1번), 한 일(3번), 검증 루프 보관(4번), 핸드오프 점검, 스킬 동기화(6번), 커밋 종류와 푸시·PR 상태(7번).
# 끝 판정·핸드오프 내용·커밋 메시지는 /end가 이 출력으로 정한다.
# 사용: sh scripts/end-check.sh [--no-build]   (이 세션에 검증 보고가 있으면 --no-build)
cd "$(git rev-parse --show-toplevel)" || exit 1
branch=$(git branch --show-current)
name=${branch%%/*}
hf=handoff/$name.md

echo "## 검증 명령"
if [ "$1" = --no-build ]; then
  echo "건너뜀(검증 보고의 판정을 쓴다)"
else
  # 검증 명령은 scripts/check.sh 하나다(AGENTS.md)
  sh scripts/check.sh
  echo "sh scripts/check.sh → $?"
fi

echo "## 한 일"
git status -sb
git log --since=midnight --oneline

# 보관은 지우는 것이 아니다. clear는 /end가 끝으로 판정한 뒤에만 부른다
echo "## 검증 루프"
case "$(sh scripts/verify-loop.sh status)" in "잠금 회차"*) sh scripts/verify-loop.sh pause && echo "보관함" ;; esac
sh scripts/verify-loop.sh status

echo "## 핸드오프"
lines=$(cat "$hf" 2>/dev/null | wc -l | tr -d ' ')
echo "$hf: ${lines}줄$([ "$lines" -gt 60 ] && echo " (60줄 넘음. 끝난 항목을 지운다)")"
# 공개 저장소다. 개인 PC 경로와 비밀값처럼 보이는 줄
leak=$(grep -nE '[A-Za-z]:[\\/]+Users[\\/]|/c/Users/|/home/[a-z]|/Users/[A-Za-z]|(password|passwd|secret|api[_-]?key|token)[[:space:]]*[=:][[:space:]]*[^[:space:]`]{8,}' "$hf" milestones/"$name".md 2>/dev/null)
echo "개인 경로·비밀값 의심: ${leak:-없음}"

echo "## 스킬 동기화"
cp -R .claude/skills/. .agents/skills/
d=$(diff -r .claude/skills .agents/skills)
echo "${d:-차이 없음}"

echo "## 커밋 종류"
changed=$(git status --porcelain | cut -c4- | sed 's/.* -> //')
# 공용 하네스: 스킬과 그 스킬이 부르는 scripts/
harness=$(printf '%s\n' "$changed" | grep '^\(\.claude/skills\|\.agents/skills\|scripts\)/')
code_files=$(printf '%s\n' "$changed" | grep . | grep -v '^\(handoff\|milestones\)/' | grep -v '^\(\.claude/skills\|\.agents/skills\|scripts\)/')
if [ -z "$changed" ]; then echo "바뀐 파일 없음"
elif [ -n "$code_files" ]; then echo "feat 또는 fix (코드·문서 변경 있음)"; printf '%s\n' "$code_files" | sed 's/^/- /'
else echo "docs: 핸드오프 갱신 (handoff/·milestones/만)"; fi
[ -n "$harness" ] && { echo "공용 하네스 변경이 섞여 있습니다. 커밋에서 빼고 PR로 따로 올리세요:"; printf '%s\n' "$harness" | sed 's/^/- /'; }

echo "## 푸시·PR"
if git rev-parse -q --verify "origin/$branch" >/dev/null; then
  ahead=$(git log "origin/$branch..HEAD" --oneline)
  echo "올릴 커밋: ${ahead:-없음}"
else
  echo "origin/$branch 없음(처음 푸시)"
fi
if command -v gh >/dev/null; then
  pr=$(gh pr list --head "$branch" --state open --json number,title --jq '.[] | "#\(.number) \(.title)"' 2>/dev/null)
  echo "열린 PR: ${pr:-없음}"
else
  echo "gh 없음"
fi
exit 0
