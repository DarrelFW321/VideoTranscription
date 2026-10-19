$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error 'Run .\setup.ps1 first to create the Python environment.'
    exit 1
}
& $python (Join-Path $PSScriptRoot 'audio.py') @args
exit $LASTEXITCODE
