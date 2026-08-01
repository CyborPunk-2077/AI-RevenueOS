@echo off
REM Destructive. Deletes the local demo database and starts from an empty schema.
REM
REM Deliberately a separate file from RUN_DEMO.cmd: the everyday command must not
REM be one mistyped flag away from dropping a volume. scripts\reset-demo.ps1 asks
REM for typed confirmation before it removes anything.

setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reset-demo.ps1" %*
set EXITCODE=%ERRORLEVEL%

echo.
echo Press any key to close this window.
pause >nul
exit /b %EXITCODE%
