@echo off
chcp 65001 >nul
echo ========================================
echo   KEPCO 안전관리 시스템 서버 시작
echo ========================================
echo.

cd /d "%~dp0"

echo [1/2] 서버 시작 중... (포트 8081)
start "SafetyManager-Server" cmd /k "cd /d %~dp0 && venv\Scripts\python -m uvicorn backend.app:app --host 0.0.0.0 --port 8081"

timeout /t 5 /nobreak >nul

echo [2/2] ngrok 터널 시작 중...
start "SafetyManager-Ngrok" cmd /k "cd /d %~dp0 && ngrok.exe http 8081"

timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo   서버 시작 완료!
echo ========================================
echo.
echo   로컬 접속:  http://localhost:8081
echo   외부 접속:  ngrok 창에서 Forwarding URL 확인
echo.
echo   종료하려면 열린 검은 창 2개를 닫으세요.
echo ========================================
pause
