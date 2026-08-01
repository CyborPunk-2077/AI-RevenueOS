@echo off
REM Double-click launcher for the AI RevenueOS local demo.
REM
REM Everything real happens in scripts\demo.ps1; this exists so the demo can be
REM started from Explorer without opening a terminal or setting an execution
REM policy. The window is held open at the end so a failure message stays
REM readable instead of vanishing with the console.

setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\demo.ps1" %*
set EXITCODE=%ERRORLEVEL%

echo.
if not "%EXITCODE%"=="0" (
  echo The demo did not start cleanly ^(exit code %EXITCODE%^).
  echo See the messages above, then try:  docker compose logs api web
)
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
