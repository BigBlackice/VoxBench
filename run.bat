@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating Python 3.11 virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python 3.11 is required. Install it and ensure the py launcher can find it.
        pause
        exit /b 1
    )
)

echo Checking project dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

"%VENV_PYTHON%" app.py
set "APP_EXIT=%ERRORLEVEL%"

if not "%APP_EXIT%"=="0" (
    echo.
    echo ERROR: The application exited with code %APP_EXIT%.
    pause
)

exit /b %APP_EXIT%
