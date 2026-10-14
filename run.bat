@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem py-лаунчер надёжнее: "python" может перехватываться заглушкой Microsoft Store
where py >nul 2>nul
if %errorlevel%==0 (
    py transcribe.py %*
) else (
    python transcribe.py %*
)
pause
