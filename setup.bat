@echo off
setlocal
rem Windows cmd·PowerShell·탐색기 더블클릭에서 setup.ps1을 실행한다. 설치 내용은 모두 setup.ps1에 있다.
rem .ps1을 바로 실행하면 실행 정책(Restricted)에 막히므로 이 파일을 둔다.
for /f "tokens=2 delims=:" %%c in ('chcp') do set "OLDCP=%%c"
chcp 65001 >nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "RC=%ERRORLEVEL%"

rem 탐색기 더블클릭이면 결과를 읽을 수 있게 창이 바로 닫히지 않게 멈춘다(백엔드 setup.bat과 같은 판정)
setlocal EnableDelayedExpansion
if "!cmdcmdline:~-2,1!"==" " pause
endlocal
chcp %OLDCP% >nul
exit /b %RC%
