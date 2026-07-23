@echo off
REM ============================================================
REM  KEPCO Safety Manager - 상시구동 설치 (관리자 권한 필요)
REM  Windows 작업스케줄러에 SYSTEM 계정으로 감시기를 등록.
REM  - 3분마다 서버 상태 점검 -> 죽어있으면 자동 재시작
REM  - 재부팅/로그오프 후에도 자동 (로그인 불필요)
REM  - 보안SW가 .html/프로세스를 지워도 자동 복구
REM ============================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM -- 관리자 권한 확인 --
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
echo  ========================================
echo   상시구동 설치 중...
echo  ========================================
echo.

REM -- 3분마다 실행 + SYSTEM 계정 + 최고 권한 --
schtasks /Create /TN "%TASK%" /TR "\"%~dp0WATCHDOG.bat\"" /SC MINUTE /MO 3 /RU SYSTEM /RL HIGHEST /F
if errorlevel 1 (
    echo.
    echo  [실패] 작업 등록에 실패했습니다. 관리자 권한 / 보안정책을 확인하세요.
    pause
    exit /b 1
)

REM -- 지금 즉시 1회 실행하여 서버 기동 --
schtasks /Run /TN "%TASK%" >nul 2>&1

echo.
echo  ========================================
echo   [완료] 상시구동이 설치되었습니다.
echo  ========================================
echo   - 서버가 3분마다 자동 점검/재시작됩니다.
echo   - PC 재부팅 후에도 자동으로 켜집니다. (로그인 불필요)
echo   - 접속: http://10.193.5.171:8000  (또는 http://localhost:8000)
echo.
echo   * 상시구동을 끄려면 "해제_상시구동.bat" 을 관리자 권한으로 실행하세요.
echo.
pause
