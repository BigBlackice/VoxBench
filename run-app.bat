@echo off
setlocal
cd /d "%~dp0"
set "VENV_PYTHON=%~dp0.venv-app\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating application-only Python 3.11 environment...
    py -3.11 -m venv .venv-app
    if errorlevel 1 goto :python_error
)

echo Installing application-only dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements-app.txt
if errorlevel 1 goto :dependency_error

"%VENV_PYTHON%" app.py
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

:python_error
echo ERROR: Python 3.11 is required.
pause
exit /b 1

:dependency_error
echo ERROR: Dependency installation failed.
pause
exit /b 1
