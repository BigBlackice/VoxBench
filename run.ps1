$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Creating Python 3.11 virtual environment..."
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 is required. Install it and ensure the py launcher can find it."
    }
}

Write-Host "Checking project dependencies..."
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

& $venvPython app.py
exit $LASTEXITCODE
