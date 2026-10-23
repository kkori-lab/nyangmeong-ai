#!/usr/bin/env bash
# 냥멍케어 AI 개발 환경 설치(맥). 터미널에서 `bash setup.sh`로 실행한다. Windows는 setup.bat이다.
# 이 파일은 Python 없이 돌아야 하는 일(Git 확인, Claude Code·uv 설치, uv sync)만 한다. 나머지는 scripts/doctor.py가 한다.
# 이미 있으면 건너뛴다. 여러 번 실행해도 된다. 인자는 doctor.py에 그대로 넘긴다
set -euo pipefail
cd "$(dirname "$0")"

ok()   { printf '  [완료] %s\n' "$1"; }
skip() { printf '  [있음] %s\n' "$1"; }
die()  { printf '\n[중단] %s\n' "$1" >&2; exit 1; }
step() { printf '\n== %s\n' "$1"; }

[ "$(uname -s)" = Darwin ] || die "맥 전용 스크립트입니다. Windows는 setup.bat을 실행해 주세요."

# 셸 설정 파일에 한 줄을 넣는다. 이미 있으면 그대로 둔다
persist_line() {
  touch "$1"
  grep -qxF "$2" "$1" || printf '\n%s\n' "$2" >> "$1"
}

# Claude Code와 uv의 공식 설치 스크립트가 쓰는 폴더. 새 창에서도 잡히도록 ~/.zshrc에 넣는다
LOCAL_BIN="$HOME/.local/bin"
export PATH="$LOCAL_BIN:$PATH"

step "도구"

command -v git >/dev/null || die "Git이 없습니다. xcode-select --install 로 설치한 뒤 다시 실행해 주세요."
skip "Git $(git --version | awk '{print $3}')"

# AI 도구: Claude Code·Codex 중 하나라도 있으면 그대로 쓴다. 둘 다 없으면 Claude Code를 설치한다. 로그인은 처음 실행할 때 직접 한다
if command -v claude >/dev/null || command -v codex >/dev/null; then
  command -v claude >/dev/null && skip "Claude Code $(claude --version 2>/dev/null | awk '{print $1}')"
  command -v codex >/dev/null && skip "Codex $(codex --version 2>/dev/null | awk '{print $NF}')"
else
  curl -fsSL https://claude.ai/install.sh | bash
  command -v claude >/dev/null || die "Claude Code 설치에 실패했습니다. 위 출력을 확인해 주세요."
  persist_line "$HOME/.zshrc" "export PATH=\"$LOCAL_BIN:\$PATH\""
  ok "Claude Code $(claude --version 2>/dev/null | awk '{print $1}')"
fi

# uv: Python 설치와 가상환경·의존성을 맡는다. Homebrew가 있으면 brew로, 없으면 공식 설치 스크립트로 설치한다
if command -v uv >/dev/null; then
  skip "uv $(uv --version | awk '{print $2}')"
else
  if command -v brew >/dev/null; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    persist_line "$HOME/.zshrc" "export PATH=\"$LOCAL_BIN:\$PATH\""
  fi
  command -v uv >/dev/null || die "uv 설치에 실패했습니다. 위 출력을 확인해 주세요."
  ok "uv $(uv --version | awk '{print $2}')"
fi

# .python-version의 Python이 없으면 uv가 내려받는다. PC에 있는 다른 Python은 건드리지 않는다
uv sync --quiet || die "uv sync 에 실패했습니다. 위 출력을 확인해 주세요."
ok "Python $(uv run python -c 'import platform; print(platform.python_version())') + 의존성 (.venv)"

exec uv run python scripts/doctor.py "$@"
