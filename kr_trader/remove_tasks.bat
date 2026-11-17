@echo off
chcp 65001 > nul
schtasks /Delete /F /TN "균형형_장중손절감시"
schtasks /Delete /F /TN "균형형_종가매매"
pause
