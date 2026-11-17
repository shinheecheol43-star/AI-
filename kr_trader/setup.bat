@echo off
chcp 65001 > nul
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if not exist config.env copy config.example.env config.env
echo.
echo 설치 끝. config.env 를 메모장으로 열어 채우세요.
pause
