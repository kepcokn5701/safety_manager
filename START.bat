@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title 폭염 안전관리 시스템

REM ============================================================
REM  KEPCO Safety Manager - 통합 시작 스크립트
REM
REM  운영자는 이 파일 하나만 실행하면 된다. 다음을 모두 처리:
REM    1) 보안SW가 지운 .html 복원
REM    2) 상시구동(24시간 자동 감시) 최초 1회 자동 등록
REM    3) 서버 기동 (이미 켜져 있으면 그대로 사용)
REM    4) 브라우저 열기
REM
REM  멱등(idempotent): 몇 번을 눌러도 안전하다.
REM ============================================================

set "TASK=KEPCO_SafetyManager_AlwaysOn"

echo.
echo  ============================================
echo    한국전력공사 경남본부
echo    폭염 안전관리 시스템
echo  ============================================
echo.

REM -- 1) 보안SW가 삭제한 .html 복원 --------------------------
set RESTORED=0
for %%f in (frontend\*.dat) do (
    if not exist "frontend\%%~nf.html" (
        copy "%%f" "frontend\%%~nf.html" >nul 2>&1
        set /a RESTORED+=1
    )
)
if %RESTORED% GTR 0 (
    echo   [복구] 삭제된 화면 파일 %RESTORED%개를 되살렸습니다.
) else (
    echo   [확인] 화면 파일 정상
)

REM -- 2) 상시구동 등록 (최초 1회만) --------------------------
schtasks /Query /TN "%TASK%" >nul 2>&1
if not errorlevel 1 (
    echo   [확인] 24시간 자동 감시 켜져 있음
    goto :server
)

echo.
echo   --------------------------------------------
echo    처음 실행입니다. 24시간 자동 감시를 켭니다.
echo.
echo    서버가 꺼지면 3분 안에 스스로 다시 켜지고,
echo    PC를 재부팅해도 자동으로 켜집니다.
echo    (주말에도 문자가 정상 발송됩니다^)
echo.
echo    잠시 후 "허용하시겠습니까?" 창이 뜨면
echo    [예] 를 눌러 주세요.  -- 최초 1회뿐입니다.
echo   --------------------------------------------
echo.
timeout /t 4 /nobreak >nul

powershell -NoProfile -Command ^
    "try { Start-Process -FilePath '%~dp0_setup_watchdog.bat' -Verb RunAs -Wait -ErrorAction Stop } catch { }" >nul 2>&1

schtasks /Query /TN "%TASK%" >nul 2>&1
if not errorlevel 1 (
    echo   [완료] 24시간 자동 감시를 켰습니다.
    goto :server
)

REM -- 관리자 권한을 못 받았을 때: 사용자 계정 감시로 대체 --
schtasks /Create /TN "%TASK%" /TR "\"%~dp0WATCHDOG.bat\"" /SC MINUTE /MO 3 /F >nul 2>&1
if not errorlevel 1 (
    echo   [완료] 자동 감시를 켰습니다.
    echo          단, 로그아웃하면 감시가 멈춥니다. PC를 켜둔 채로 두세요.
) else (
    echo   [건너뜀] 자동 감시를 켜지 못했습니다. 서버는 정상 시작합니다.
    echo            서버가 꺼지면 이 파일을 다시 실행하세요.
)

REM -- 3) 서버 기동 -------------------------------------------
:server
netstat -aon | findstr :8000 | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
    echo   [확인] 서버가 이미 켜져 있습니다.
    goto :browser
)

echo   [시작] 서버를 켜는 중...
REM 이 스크립트가 이미 cd /d "%~dp0" 했으므로 start 는 그 경로를 물려받는다.
REM (cmd /k "..." 안에 경로를 또 넣으면 따옴표가 중첩돼 깨진다)
start "SafetyManager" cmd /k python\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --log-level info

set /a WAIT=0
:waitloop
timeout /t 2 /nobreak >nul
set /a WAIT+=2
netstat -aon | findstr :8000 | findstr LISTENING >nul 2>&1
if not errorlevel 1 goto :ready
if %WAIT% GEQ 30 (
    echo.
    echo   [오류] 서버가 켜지지 않았습니다.
    echo          방금 열린 검은 창의 메시지를 캡처해
    echo          AI혁신팀에 보내주세요.
    echo.
    pause
    exit /b 1
)
goto :waitloop

:ready
echo   [완료] 서버가 켜졌습니다.

REM -- 4) 브라우저 열기 ---------------------------------------
:browser
start http://localhost:8000

REM -- 접속 주소 안내 (이 PC의 내부 IP) ------------------------
set "MYIP="
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined MYIP set "MYIP=%%i"
)
if defined MYIP set "MYIP=%MYIP: =%"

echo.
echo  ============================================
echo    준비 완료
echo  ============================================
echo    이 PC        : http://localhost:8000
if defined MYIP echo    다른 PC      : http://%MYIP%:8000
echo.
echo    끄기         : STOP.bat
echo    문제 발생 시 : 이 창을 캡처해 AI혁신팀에 문의
echo  ============================================
echo.
timeout /t 10 /nobreak >nul
