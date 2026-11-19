param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements-studio.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$runtimeDir = Join-Path $PSScriptRoot 'runtime'
$downloadsDir = Join-Path $PSScriptRoot 'user-data'
if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir 'vlc-3.0.21\libvlc.dll'))) {
    New-Item -ItemType Directory -Path $runtimeDir,$downloadsDir -Force | Out-Null
    $archive = Join-Path $downloadsDir 'vlc-3.0.21-win64.7z'
    $checksum = Join-Path $downloadsDir 'vlc.sha256'
    $source = 'https://download.videolan.org/pub/videolan/vlc/3.0.21/win64'
    Invoke-WebRequest -Uri "$source/vlc-3.0.21-win64.7z" -OutFile $archive
    Invoke-WebRequest -Uri "$source/vlc-3.0.21-win64.7z.sha256" -OutFile $checksum
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    $expected = ((Get-Content -LiteralPath $checksum -Raw).Trim() -split '\s+')[0]
    if ($actual -ine $expected) { throw 'VLC download checksum mismatch.' }
    & tar -xf $archive -C $runtimeDir
    if ($LASTEXITCODE -ne 0) { throw 'VLC extraction failed.' }
}
& .\.venv\Scripts\python.exe scripts/build_launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Native launcher compilation failed.' }
Write-Output 'Ready. Double-click DD Monitor Studio.exe to launch.'
