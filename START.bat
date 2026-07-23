@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo  ========================================
echo   한국전력공사 경남본부 안전관리 시스템
echo  ========================================
echo.

REM -- Kill old server --
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM -- Restore deleted .html --
for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" (
        copy "%%f" "frontend\%%~nf.html" >nul
        echo  [REPAIR] %%~nf.html restored
    )
)


echo  Starting server on port 8000...
echo.
start "SafetyManager" cmd /k "cd /d %~dp0 && echo Server starting... && echo. && python\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --log-level info"
timeout /t 4 /nobreak >nul
start http://localhost:8000
echo.
echo  ========================================
echo   서버가 시작되었습니다!
echo   주소: http://localhost:8000
echo   종료: STOP.bat 실행
echo  ========================================
echo.
