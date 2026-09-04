@echo off

setlocal
cd /d "%~dp0"

:loop
C:\Users\HOME\AppData\Local\Programs\Python\Python311\python.exe main.py
set EXITCODE=%ERRORLEVEL%

if %EXITCODE%==0 (
    goto :eof
)

timeout /t 1 /nobreak >nul
goto loop
