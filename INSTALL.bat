@echo off
chcp 65001 >nul
echo ========================================
echo   KEPCO 안전관리 시스템 - 초기 설치
echo ========================================
echo.

cd /d "%~dp0"

echo [1/4] Python 가상환경 생성...
if not exist venv (
    python -m venv venv
    echo     가상환경 생성 완료
) else (
    echo     가상환경 이미 존재
)

echo.
echo [2/4] 패키지 설치 중... (1~2분 소요)
set PYTHONUTF8=1
venv\Scripts\pip install fastapi uvicorn sqlalchemy asyncpg aiosqlite pydantic-settings httpx pywebpush cryptography apscheduler openpyxl xlrd pandas python-multipart --quiet
echo     패키지 설치 완료

echo.
echo [3/4] .env 설정 파일 확인...
if not exist .env (
    copy .env.example .env
    echo     .env 파일 생성 완료 (.env.example 복사)
) else (
    echo     .env 파일 이미 존재
)

echo.
echo [4/4] ngrok 확인...
if exist ngrok.exe (
    echo     ngrok.exe 존재
) else (
    echo     [주의] ngrok.exe가 없습니다.
    echo     https://ngrok.com/download 에서 다운로드하여 이 폴더에 넣으세요.
)

echo.
echo ========================================
echo   설치 완료!
echo.
echo   서버 시작: START.bat 더블클릭
echo ========================================
pause
