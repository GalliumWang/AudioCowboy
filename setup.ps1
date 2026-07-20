<#
.SYNOPSIS
    OPTIONAL: download NirSoft svcl.exe (SoundVolumeCommandLine) into .\bin.

.DESCRIPTION
    AudioCowboy switches devices with the bundled pure-Python pycaw backend and needs
    no external executable — this script is not required for normal use. It adds an
    svcl.exe which, when present, is used in preference to pycaw; the only thing that
    buys you is reading the *communications* default, which pycaw cannot report.
    svcl.exe is never shipped in the release zip.

.NOTES
    NirSoft executables are closed-source freeware and may trigger antivirus false
    positives. The download URL below is the official NirSoft site.
#>
[CmdletBinding()]
param(
    [string]$Url = "https://www.nirsoft.net/utils/svcl-x64.zip"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin  = Join-Path $root "bin"
$dest = Join-Path $bin "svcl.exe"

if (Test-Path $dest) {
    Write-Host "svcl.exe already present at $dest" -ForegroundColor Green
    return
}

New-Item -ItemType Directory -Force -Path $bin | Out-Null
$zip = Join-Path $env:TEMP ("svcl-" + [guid]::NewGuid().ToString("N") + ".zip")

Write-Host "Downloading $Url ..."
Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing

Write-Host "Extracting svcl.exe ..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $entry = $archive.Entries | Where-Object { $_.Name -ieq "svcl.exe" } | Select-Object -First 1
    if (-not $entry) { throw "svcl.exe not found inside the downloaded archive." }
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
}
finally {
    $archive.Dispose()
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

# Clear the Mark-of-the-Web so Windows doesn't block the freshly downloaded exe.
try { Unblock-File -Path $dest } catch {}

if (Test-Path $dest) {
    Write-Host "Done. svcl.exe installed at $dest" -ForegroundColor Green
    Write-Host "Restart Flow Launcher (or reload plugins). AudioCowboy will now prefer svcl.exe over the built-in pycaw backend."
} else {
    throw "Failed to install svcl.exe."
}
