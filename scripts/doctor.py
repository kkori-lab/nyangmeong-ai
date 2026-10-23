"""개발 환경 점검·설정. setup.sh·setup.ps1이 uv sync 다음에 부른다. 직접 실행해도 된다.

    uv run python scripts/doctor.py

이미 맞는 것은 건너뛴다. 사람이 직접 할 일이 남으면 [직접] 줄로 알리고 종료 코드 3으로 끝낸다.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
ENV_EXAMPLE = ROOT / ".env.local.example"

todo_count = 0


def ok(message: str) -> None:
    print(f"  [완료] {message}")


def skip(message: str) -> None:
    print(f"  [있음] {message}")


def todo(message: str) -> None:
    global todo_count
    todo_count += 1
    print(f"  [직접] {message}")


def die(message: str) -> None:
    print(f"\n[중단] {message}", file=sys.stderr)
    sys.exit(1)


def step(title: str) -> None:
    print(f"\n== {title}")


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=check
    )


def ask(prompt: str) -> str | None:
    """입력을 받는다. 입력할 수 없는 환경(CI 등)이면 None."""
    try:
        return input(f"  {prompt}").strip()
    except EOFError:
        return None


def read_env() -> dict[str, str]:
    """.env.local의 KEY=값을 읽는다. 따옴표와 주석은 다루지 않는다(예시 파일 형식 그대로)."""
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def git_setup() -> None:
    step("git")

    # 전역 설정(회사 계정 등)은 건드리지 않고 이 저장소에만 둔다
    for key in ("user.name", "user.email"):
        local = run("git", "config", "--local", key).stdout.strip()
        if local:
            skip(f"git {key} = {local}")
            continue
        value = run("git", "config", "--global", key).stdout.strip()
        answer = ""
        if value:
            answer = ask(f"이 저장소에도 전역 git {key}({value}) 값을 사용하시겠습니까? [Y/n] ")
            if answer is None or answer.lower().startswith("n"):
                value = ""
        # 입력할 수 없는 환경이면 다시 묻지 않는다
        while not value and answer is not None:
            answer = ask(f"이 저장소에 사용할 git {key} 값을 입력하세요: ")
            value = answer or ""
        if value:
            run("git", "config", "--local", key, value, check=True)
            ok(f"git {key} = {value}")
        else:
            todo(f"git config --local {key} <값> 으로 설정해 주세요")

    # 커밋 훅: AI 도구가 붙인 Co-Authored-By 줄을 지운다(.githooks/commit-msg)
    if run("git", "config", "--local", "core.hooksPath").stdout.strip() == ".githooks":
        skip("git 커밋 훅 (.githooks)")
    else:
        run("git", "config", "--local", "core.hooksPath", ".githooks", check=True)
        ok("git 커밋 훅 (.githooks)")


def env_setup() -> dict[str, str]:
    step("설정")

    if ENV_FILE.exists():
        skip(".env.local")
    else:
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        ok(".env.local (예시 복사, AI_MODE=mock). 실제 값은 디스코드에서 받아 바꿔 주세요")
    env = read_env()

    mode = env.get("AI_MODE", "mock")
    if mode not in ("mock", "real"):
        todo(f".env.local 의 AI_MODE={mode} 는 mock 또는 real 이어야 합니다")
    skip(f"AI_MODE = {mode}")

    # 비어 있는 키는 그 기능을 붙일 때 채운다. real 모드에서 외부 API 키가 비면 할 일로 남긴다
    groups = {
        "DB": ("DB_URL", "DB_USERNAME", "DB_PASSWORD"),
        "인증": ("JWT_SECRET_BASE64", "INTERNAL_API_KEY"),
        "암호화": ("CONVERSATION_ENC_KEY",),
        "LLM": ("LLM_API_KEY",),
        "이미지 생성": ("OPENAI_API_KEY",),
        "Google Vision": ("GOOGLE_APPLICATION_CREDENTIALS",),
    }
    for name, keys in groups.items():
        empty = [key for key in keys if not env.get(key)]
        if not empty:
            skip(f"{name} 값 있음")
        elif mode == "real" and name in ("LLM", "이미지 생성", "Google Vision"):
            todo(f"AI_MODE=real 인데 {name} 값이 없습니다: {', '.join(empty)}")
        else:
            print(f"  [비움] {name}: {', '.join(empty)}")

    credentials = env.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials:
        check_google_credentials(Path(credentials))
    return env


def check_google_credentials(path: Path) -> None:
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        todo(f"GOOGLE_APPLICATION_CREDENTIALS 파일이 없습니다: {path}")
        return
    try:
        kind = json.loads(path.read_text(encoding="utf-8")).get("type")
    except (ValueError, OSError):
        kind = None
    if kind == "service_account":
        skip("Google 서비스 계정 키 파일")
    else:
        todo(f"Google 서비스 계정 키 파일 형식이 아닙니다: {path}")


def vscode_cli() -> str | None:
    found = shutil.which("code")
    if found:
        return found
    # 맥은 PATH에 없어도 앱 안의 명령을 쓴다
    mac_app = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
    return str(mac_app) if mac_app.exists() else None


def vscode_setup() -> None:
    step("VS Code")

    code = vscode_cli()
    if not code:
        todo("VS Code를 설치한 뒤 다시 실행해 주세요(확장 설치를 위해)")
        return
    wanted = json.loads((ROOT / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    installed = {
        line.strip().lower() for line in run(code, "--list-extensions").stdout.splitlines()
    }
    for extension in wanted["recommendations"]:
        if extension.lower() in installed:
            skip(f"VS Code 확장 {extension}")
        elif run(code, "--install-extension", extension).returncode == 0:
            ok(f"VS Code 확장 {extension}")
        else:
            todo(f"VS Code 확장 {extension} 설치에 실패했습니다. VS Code에서 직접 설치해 주세요")


def mcp_setup(env: dict[str, str]) -> None:
    step("MCP")

    url = env.get("DMS_MCP_URL", "")
    claude = shutil.which("claude")
    codex = shutil.which("codex")

    if claude:
        # claude.ai 에서 연결한 커넥터는 claude mcp get 으로 찾을 수 없어 목록에서 찾는다
        listed = run(claude, "mcp", "list").stdout.splitlines()
        connector = next(
            (
                line
                for line in listed
                if line.startswith("claude.ai ")
                and (line.lower().startswith("claude.ai dms:") or (url and f": {url} " in line))
            ),
            None,
        )
        if connector:
            skip(f"Claude Code MCP dms ({connector.split(':', 1)[0]} 커넥터)")
        elif run(claude, "mcp", "get", "dms").returncode == 0:
            skip("Claude Code MCP dms")
        elif url:
            if run(claude, "mcp", "add", "-s", "user", "-t", "http", "dms", url).returncode == 0:
                ok("Claude Code MCP dms")
            else:
                todo("Claude Code에 dms MCP를 등록하지 못했습니다. 위 출력을 확인해 주세요")
        else:
            todo(".env.local 에 DMS_MCP_URL 값이 없습니다. 디스코드의 최신 파일로 바꿔 주세요")
        if not connector and "Needs authentication" in run(claude, "mcp", "get", "dms").stdout:
            todo("claude 를 실행해 /mcp 에서 dms 를 고르고 Authenticate 해 주세요")

    if codex:
        if run(codex, "mcp", "get", "dms").returncode == 0:
            skip("Codex MCP dms")
        elif url:
            # 원격 서버는 등록하면 바로 브라우저 로그인이 시작되므로 출력을 가리지 않는다
            if subprocess.run([codex, "mcp", "add", "dms", "--url", url], cwd=ROOT).returncode == 0:
                ok("Codex MCP dms")
            else:
                todo("codex mcp login dms 로 로그인해 주세요")
        else:
            todo(".env.local 에 DMS_MCP_URL 값이 없습니다. 디스코드의 최신 파일로 바꿔 주세요")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check() -> None:
    step("확인")

    python = sys.executable
    for title, args in (
        ("ruff check", (python, "-m", "ruff", "check", ".")),
        ("ruff format", (python, "-m", "ruff", "format", "--check", ".")),
        ("pytest", (python, "-m", "pytest", "-q")),
    ):
        result = run(*args)
        if result.returncode != 0:
            print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
            die(f"{title} 에 실패했습니다. 위 출력을 확인해 주세요.")
        ok(title)

    # 서버가 .env.local을 읽고 뜨는지 /health로 보고 끈다. 포트는 비어 있는 아무 포트를 쓴다
    port = free_port()
    server = subprocess.Popen(
        (python, "-m", "uvicorn", "app.main:app", "--port", str(port)),
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    body = None
    try:
        for _ in range(60):
            if server.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as res:
                    body = json.loads(res.read())
                    break
            except OSError:
                time.sleep(0.5)
    finally:
        server.terminate()
        output = server.communicate(timeout=10)[0]
    if body is None:
        print(output[-3000:])
        die("서버가 뜨지 않았습니다. 위 로그를 확인해 주세요.")
    ok(f"서버 기동 (/health: aiMode={body['aiMode']})")


def main() -> None:
    os.chdir(ROOT)
    git_setup()
    env = env_setup()
    vscode_setup()
    mcp_setup(env)
    check()

    print(f"\n설치가 끝났습니다. 직접 할 일 {todo_count}개(위 [직접] 줄).")
    # 직접 할 일이 남으면 0이 아닌 코드로 끝낸다
    sys.exit(3 if todo_count else 0)


if __name__ == "__main__":
    main()
