$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw '请先在项目根目录创建 .venv 并安装 requirements.txt。'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $projectPython -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
} finally {
    Pop-Location
}
