@echo off
setlocal
cd /d "%~dp0"
set "VENV_PYTHON=%~dp0.venv-model\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating model-only Python 3.11 environment...
    py -3.11 -m venv .venv-model
    if errorlevel 1 goto :python_error
)

echo Installing model-service dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r requirements-model.txt
if errorlevel 1 goto :dependency_error

"%VENV_PYTHON%" model_server.py
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
