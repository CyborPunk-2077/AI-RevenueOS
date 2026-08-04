@echo off
setlocal
echo =======================================================
echo     AI RevenueOS - One-Click Developer Environment Setup
echo =======================================================
echo.

:: Ensure we run in the directory of the script
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "^
Write-Host '1. Checking for uv (Python package manager)...' -ForegroundColor Cyan; ^
if (!(Get-Command uv -ErrorAction SilentlyContinue)) { ^
    Write-Host '   uv is missing. Please install it or ensure it is in your PATH.' -ForegroundColor Red; ^
    exit 1; ^
} ^
^
Write-Host '2. Creating Python 3.12 virtual environment (.venv)...' -ForegroundColor Cyan; ^
uv venv .venv --python 3.12; ^
if ($LASTEXITCODE -ne 0) { Write-Host '   Failed to create virtual environment.' -ForegroundColor Red; exit 1; } ^
^
Write-Host '3. Compiling and installing backend dependencies...' -ForegroundColor Cyan; ^
uv pip compile backend/pyproject.toml --python-version 3.12 --generate-hashes --output-file backend/requirements.lock; ^
uv pip compile backend/pyproject.toml --extra dev --python-version 3.12 --generate-hashes --output-file backend/requirements-dev.lock; ^
uv pip install --require-hashes --no-deps -r backend/requirements-dev.lock; ^
if ($LASTEXITCODE -ne 0) { Write-Host '   Failed to install backend dependencies.' -ForegroundColor Red; exit 1; } ^
^
Write-Host '4. Checking for pnpm and installing frontend dependencies...' -ForegroundColor Cyan; ^
if (Get-Command pnpm -ErrorAction SilentlyContinue) { ^
    pnpm install; ^
} else { ^
    Write-Host '   pnpm is missing! Skipping frontend install. Please install pnpm (npm install -g pnpm).' -ForegroundColor Yellow; ^
} ^
^
Write-Host '=======================================================' -ForegroundColor Green; ^
Write-Host 'Setup Complete! Your environment is ready.' -ForegroundColor Green; ^
Write-Host '=======================================================' -ForegroundColor Green; ^
"

echo.
pause
