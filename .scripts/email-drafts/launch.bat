@echo off
setlocal

set PORT=4747
set SCRIPT_DIR=%~dp0

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%PORT%/api/drafts' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1

if %ERRORLEVEL% EQU 0 (
    echo Dashboard already running at http://localhost:%PORT%
) else (
    echo Starting email drafts dashboard...
    start "Email Drafts Dashboard" /min cmd /c "node "%SCRIPT_DIR%server.cjs""
    timeout /t 2 /nobreak >nul
)

start http://localhost:%PORT%
