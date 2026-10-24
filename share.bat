@echo off
setlocal
title DataPilot - Public test link
cd /d "%~dp0"

echo.
echo  ====================================================
echo    DataPilot - share a public test link
echo  ====================================================
echo.
echo  Keep this window open while people are testing.
echo  Closing it (or your PC sleeping) takes the link offline.
echo.

:: -- Find cloudflared (install it once with winget if missing) ------------
set CLOUDFLARED=
where cloudflared >nul 2>&1 && set CLOUDFLARED=cloudflared
if not defined CLOUDFLARED if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set CLOUDFLARED="%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
if not defined CLOUDFLARED if exist "%ProgramFiles%\cloudflared\cloudflared.exe" set CLOUDFLARED="%ProgramFiles%\cloudflared\cloudflared.exe"
if not defined CLOUDFLARED (
  echo [INFO] Installing Cloudflare Tunnel - one time only...
  winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
  if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set CLOUDFLARED="%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
  if exist "%ProgramFiles%\cloudflared\cloudflared.exe" set CLOUDFLARED="%ProgramFiles%\cloudflared\cloudflared.exe"
)
if not defined CLOUDFLARED (
  echo [ERROR] Could not install cloudflared. Close this window, run share.bat again,
  echo         or install it from https://github.com/cloudflare/cloudflared/releases
  pause
  exit /b 1
)

:: -- Start the backend (start.bat also installs dependencies) -------------
curl -s -o nul http://127.0.0.1:8001/live
if errorlevel 1 (
  echo [INFO] Starting DataPilot backend - first run can take several minutes...
  rem Public-link safety: no dev-mode phone OTP codes in API responses.
  set PHONE_OTP_ENABLED=false
  set PHONE_OTP_DEV_MODE=false
  start "DataPilot setup" cmd /c "%~dp0start.bat"
  for /l %%i in (1,1,300) do (
    curl -s -o nul http://127.0.0.1:8001/live && goto :backend_ready
    timeout /t 2 /nobreak >nul
  )
  echo [ERROR] The backend did not start. Check the "Tallis Backend" window for errors.
  pause
  exit /b 1
)
:backend_ready
echo [OK] Backend is running.

:: -- Build the frontend and serve the optimized build ----------------------
:: A production build loads a handful of files per page instead of hundreds,
:: which keeps testers well under the free tunnel's request limit.
echo [INFO] Building the web app...
pushd frontend
set VITE_API_URL=/api
call npm run build
if errorlevel 1 (
  popd
  echo [ERROR] Frontend build failed - see the messages above.
  pause
  exit /b 1
)
popd
start "DataPilot web (keep open)" cmd /k "cd /d %~dp0frontend && npx vite preview --port 4173 --strictPort"
for /l %%i in (1,1,30) do (
  curl -s -o nul http://localhost:4173 && goto :web_ready
  timeout /t 1 /nobreak >nul
)
echo [ERROR] The web app did not start. Check the "DataPilot web" window.
pause
exit /b 1
:web_ready
echo [OK] Web app is running.

echo.
echo  ----------------------------------------------------
echo   Your public link appears below in a box, like:
echo     https://something-random.trycloudflare.com
echo   Send that link to your testers.
echo  ----------------------------------------------------
echo.
%CLOUDFLARED% tunnel --no-autoupdate --url http://localhost:4173
