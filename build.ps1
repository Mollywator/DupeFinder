# Builds dist\DupeFinder.exe — a single file that runs without Python.
# Usage: pwsh ./build.ps1   (CI runs the same script for releases)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name DupeFinder `
    --icon src/dupefinder/icon.ico `
    --paths src `
    --add-data "src/dupefinder/icon.ico;dupefinder" `
    --collect-data customtkinter `
    --collect-all pillow_heif `
    --exclude-module pytest `
    DupeFinder.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Get-Item dist/DupeFinder.exe
"Built {0} ({1:N1} MB)" -f $exe.FullName, ($exe.Length / 1MB)
