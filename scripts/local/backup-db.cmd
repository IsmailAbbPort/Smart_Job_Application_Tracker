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
rem
rem `bash -o pipefail`, not `sh -c`: a shell pipeline reports only the LAST command's
rem status, so a failing pg_dump piped into a succeeding gzip exited 0 and this script
rem kept a tiny valid-gzip file as if it were a backup. `sh` is dash in this image and
rem has no pipefail, so it has to be bash.
docker compose exec -T db bash -o pipefail -c "pg_dump -U postgres jobtracker | gzip -c" > "%OUT%"
if errorlevel 1 goto fail_dump
for %%s in ("%OUT%") do if %%~zs LSS 1024 goto fail_empty

rem Size is not integrity: a dump cut off by a full disk or a container stopped
rem mid-write is megabytes long and still useless. pg_dump ends every complete dump
rem with this trailer, so reading the file back and finding it proves the gzip stream
rem is whole and the dump reached its end. `grep` without -q on purpose: -q can exit
rem before `tail` finishes writing, and that SIGPIPE would fail pipefail spuriously.
echo Verifying %OUT% ...
docker compose exec -T db bash -o pipefail -c "gunzip -c | tail -n 5 | grep \"PostgreSQL database dump complete\" > /dev/null" < "%OUT%"
if errorlevel 1 goto fail_corrupt

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

:fail_corrupt
echo FAILED: the dump did not read back as a complete pg_dump (truncated or corrupt).
del "%OUT%" 2>nul
goto held

:held
echo.
pause
endlocal
exit /b 1
