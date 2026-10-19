$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Run-Python {
    & .\.venv\Scripts\python.exe @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $args" }
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 venv creation failed' }
}
Run-Python -m pip install 'pip==24.3.1' 'setuptools==75.6.0' 'wheel==0.45.1'
Run-Python -m pip install 'torch==2.4.1' 'torchaudio==2.4.1' --index-url https://download.pytorch.org/whl/cu121
Run-Python -m pip install --no-build-isolation -r requirements.txt
Run-Python -m playwright install chromium
Run-Python -m unittest discover -s tests -v
Get-Command ffmpeg,ffprobe -ErrorAction Stop | Out-Null
Write-Host 'Setup complete. Run .\audio.ps1 --help, then .\audio.ps1 add "path\recording.mp3"'
