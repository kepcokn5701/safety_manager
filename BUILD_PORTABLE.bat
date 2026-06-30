@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo  ========================================
echo   포터블 배포판 빌드 (개발자용)
echo  ========================================
echo.

if not exist ".env" (
    echo  [ERROR] .env 파일이 없습니다! 먼저 .env를 설정하세요.
    pause
    exit /b 1
)

echo  [INFO] .env의 API 키가 배포판에 포함됩니다.
echo         받는 사람은 API 키를 몰라도 됩니다.
echo.

REM Use venv python if available, else system python
if exist "venv\Scripts\python.exe" (
    set PYEXE=venv\Scripts\python.exe
) else (
    set PYEXE=python
)

%PYEXE% _build_portable.py
if errorlevel 1 (
    echo.
    echo  [ERROR] 빌드 실패. 위의 에러 메시지를 확인하세요.
)
pause
