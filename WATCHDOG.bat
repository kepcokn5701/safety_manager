@echo off
REM ============================================================
REM  KEPCO Safety Manager - 상시구동 감시기 (Watchdog)
REM  - 작업스케줄러가 3분마다 이 파일을 실행
REM  - 서버가 죽어있으면 되살리고, 보안SW가 지운 .html을 복원
REM  - 멱등(idempotent): 서버가 살아있으면 아무것도 하지 않음
REM ============================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if not exist logs mkdir logs

REM -- 1) 보안SW가 삭제한 .html 복원 (.dat 백업에서) --
for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" copy "%%f" "frontend\%%~nf.html" >nul 2>&1
)

REM -- 2) Python 실행기 자동 감지 (포터블: python\ / 개발: venv\) --
set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [%date% %time%] python 실행기를 찾을 수 없음 >> logs\watchdog.log
    exit /b 1
)

REM -- 3) 8000 포트가 LISTENING 아니면 서버 기동 (헤드리스) --
netstat -aon | findstr :8000 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] 서버 미동작 감지 -^> 재시작 >> logs\watchdog.log
    start "KEPCO-Server" /min cmd /c "cd /d "%~dp0" && "%PY%" -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --log-level info >> logs\server.log 2>&1"
)
