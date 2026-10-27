@echo off
rem Swing signal bot for Windows. Double-click to run. Restarts automatically if it stops.
rem Put your Telegram token etc. in bot.env (same folder as this repo root, copied from deploy\bot.env.example).
chcp 65001 > nul
set PYTHONUTF8=1
cd /d "%~dp0.."
if not exist bot.env (
  copy deploy\bot.env.example bot.env > nul
  echo bot.env was created. Open it with Notepad, fill in the values, then run this file again.
  pause
  exit /b
)
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("bot.env") do set "%%a=%%b"
if not exist .venv\Scripts\python.exe (
  echo Installing packages for the first time...
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
:loop
.venv\Scripts\python -m smc.signal_bot %*
if "%~1"=="--once" (
  pause
  exit /b
)
echo Bot stopped. Restarting in 60 seconds... (close this window to quit)
timeout /t 60 > nul
goto loop
