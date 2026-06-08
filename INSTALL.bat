@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo   KEPCO Safety Manager - Install
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] Creating virtual environment...
if not exist venv (
    python -m venv venv
    echo     Created
) else (
    echo     Already exists
)

echo.
echo [2/3] Installing packages... (1-2 min)
set PYTHONUTF8=1
venv\Scripts\pip install fastapi uvicorn sqlalchemy asyncpg aiosqlite pydantic-settings httpx pywebpush cryptography apscheduler openpyxl xlrd pandas python-multipart --quiet
echo     Done

echo.
echo [3/3] Checking .env file...
if not exist .env (
    if exist .env.example (
        copy .env.example .env
        echo     .env created from .env.example
    ) else (
        echo     [WARNING] .env.example not found. Create .env manually.
    )
) else (
    echo     .env already exists
)

echo.
echo ========================================
echo   Install complete!
echo.
echo   Start server: START.bat
echo   URL: http://localhost:8000
echo ========================================
pause
