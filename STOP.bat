@echo off
echo Stopping server...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Server stopped.
timeout /t 2 /nobreak >nul
