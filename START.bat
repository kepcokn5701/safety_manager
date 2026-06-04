@echo off
chcp 65001 >nul 2>&1

cd /d "%~dp0"

echo.
echo  ========================================
echo   KEPCO Safety Manager
echo  ========================================
echo.

REM -- Kill old server --
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8081 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM -- Check venv --
if not exist "venv\Scripts\python.exe" (
    echo  [ERROR] venv not found. Run INSTALL.bat first.
    pause
    exit /b 1
)

REM -- Restore .html files from .dat backups (security software workaround) --
for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" (
        copy "%%f" "frontend\%%~nf.html" >nul
        echo  Restored: %%~nf.html
    )
)

echo  Starting server on port 8081...
echo.

REM -- Start server in new window (stays open with logs) --
start "KEPCO-Server" cmd /k "cd /d %~dp0 && echo Server starting... && echo. && venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8081 --log-level info"

echo  Waiting for server...
timeout /t 4 /nobreak >nul

REM -- Open browser --
start http://localhost:8081

echo.
echo  ========================================
echo   Server started!
echo   URL: http://localhost:8081
echo   Logs: see "KEPCO-Server" window
echo   Stop: run STOP.bat
echo  ========================================
echo.
