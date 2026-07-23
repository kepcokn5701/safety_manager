@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo Repairing...
for %%f in (frontend\*.dat) do (
    copy "%%f" "frontend\%%~nf.html" >nul
    echo  Restored: %%~nf.html
)
echo Done!
timeout /t 3 /nobreak >nul
