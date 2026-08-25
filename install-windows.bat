@echo off
setlocal
cd /d "%~dp0"

set "SUPPORT=_support"
set "PY=%SUPPORT%\.venv\Scripts\python.exe"
set "SELF_URL=https://github.com/dolfies/discord.py-self/archive/refs/heads/master.zip"

if not exist "%SUPPORT%" mkdir "%SUPPORT%"

echo [1/8] Checking Python 3...
py -3 --version || goto :error

echo [2/8] Creating isolated runtime...
if not exist "%PY%" (
  py -3 -m venv "%SUPPORT%\.venv" || goto :error
)

echo [3/8] Updating pip...
"%PY%" -m pip install --upgrade pip setuptools wheel || goto :error

echo [4/8] Removing conflicting Discord packages...
"%PY%" -m pip uninstall -y discord discord.py discord.py-self discord-native-voice >nul 2>nul

echo [5/8] Installing runtime dependencies...
"%PY%" -m pip install -r "%SUPPORT%\requirements.txt" || goto :error

echo [6/8] Installing discord.py-self...
"%PY%" -m pip install --upgrade "%SELF_URL%" || goto :error

echo [7/8] Installing native voice wheel...
"%PY%" -m pip install --only-binary=:all: --no-deps "discord-native-voice==0.1.1" || goto :error

echo [8/8] Verifying runtime...
"%PY%" -c "from dotenv import load_dotenv; import fastapi, uvicorn, discord; from discord.ext.native_voice import StreamClient, VoiceClient; print('discord.py-self:', discord.__version__); print('runtime: OK')" || goto :error

if not exist .env (
  copy /y "%SUPPORT%\.env.example" .env >nul
)

echo.
echo [DONE] Installation complete.
pause
exit /b 0

:error
echo.
echo [ERROR] Installation failed.
pause
exit /b 1
