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
rem
rem Every message also goes to logs\launcher.log, and a failure pings Telegram. The
rem hidden autostart path has no console and nobody watching it, so without both of
rem those a stack that failed to come up at logon looked exactly like one that came
rem up fine: the next sign of trouble was a day of missing jobs.

setlocal enabledelayedexpansion
title Job Tracker

set "REPO=%~dp0..\.."
set "URL=http://localhost:8000"
set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "NO_BROWSER=0"
if /i "%~1"=="--no-browser" set "NO_BROWSER=1"

cd /d "%REPO%"
if errorlevel 1 goto fail_repo

if not exist "logs" mkdir "logs"
set "LOG=%CD%\logs\launcher.log"
rem Keep one previous generation rather than growing without bound.
for %%s in ("%LOG%") do if %%~zs GTR 1048576 move /y "%LOG%" "%LOG%.old" >nul
>>"%LOG%" echo.
call :say === start-tracker %* ===

call :say [1/4] Docker engine
docker info >nul 2>&1
if not errorlevel 1 goto compose
call :say       not responding; starting Docker Desktop (a cold start takes a minute or two)
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
call :say [2/4] Starting the containers
rem No --build: building is an install-time step, not a per-launch cost.
rem Output is teed to the log so "scroll up for the reason" still has a reason
rem hours later, and at all on the hidden path where there is nothing to scroll.
docker compose up -d >>"%LOG%" 2>&1
if errorlevel 1 goto fail_compose

call :say [3/4] Waiting for the API
set /a TRIES=0
:wait_api
curl -fsS -m 5 -o nul "%URL%/health" >nul 2>&1
if not errorlevel 1 goto serving
set /a TRIES+=1
if !TRIES! GEQ 40 goto fail_api
ping -n 4 127.0.0.1 >nul
goto wait_api

:serving
call :say [4/4] Ready at %URL%
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
rem Before the log path is known, so this one is console-only.
echo FAILED: could not enter the repo at "%REPO%".
goto held

:fail_docker_missing
call :fail "Docker Desktop was not found at %DOCKER_EXE%. Install it, or start the engine yourself and run this again."
goto held

:fail_engine
call :fail "the Docker engine did not respond within 3 minutes. Open Docker Desktop and check whether it is stuck starting."
goto held

:fail_compose
call :fail "docker compose up -d returned an error. See logs\launcher.log for its output."
goto held

:fail_api
call :fail "the API did not answer %URL%/health within 2 minutes. Check: docker compose logs --tail=50 api"
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
call :say Done.
endlocal
exit /b 0

rem ---------------------------------------------------------------------------

rem Echo to the console and append a timestamped copy to the log.
:say
echo %*
>>"%LOG%" echo [%DATE% %TIME%] %*
goto :eof

rem Report a failure everywhere it can be seen: console, log, and the phone.
:fail
call :say FAILED: %~1
call :notify "Job Tracker failed to start: %~1"
goto :eof

rem Telegram straight from cmd, reading the same .env the containers use. curl ships
rem with Windows 11. Best-effort by design: no bot, no network and no .env all mean
rem the log is the only record, which is still better than the nothing it replaced.
:notify
if not exist ".env" goto :eof
set "TG_TOKEN="
set "TG_CHAT="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if /i "%%a"=="TELEGRAM_BOT_TOKEN" set "TG_TOKEN=%%b"
  if /i "%%a"=="TELEGRAM_CHAT_ID" set "TG_CHAT=%%b"
)
if not defined TG_TOKEN goto :eof
if not defined TG_CHAT goto :eof
curl -fsS -m 10 -o nul "https://api.telegram.org/bot!TG_TOKEN!/sendMessage" --data-urlencode "chat_id=!TG_CHAT!" --data-urlencode "text=%~1" >nul 2>&1
if errorlevel 1 >>"%LOG%" echo [%DATE% %TIME%] (telegram ping failed)
goto :eof
