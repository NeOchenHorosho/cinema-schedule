@echo off
chcp 65001 >nul
setlocal

REM Change to the script's own directory
pushd "%~dp0"

REM Activate a virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

python make_schedule.py %*

popd
endlocal
pause
