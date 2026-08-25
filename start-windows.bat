@echo off
setlocal
cd /d "%~dp0"
set "PY=_support\.venv\Scripts\python.exe"

if not exist .env (
  echo [ERROR] Missing .env
  exit /b 1
)

if not exist "%PY%" (
  echo [ERROR] Missing runtime. Run install-windows.bat first.
  exit /b 1
)

"%PY%" -c "from dotenv import load_dotenv; import fastapi, uvicorn, discord; from discord.ext.native_voice import StreamClient, VoiceClient" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Runtime dependencies are incomplete
  exit /b 1
)

"%PY%" app.py
exit /b %ERRORLEVEL%
