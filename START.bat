@echo off
chcp 65001 >nul 2>&1

cd /d "%~dp0"

echo.
echo  ========================================
echo   KEPCO Safety Manager
echo  ========================================
echo.

REM -- Kill old server --
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM -- Check venv --
if not exist "venv\Scripts\python.exe" (
    echo  [ERROR] venv not found. Run INSTALL.bat first.
    pause
    exit /b 1
)

REM ========================================
REM  Auto Repair (security software damage)
REM ========================================

REM -- 1. Restore deleted .html files --
for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" (
        copy "%%f" "frontend\%%~nf.html" >nul
        echo  [REPAIR] %%~nf.html restored
    )
)

REM -- 2. Fix broken Python packages (entry_points metadata) --
venv\Scripts\python.exe -c "from importlib.metadata import distribution; d = distribution('APScheduler'); assert 'interval' in d.read_text('entry_points.txt')" >nul 2>&1
if errorlevel 1 (
    echo  [REPAIR] apscheduler metadata broken, reinstalling...
    venv\Scripts\pip install --force-reinstall apscheduler >nul 2>&1
    echo  [REPAIR] apscheduler fixed
)

REM ========================================

echo  Starting server on port 8000...
echo.

REM -- Start server in new window (stays open with logs) --
start "KEPCO-Server" cmd /k "cd /d %~dp0 && echo Server starting... && echo. && venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --log-level info"

echo  Waiting for server...
timeout /t 4 /nobreak >nul

REM -- Open browser --
start http://localhost:8000

echo.
echo  ========================================
echo   Server started!
echo   URL: http://localhost:8000
echo   Logs: see "KEPCO-Server" window
echo   Stop: run STOP.bat
echo  ========================================
echo.
