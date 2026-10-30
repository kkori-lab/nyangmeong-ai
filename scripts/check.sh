#!/bin/sh
# 검증 명령. AGENTS.md·verify-collect.sh·end-check.sh·pr-prep.sh·CI가 모두 이 파일을 부른다. 검사를 바꿀 때는 이 파일과 scripts/doctor.py의 check()를 함께 고친다(doctor.py는 Windows에서 sh 없이 돌아야 해서 같은 검사를 Python으로 부른다).
# 실패한 검사의 출력만 보여 준다. 종료 코드는 처음 실패한 검사의 것이다.
# 사용: sh scripts/check.sh
cd "$(git rev-parse --show-toplevel)" || exit 1

run() {
  title=$1
  shift
  out=$("$@" 2>&1)
  code=$?
  if [ "$code" != 0 ]; then
    echo "$title → $code"
    printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | tail -60
    exit "$code"
  fi
}

run "ruff check" uv run ruff check .
run "ruff format --check" uv run ruff format --check .
run "pytest" uv run pytest -q
echo "ruff check · ruff format · pytest 통과"
