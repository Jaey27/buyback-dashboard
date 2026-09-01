@echo off
rem Manual-update alias. All logic lives in run_daily.bat (single source of truth).
call "%~dp0run_daily.bat" %*
exit /b %errorlevel%
