@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo  ========================================
echo   HTML File Repair Tool
echo  ========================================
echo.

set COUNT=0

for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" (
        copy "%%f" "frontend\%%~nf.html" >nul
        echo  [RESTORED] %%~nf.html
        set /a COUNT+=1
    ) else (
        echo  [OK] %%~nf.html
    )
)

echo.
if %COUNT% GTR 0 (
    echo  %COUNT% files restored from .dat backups.
) else (
    echo  All HTML files are intact. No repair needed.
)

echo.
echo  ========================================
pause
