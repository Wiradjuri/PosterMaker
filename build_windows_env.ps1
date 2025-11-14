# build_windows_env.ps1
# Safe, production-ready Nuitka builder for Windows + Pipenv
# Prevents empty args, fixes icon handling, ensures correct paths

$ErrorActionPreference = "Stop"

# Move to project root
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

# Source entry script
$src = "app/gui.py"

# Dist directory
$distDir = Join-Path $projectRoot "dist"
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

Write-Host "==================================================================="
Write-Host " Building PosterMaker with Nuitka (Pipenv)..."
Write-Host "==================================================================="

# Build arguments list safely (PowerShell array = NO empty args ever)
$argsList = @(
    "--onefile",                       # Single exe
    "--standalone",                    # Include all dependencies
    "--enable-plugin=pyside6",         # Include Qt plugins
    "--windows-disable-console",       # Hide console window
    "--nofollow-import-to=tkinter",    # Avoid Tkinter in PySide6 app
    "--output-dir=$distDir",           # Output folder
    "--remove-output"                  # Remove temp build folder
)

# Optional icon support — ONLY added if file exists
$icon = Join-Path $projectRoot "app/assets/poster_maker.ico"
if (Test-Path $icon) {
    $argsList += "--windows-icon-from-ico=$icon"
}

# Add the entry point (must be the ONLY positional arg)
$argsList += $src

# ----- RUN NUITKA -----
pipenv run python -m nuitka @argsList

# ----- CHECK RESULT -----
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Nuitka build failed with exit code $LASTEXITCODE"
} else {
    Write-Host ""
    Write-Host "✅ Build complete!"
    Write-Host "📦 Your executable is inside:"
    Write-Host "    $distDir"
}
