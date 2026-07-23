@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM ============================================================
REM  내부용 - START.bat 이 관리자 권한으로 호출한다.
REM  운영자가 직접 실행할 필요 없음.
REM
REM  작업스케줄러에 SYSTEM 계정으로 감시기를 등록:
REM    - 3분마다 서버 상태 점검 -> 죽어있으면 자동 재시작
REM    - 재부팅/로그오프 후에도 동작 (로그인 불필요)
REM ============================================================

set "TASK=KEPCO_SafetyManager_AlwaysOn"

schtasks /Create /TN "%TASK%" /TR "\"%~dp0WATCHDOG.bat\"" /SC MINUTE /MO 3 /RU SYSTEM /RL HIGHEST /F >nul 2>&1
if errorlevel 1 exit /b 1

REM 즉시 1회 실행하여 서버 기동
schtasks /Run /TN "%TASK%" >nul 2>&1
exit /b 0
