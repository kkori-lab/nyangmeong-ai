# 냥멍케어 AI 개발 환경 설치(Windows). setup.bat이 이 파일을 실행한다.
# 이 파일은 Python 없이 돌아야 하는 일(Git 확인, Claude Code·uv 설치, uv sync)만 한다. 나머지는 scripts/doctor.py가 한다.
# 이미 있으면 건너뛴다. 여러 번 실행해도 된다. 인자는 doctor.py에 그대로 넘긴다.
# Windows PowerShell 5.1이 한글을 읽도록 이 파일은 BOM 있는 UTF-8로 저장한다.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

function Ok($m) { Write-Host "  [완료] $m" }
function Skip($m) { Write-Host "  [있음] $m" }
function Die($m) { Write-Host "`n[중단] $m"; exit 1 }
function Step($m) { Write-Host "`n== $m" }
function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# Claude Code와 uv의 공식 설치 스크립트가 쓰는 폴더
$LocalBin = Join-Path $HOME '.local\bin'

# 새 창에서도 잡히도록 사용자 PATH에 넣는다. %USERPROFILE% 같은 항목이 풀리지 않게 레지스트리 값을 그대로 다시 쓴다
function Add-UserPath($dir) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
  $parts = @(([string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')) -split ';' | Where-Object { $_ })
  $norm = { param($p) [Environment]::ExpandEnvironmentVariables($p).TrimEnd('\').ToLowerInvariant() }
  $want = & $norm $dir
  if (-not ($parts | Where-Object { (& $norm $_) -eq $want })) {
    $key.SetValue('Path', (($parts + $dir) -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
  }
  if (-not (($env:Path -split ';') | Where-Object { (& $norm $_) -eq $want })) { $env:Path = "$dir;$env:Path" }
}

Step '도구'

if (-not (Has git)) { Die 'Git이 없습니다. Git for Windows를 설치한 뒤 다시 실행해 주세요.' }
Skip ((git --version) -replace '^git version ', 'Git ')

# AI 도구: Claude Code·Codex 중 하나라도 있으면 그대로 쓴다. 둘 다 없으면 Claude Code를 설치한다. 로그인은 처음 실행할 때 직접 한다
if ((Has claude) -or (Has codex)) {
  if (Has claude) { Skip "Claude Code $((claude --version) -split ' ' | Select-Object -First 1)" }
  if (Has codex) { Skip "Codex $((codex --version) -split ' ' | Select-Object -Last 1)" }
} else {
  Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
  Add-UserPath $LocalBin
  if (-not (Has claude)) { Die 'Claude Code 설치에 실패했습니다. 위 출력을 확인해 주세요.' }
  Ok "Claude Code $((claude --version) -split ' ' | Select-Object -First 1)"
}

# uv: Python 설치와 가상환경·의존성을 맡는다. 공식 설치 스크립트로 Claude Code와 같은 폴더에 설치한다
if (Has uv) {
  Skip "uv $((uv --version) -split ' ' | Select-Object -Index 1)"
} else {
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  Add-UserPath $LocalBin
  if (-not (Has uv)) { Die 'uv 설치에 실패했습니다. 위 출력을 확인해 주세요.' }
  Ok "uv $((uv --version) -split ' ' | Select-Object -Index 1)"
}

# .python-version의 Python이 없으면 uv가 내려받는다. PC에 있는 다른 Python은 건드리지 않는다
uv sync --quiet
if ($LASTEXITCODE -ne 0) { Die 'uv sync 에 실패했습니다. 위 출력을 확인해 주세요.' }
Ok "Python $(uv run python -c 'import platform; print(platform.python_version())') + 의존성 (.venv)"

$env:PYTHONUTF8 = '1'
uv run python scripts/doctor.py @args
exit $LASTEXITCODE
