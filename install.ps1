$ErrorActionPreference = "Stop"

$repoName = "johnston"
$uvInstallUrl = "https://astral.sh/uv/install.ps1"

Write-Host "[INFO] Installing uv..."
powershell -ExecutionPolicy ByPass -c "irm $uvInstallUrl | iex"

$localBin = Join-Path $env:USERPROFILE ".local\bin"
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
$env:PATH = "$localBin;$cargoBin;$env:PATH"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Failed to find 'uv'. Add $localBin to PATH and retry." -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Installing $repoName..."
if ((Test-Path "pyproject.toml") -and (Select-String -Path "pyproject.toml" -Pattern 'name = "johnston"' -Quiet)) {
    uv tool install --force .
} else {
    uv tool install --force $repoName
}

Write-Host "[OK] Installed. Run 'johnston' to start Johnston."
