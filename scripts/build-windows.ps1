$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$version = (node -p "require('./package.json').version").Trim()
if (-not $version) {
  throw "Could not read package.json version."
}

Write-Host "Building Local Meeting Notes $version"

npm.cmd run build

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

& $python -m pip install --upgrade pip
& $python -m pip install -r backend\installer-requirements.txt -r backend\build-requirements.txt

New-Item -ItemType Directory -Force -Path vendor | Out-Null
$ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if ($ffmpeg) {
  Copy-Item -LiteralPath $ffmpeg.Source -Destination "vendor\ffmpeg.exe" -Force
} else {
  Write-Warning "ffmpeg.exe was not found in PATH; the installer will rely on the user's PATH."
}

$workPath = Join-Path "build" ("pyinstaller-" + (Get-Date -Format "yyyyMMddHHmmss"))
if (Test-Path -LiteralPath "dist-app") {
  Remove-Item -LiteralPath "dist-app" -Recurse -Force
}
New-Item -ItemType Directory -Force -Path release | Out-Null

& $python -m PyInstaller --noconfirm --clean --distpath dist-app --workpath $workPath LocalMeetingNotes.spec

$exePath = Join-Path $root "dist-app\LocalMeetingNotes.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
  throw "PyInstaller did not create $exePath"
}

$makensis = Get-Command makensis.exe -ErrorAction SilentlyContinue
$makensisPath = if ($makensis) { $makensis.Source } else { $null }
if (-not $makensis) {
  $candidateMakensis = @(
    "${env:ProgramFiles(x86)}\NSIS\makensis.exe",
    "$env:ProgramFiles\NSIS\makensis.exe",
    "$env:LOCALAPPDATA\Programs\NSIS\makensis.exe"
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
  if ($candidateMakensis) {
    $makensisPath = $candidateMakensis
  } else {
    throw "makensis.exe was not found. Install NSIS and retry."
  }
}

& $makensisPath "/DAPP_VERSION=$version" "installer\LocalMeetingNotes.nsi"

$installer = Join-Path $root "release\LocalMeetingNotesSetup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
  throw "NSIS did not create $installer"
}

Get-Item -LiteralPath $installer | Select-Object FullName, Length, LastWriteTime
