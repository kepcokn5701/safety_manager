@echo off
REM ============================================================
REM  KEPCO Safety Manager - 상시구동 해제 (관리자 권한 필요)
REM  작업스케줄러에 등록된 감시기를 제거.
REM  (이미 실행 중인 서버는 STOP.bat 으로 별도 종료)
REM ============================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [오류] 관리자 권한이 필요합니다.
    echo         이 파일을 마우스 우클릭 - "관리자 권한으로 실행" 하세요.
    echo.
    pause
    exit /b 1
)

set "TASK=KEPCO_SafetyManager_AlwaysOn"

echo.
echo  상시구동 해제 중...
schtasks /Delete /TN "%TASK%" /F
if errorlevel 1 (
    echo  [안내] 등록된 상시구동 작업이 없거나 이미 삭제되었습니다.
) else (
    echo  [완료] 상시구동이 해제되었습니다.
)
echo.
echo  * 현재 실행 중인 서버를 완전히 끄려면 STOP.bat 을 실행하세요.
echo    (해제하지 않고 STOP.bat만 실행하면 3분 내 자동 재시작됩니다)
echo.
pause
