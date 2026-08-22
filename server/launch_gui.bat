@echo off
setlocal

set "ROOT=%~dp0"
set "HOST=127.0.0.1"
set "PORT=8080"

if not defined PYTHON (
    set "PYTHON=python"
)

pushd "%ROOT%"

start "Network Monitoring GUI" "%PYTHON%" gui_server.py
timeout /t 2 /nobreak >nul
start "" "http://%HOST%:%PORT%"

popd
endlocal
