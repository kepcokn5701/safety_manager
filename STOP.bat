@echo off
chcp 65001 >nul
echo 서버 종료 중...
taskkill /F /FI "WINDOWTITLE eq SafetyManager*" >nul 2>&1
taskkill /F /IM ngrok.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8081 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
echo 서버 종료 완료.
pause
