# Builds dist\PASTA-Setup-<version>.exe from a clean environment.
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Requirements: Python 3.11+ on PATH (or C:\Python313), Inno Setup 6 (winget install JRSoftware.InnoSetup).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = if (Test-Path "C:\Python313\python.exe") { "C:\Python313\python.exe" } else { "python" }
$venv = "$root\build\venv"
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Write-Host "Creating clean build environment ..."
    & $py -m venv $venv
}
$vpy = "$venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -e ".[pasta]" pyinstaller
# faster-whisper depends on the CPU "onnxruntime", which overwrites onnxruntime-gpu's files.
& $vpy -m pip uninstall -y onnxruntime onnxruntime-gpu
& $vpy -m pip install "onnxruntime-gpu>=1.20,<1.24"

Write-Host "Freezing the application ..."
if (Test-Path "$root\dist\PASTA") { Remove-Item -Recurse -Force "$root\dist\PASTA" }
& "$venv\Scripts\pyinstaller.exe" packaging\pasta.spec --noconfirm --distpath dist --workpath build\pyi

Write-Host "Self-test of the frozen build ..."
$report = "$root\build\selftest.json"
$env:PESTO_HOME = $root   # use the developer model cache; no download during the build
& "$root\dist\PASTA\PASTA.exe" --selftest $report | Out-Null
Remove-Item Env:\PESTO_HOME
Get-Content $report
$r = Get-Content $report | ConvertFrom-Json
if (-not $r.whisper.ok) { throw "Self-test failed: Whisper did not load in the frozen build" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup not found: winget install JRSoftware.InnoSetup" }
Write-Host "Building the installer ..."
& $iscc packaging\installer.iss
Get-ChildItem "$root\dist\*.exe" | Format-Table Name, @{n="MB"; e={[math]::Round($_.Length / 1MB)}}
