@echo off
setlocal
title DataPilot - Public test link

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

:: -- Start DataPilot if it is not already running -------------------------
curl -s -o nul http://localhost:5173
if errorlevel 1 (
  echo [INFO] Starting DataPilot...
  rem Public-link safety: no dev-mode phone OTP codes in API responses.
  set PHONE_OTP_ENABLED=false
  set PHONE_OTP_DEV_MODE=false
  start "DataPilot" cmd /c "%~dp0start.bat"
  echo [INFO] Waiting for DataPilot to come up...
  for /l %%i in (1,1,60) do (
    curl -s -o nul http://localhost:5173 && goto :ready
    timeout /t 2 /nobreak >nul
  )
  echo [ERROR] DataPilot did not start. Check the DataPilot windows for errors.
  pause
  exit /b 1
) else (
  echo [OK] DataPilot is already running.
)

:ready
echo.
echo  ----------------------------------------------------
echo   Your public link appears below in a box, like:
echo     https://something-random.trycloudflare.com
echo   Send that link to your testers.
echo  ----------------------------------------------------
echo.
%CLOUDFLARED% tunnel --no-autoupdate --url http://localhost:5173
