#!/bin/sh
# /verify 1~4번의 사실 수집: 기획, 바뀐 것, 검증 명령 종료 코드, 기획 밖 변경 후보, 새 의존성, 기준 변경.
# 판정은 하지 않는다. 검증 에이전트가 이 출력과 diff를 보고 판정한다.
# 기획 밖 변경 후보는 기획·추가 요청에 경로나 파일 이름이 적히지 않은 파일이다. 보조 파일인지는 에이전트가 정한다.
# 사용: sh scripts/verify-collect.sh
cd "$(git rev-parse --show-toplevel)" || exit 1
branch=$(git branch --show-current)
hf=handoff/${branch%%/*}.md
plan=$(awk '/^## 지금 하는 것/ { f = 1; next } /^## / { f = 0 } f' "$hf" 2>/dev/null)

echo "## 기획"
if ! printf '%s\n' "$plan" | grep -q '완료 조건\|새 의존성:'; then
  echo "기획 없음"
  exit 3
fi
printf '%s\n' "$plan" | grep -v '^[[:space:]]*$'

start=$(printf '%s\n' "$plan" | grep -m1 -o '시작 [0-9]\{4\}-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]' | cut -c8-)
echo "## 바뀐 것 (시작: ${start:-못 찾음, 오늘 0시로 봄})"
start=${start:-midnight}
git status -sb
git diff HEAD --stat
git log --since="$start" --no-merges --stat --format='%h %s'

echo "## 검증 명령"
# 검증 명령은 scripts/check.sh 하나다(AGENTS.md)
sh scripts/check.sh
echo "sh scripts/check.sh → $?"

# 시작 뒤 내 커밋·작업 트리·새 파일에서 바뀐 파일. develop에서 합쳐 온 것은 빠진다
files=$( { git log --since="$start" --no-merges --format= --name-only; git diff HEAD --name-only; git ls-files -o --exclude-standard; } | grep . | sort -u)

echo "## 기획 밖 변경 후보"
# 기획에 `scripts/`처럼 폴더로 적은 것
dirs=$(printf '%s\n' "$plan" | grep -oE '`[^` ]+/`' | tr -d '`')
out_plan=$(printf '%s\n' "$files" | while IFS= read -r f; do
  case "$f" in handoff/* | milestones/*) continue ;; esac
  for d in $dirs; do case "$f" in "$d"*) continue 2 ;; esac; done
  base=${f##*/}
  printf '%s\n' "$plan" | grep -qF -- "$base" && continue
  # 확장자 없이 클래스 이름만 적은 경우
  printf '%s\n' "$plan" | grep -qw -- "${base%.*}" && continue
  echo "$f"
done)
echo "${out_plan:-없음}"
printf '%s\n' "$files" | grep '^\(handoff\|milestones\)/' | sed 's/^/(세지 않음) /'

echo "## 새 의존성"
printf '%s\n' "$plan" | grep '새 의존성:' || echo "기획에 새 의존성 줄 없음"
# pyproject.toml의 의존성 목록(dependencies·dependency-groups)에 들어온 "패키지>=버전" 줄
deps=$( { git log --since="$start" --no-merges -p --format= -- pyproject.toml; git diff HEAD -- pyproject.toml; } |
  grep -E '^\+[[:space:]]*"[A-Za-z0-9_.-]+(\[[^]]*\])?([<>=!~][^"]*)?",?[[:space:]]*$')
echo "pyproject.toml에 들어온 줄: ${deps:-없음}"

echo "## 기준 변경 (verify-loop.sh check)"
changed=$(sh scripts/verify-loop.sh check)
echo "${changed:-없음}"
exit 0
