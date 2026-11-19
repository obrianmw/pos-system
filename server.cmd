@echo off
setlocal
REM POS System - server control (on/off). The control program is tools\control.py.
REM   server.cmd                                   opens the control window
REM   server.cmd start ^| stop ^| restart ^| status ^| phones-on ^| phones-off ^| change-password   does that one thing here
REM Start, Stop, Restart, Change password and closing the window need the server control password
REM (chosen the first time; stored as a hash in .run\control-password). Closing the window stops the servers.
REM API + admin: http://localhost:8100/admin/    POS + back office: http://localhost:5180/
cd /d "%~dp0"
set "NAME=POS System server control"
set "PY=backend\.venv\Scripts\python.exe"
if not exist "%PY%" (echo backend\.venv is missing. See README.md, "Quick start". & pause & exit /b 1)

if "%~1"=="" goto window
if /i "%~1"=="menu" goto window
"%PY%" tools\control.py %~1 "%NAME%"
pause
exit /b

:window
"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (echo This Python has no tkinter, so the window cannot open. Use: server.cmd start ^| stop ^| restart ^| status ^| change-password & pause & exit /b 1)
start "" "backend\.venv\Scripts\pythonw.exe" tools\control.py window "%NAME%"
exit /b
