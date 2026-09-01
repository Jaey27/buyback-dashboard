@echo off
rem ---------------------------------------------------------------------------
rem  buyback-dashboard : daily update entry point
rem
rem  NOTE: keep this file ASCII-only. cmd.exe re-reads batch files by BYTE OFFSET,
rem  so multi-byte (Korean) text after "chcp 65001" corrupts block parsing.
rem  Korean messages come from the Python scripts, which print UTF-8.
rem
rem  Step 1  build_data.py : KIND + DART + Naver  -> data\buyback.json
rem                          invariant gate fails -> exit 2 -> STOP (no render)
rem  Step 2  render.py     : buyback.json         -> dashboard.html
rem
rem  The errorlevel guard between the two steps is REQUIRED. Without it, a failed
rem  build would still be followed by a render of the STALE buyback.json, which
rem  produces a normal-looking page showing numbers that are no longer current.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
title Buyback Dashboard - Daily Update
cd /d "%~dp0"

echo ============================================
echo [%DATE% %TIME%] buyback-dashboard update
echo ============================================

python scripts\build_data.py
if errorlevel 1 goto build_failed

python scripts\render.py --max-age-days 4
if errorlevel 1 goto render_failed

echo.
echo [OK] done - "%~dp0dashboard.html"
exit /b 0

:build_failed
echo.
echo [ERROR] build_data.py failed - dashboard.html was NOT regenerated.
echo         data\buyback.json is unchanged (previous run's values).
exit /b 1

:render_failed
echo.
echo [ERROR] render.py failed.
exit /b 1
