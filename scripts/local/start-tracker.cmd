@echo off
rem Start the whole local stack and open the UI as an app window. Idempotent:
rem running it twice costs nothing, because every step is a no-op when already done.
rem
rem Pass --no-browser to bring the stack up without opening the UI (the logon task
rem uses this: ingestion must not depend on anyone opening a window).
rem
rem A .cmd rather than a .ps1 on purpose: Windows Application Control on this
rem machine interferes with PowerShell and with the project venv's Python.
rem
rem `ping` is the sleep, not `timeout`: timeout.exe aborts when stdin is redirected,
rem which is exactly the case when this runs from a hidden scheduled task.

setlocal enabledelayedexpansion
title Job Tracker

set "REPO=%~dp0..\.."
set "URL=http://localhost:8000"
set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "NO_BROWSER=0"
if /i "%~1"=="--no-browser" set "NO_BROWSER=1"

cd /d "%REPO%"
if errorlevel 1 goto fail_repo

echo [1/4] Docker engine
docker info >nul 2>&1
if not errorlevel 1 goto compose
echo       not responding; starting Docker Desktop (a cold start takes a minute or two)
if not exist "%DOCKER_EXE%" goto fail_docker_missing
start "" "%DOCKER_EXE%"
set /a TRIES=0
:wait_engine
ping -n 6 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 goto compose
set /a TRIES+=1
if !TRIES! LSS 36 goto wait_engine
goto fail_engine

:compose
echo [2/4] Starting the containers
rem No --build: building is an install-time step, not a per-launch cost.
docker compose up -d
if errorlevel 1 goto fail_compose

echo [3/4] Waiting for the API
set /a TRIES=0
:wait_api
curl -fsS -m 5 -o nul "%URL%/health" >nul 2>&1
if not errorlevel 1 goto serving
set /a TRIES+=1
if !TRIES! GEQ 40 goto fail_api
ping -n 4 127.0.0.1 >nul
goto wait_api

:serving
echo [4/4] Ready at %URL%
if "%NO_BROWSER%"=="1" goto done
rem App mode is what makes this read as an application rather than a browser tab.
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" goto open_chrome
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" goto open_chrome86
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" goto open_edge
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" goto open_edge64
start "" "%URL%"
goto done

:open_chrome
start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --app=%URL%
goto done

:open_chrome86
start "" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" --app=%URL%
goto done

:open_edge
start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=%URL%
goto done

:open_edge64
start "" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" --app=%URL%
goto done

:fail_repo
echo FAILED: could not enter the repo at "%REPO%".
goto held

:fail_docker_missing
echo FAILED: Docker Desktop was not found at "%DOCKER_EXE%".
echo         Install it, or start the engine yourself and run this again.
goto held

:fail_engine
echo FAILED: the Docker engine did not respond within 3 minutes.
echo         Open Docker Desktop and check whether it is stuck starting.
goto held

:fail_compose
echo FAILED: `docker compose up -d` returned an error (scroll up for the reason).
goto held

:fail_api
echo FAILED: the API did not answer %URL%/health within 2 minutes.
echo         Check the logs: docker compose logs --tail=50 api
goto held

:held
rem Keep the window so the message above is readable. Skipped for the hidden
rem autostart run, where nobody is looking and the task would never exit.
if "%NO_BROWSER%"=="1" goto bail
echo.
pause
:bail
endlocal
exit /b 1

:done
endlocal
exit /b 0
