$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$version = (node -p "require('./package.json').version").Trim()
if (-not $version) {
  throw "Could not read package.json version."
}

Write-Host "Building Local Meeting Notes $version"

npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }
& $python -m pip install -r backend\installer-requirements.txt -r backend\build-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }

$ffmpegArguments = @("scripts/prepare_windows_ffmpeg.py", "--output", "vendor/ffmpeg.exe")
if (-not $env:CI) { $ffmpegArguments += "--allow-local-cache" }
& $python @ffmpegArguments
if ($LASTEXITCODE -ne 0) { throw "Verified standalone ffmpeg preparation failed." }

$workPath = Join-Path "build" ("pyinstaller-" + (Get-Date -Format "yyyyMMddHHmmss"))
if (Test-Path -LiteralPath "dist-app") {
  $distPath = (Resolve-Path -LiteralPath "dist-app").Path
  if ($distPath -ne (Join-Path $root "dist-app")) { throw "Unexpected dist-app target: $distPath" }
  if ((Get-Item -LiteralPath $distPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing to remove a linked dist-app directory." }
  Remove-Item -LiteralPath $distPath -Recurse -Force
}
New-Item -ItemType Directory -Force -Path release | Out-Null

& $python -m PyInstaller --noconfirm --clean --distpath dist-app --workpath $workPath LocalMeetingNotes.spec
if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }

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
if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }

$installer = Join-Path $root "release\LocalMeetingNotesSetup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
  throw "NSIS did not create $installer"
}

Get-Item -LiteralPath $installer | Select-Object FullName, Length, LastWriteTime
