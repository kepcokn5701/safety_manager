@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM 포터블 배포판 빌드 (실제 로직은 build.py)
REM   build.bat            -> 버전 자동 (yyMMdd_v1)
REM   build.bat 260723_v3  -> 버전 직접 지정

if not exist "runtime\python\python.exe" (
    echo.
    echo  [오류] runtime\python\python.exe 가 없습니다.
    echo         기존 배포판의 python 폴더를 runtime\python\ 으로 복사하세요.
    echo.
    pause
    exit /b 1
)

"runtime\python\python.exe" build.py %*
if errorlevel 1 (
    echo.
    echo  [오류] 빌드에 실패했습니다. 위 메시지를 확인하세요.
)
pause
