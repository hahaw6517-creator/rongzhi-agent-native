param(
    [int]$Port = 8787,
    [string]$ListenAddress = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Python environment missing. Run python -m venv .venv, then install requirements-web.txt.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $projectPython -m uvicorn web_app:app --host $ListenAddress --port $Port --no-server-header
} finally {
    Pop-Location
}
