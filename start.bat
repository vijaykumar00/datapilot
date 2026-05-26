@echo off
setlocal enabledelayedexpansion
title DataPilot Startup

echo.
echo  ====================================================
echo   ^🧭  DataPilot — Local AI Data Assistant
echo  ====================================================
echo.

:: ── Find Python ──────────────────────────────────────────────────────────
set PYTHON_CMD=
for %%P in (python3.11 python3 python) do (
  if "!PYTHON_CMD!"=="" (
    where %%P >nul 2>&1
    if !errorlevel! == 0 (
      set PYTHON_CMD=%%P
    )
  )
)

:: Also try common install paths
if "!PYTHON_CMD!"=="" (
  for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python311\python.exe"
    "C:\Python312\python.exe"
  ) do (
    if "!PYTHON_CMD!"=="" (
      if exist %%P set PYTHON_CMD=%%~P
    )
  )
)

if "!PYTHON_CMD!"=="" (
  echo [ERROR] Python not found. Install from https://www.python.org
  echo         Or run: winget install Python.Python.3.11
  pause
  exit /b 1
)

echo [OK] Python found: !PYTHON_CMD!
!PYTHON_CMD! --version

:: ── Check Ollama ─────────────────────────────────────────────────────────
echo.
echo [INFO] Checking Ollama...
curl -s http://localhost:11434 >nul 2>&1
if !errorlevel! == 0 (
  echo [OK] Ollama is running
) else (
  echo [WARN] Ollama is not running.
  echo        Start it in a separate terminal: ollama serve
  echo        Or install from: https://ollama.ai
  echo        DataPilot will still work — LLM features will be limited.
)

:: ── Backend virtual environment ───────────────────────────────────────────
echo.
echo [INFO] Setting up Python virtual environment...
set BACKEND_DIR=%~dp0backend
set VENV_DIR=%BACKEND_DIR%\venv

if not exist "!VENV_DIR!" (
  echo [INFO] Creating virtual environment...
  !PYTHON_CMD! -m venv "!VENV_DIR!"
  if !errorlevel! neq 0 (
    echo [ERROR] Failed to create virtual environment
    pause & exit /b 1
  )
  echo [OK] Virtual environment created
) else (
  echo [OK] Virtual environment exists
)

:: Activate venv
set VENV_PYTHON=!VENV_DIR!\Scripts\python.exe
set VENV_PIP=!VENV_DIR!\Scripts\pip.exe

:: Install requirements
echo.
echo [INFO] Installing Python dependencies (first run may take a few minutes)...
!VENV_PIP! install -r "!BACKEND_DIR!\requirements.txt" --quiet --no-warn-script-location
if !errorlevel! neq 0 (
  echo [ERROR] pip install failed. Check requirements.txt and your internet connection.
  pause & exit /b 1
)
echo [OK] Python dependencies installed

:: ── Frontend dependencies ─────────────────────────────────────────────────
echo.
echo [INFO] Installing frontend dependencies...
set FRONTEND_DIR=%~dp0frontend

if not exist "!FRONTEND_DIR!\node_modules" (
  pushd "!FRONTEND_DIR!"
  call npm install --silent
  if !errorlevel! neq 0 (
    echo [ERROR] npm install failed
    popd & pause & exit /b 1
  )
  popd
  echo [OK] npm packages installed
) else (
  echo [OK] node_modules exists
)

:: ── Start backend ─────────────────────────────────────────────────────────
echo.
echo [INFO] Starting FastAPI backend on http://localhost:8000 ...
start "DataPilot Backend" cmd /k "cd /d !BACKEND_DIR! && !VENV_PYTHON! -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend to start
echo [INFO] Waiting for backend to start...
timeout /t 4 /nobreak >nul

:: ── Start frontend ────────────────────────────────────────────────────────
echo [INFO] Starting Vite dev server on http://localhost:5173 ...
start "DataPilot Frontend" cmd /k "cd /d !FRONTEND_DIR! && npm run dev"

:: Wait and open browser
timeout /t 3 /nobreak >nul
echo.
echo [INFO] Opening browser...
start "" "http://localhost:5173"

echo.
echo  ====================================================
echo   DataPilot is running!
echo.
echo   Frontend : http://localhost:5173
echo   Backend  : http://localhost:8000
echo   API docs : http://localhost:8000/docs
echo  ====================================================
echo.
echo  Close the Backend and Frontend windows to stop.
echo.
pause
