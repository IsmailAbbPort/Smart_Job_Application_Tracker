@echo off
rem Dump the database to backups\ and keep the newest 7.
rem
rem `pgdata` is a named volume inside Docker Desktop's WSL2 disk image, so it is not
rem covered by any file backup of this folder and it does not survive
rem `docker compose down -v` or a Docker Desktop factory reset. A logical dump is
rem the only copy that lives on the real filesystem.
rem
rem Restore (destructive, overwrites the current corpus):
rem   docker compose up -d db
rem   docker compose exec -T db sh -c "gunzip -c > /tmp/d.sql" < backups\<file>.sql.gz
rem   docker compose exec -T db psql -U postgres -d jobtracker -f /tmp/d.sql

setlocal
title Job Tracker backup

set "REPO=%~dp0..\.."
set "KEEP=7"

cd /d "%REPO%"
if errorlevel 1 goto fail_repo

docker compose exec -T db pg_isready -U postgres -d jobtracker >nul 2>&1
if errorlevel 1 goto fail_db

rem The timestamp comes from the container, so this does not depend on the host's
rem date format (which is locale-specific) or on wmic (removed in recent Windows).
for /f "delims=" %%d in ('docker compose exec -T db date -u +%%Y%%m%%d-%%H%%M%%S') do set "STAMP=%%d"
if not defined STAMP goto fail_stamp

if not exist "backups" mkdir "backups"
set "OUT=backups\jobtracker-%STAMP%.sql.gz"

echo Dumping to %OUT% ...
rem gzip inside the container: the embeddings make a plain dump several times larger,
rem and Windows ships no gzip.
docker compose exec -T db sh -c "pg_dump -U postgres jobtracker | gzip -c" > "%OUT%"
if errorlevel 1 goto fail_dump
for %%s in ("%OUT%") do if %%~zs LSS 1024 goto fail_empty

rem Rotation. Oldest first out, by name (the stamp sorts chronologically).
for /f "skip=%KEEP% delims=" %%f in ('dir /b /o-n "backups\jobtracker-*.sql.gz" 2^>nul') do del "backups\%%f"

for %%s in ("%OUT%") do echo Done: %%~nxs (%%~zs bytes). Keeping the newest %KEEP%.
endlocal
exit /b 0

:fail_repo
echo FAILED: could not enter the repo at "%REPO%".
goto held

:fail_db
echo FAILED: the db container is not accepting connections.
echo         Start the stack first: scripts\local\start-tracker.cmd --no-browser
goto held

:fail_stamp
echo FAILED: could not read the time from the db container.
goto held

:fail_dump
echo FAILED: pg_dump returned an error (scroll up for the reason).
del "%OUT%" 2>nul
goto held

:fail_empty
echo FAILED: the dump is suspiciously small; treating it as a failure.
del "%OUT%" 2>nul
goto held

:held
echo.
pause
endlocal
exit /b 1
