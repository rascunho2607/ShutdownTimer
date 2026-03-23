#Requires -Version 5.1
<#
.SYNOPSIS
    Build temp_reader.exe and place it in the temperature_watch plugin folder.

.DESCRIPTION
    Compiles the C# project in temp_reader_src\ using the .NET SDK and
    publishes a self-contained single-file executable (win-x64) directly
    into the plugin root so the Python plugin can find it automatically.

.NOTES
    Requirements:
      - .NET SDK 8.0 (or 6.0 LTS) installed
        https://dotnet.microsoft.com/download

    Usage:
      cd "sample_plugins\temperature_watch"
      .\build_temp_reader.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir  = $PSScriptRoot
$SrcDir     = Join-Path $ScriptDir "temp_reader_src"
$OutputDir  = $ScriptDir   # exe lands in plugin root
$ExePath    = Join-Path $OutputDir "temp_reader.exe"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗"
Write-Host "║  Temperature Watch — build temp_reader.exe   ║"
Write-Host "╚══════════════════════════════════════════════╝"
Write-Host ""

# ── Verify dotnet is available ─────────────────────────────────────────────
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Error ("dotnet SDK not found.`n" +
                 "Download it from https://dotnet.microsoft.com/download")
}

$dotnetVersion = (dotnet --version 2>&1)
Write-Host "  .NET SDK : $dotnetVersion"
Write-Host "  Source   : $SrcDir"
Write-Host "  Output   : $OutputDir"
Write-Host ""

# ── Run publish ────────────────────────────────────────────────────────────
Write-Host "Building (this may take a moment on first run)…"
Write-Host ""

dotnet publish "$SrcDir\temp_reader.csproj" `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:PublishTrimmed=true `
    -p:EnableCompressionInSingleFile=true `
    --output "$OutputDir" `
    --nologo

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed (exit code $LASTEXITCODE)."
}

# ── Verify output ──────────────────────────────────────────────────────────
if (Test-Path $ExePath) {
    $size = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "  ✅  temp_reader.exe built successfully  ($size MB)" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Error "Build succeeded but temp_reader.exe was not found at: $ExePath"
}
