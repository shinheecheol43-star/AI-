@echo off
chcp 65001 > nul
cd /d "%~dp0"
schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN "균형형_장중손절감시" /TR "\"%~dp0watch_stops.bat\"" /ST 08:55
schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN "균형형_종가매매" /TR "\"%~dp0run_daily.bat\"" /ST 15:41
echo.
echo 작업 스케줄러에 두 작업을 등록했습니다 (평일 08:55 감시 · 15:41 종가 매매).
echo 지우려면 remove_tasks.bat
pause
