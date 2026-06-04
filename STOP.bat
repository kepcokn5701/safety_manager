@echo off
echo  Stopping server...
taskkill /F /FI "WINDOWTITLE eq KEPCO-Server" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8081 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo  Done.
pause
