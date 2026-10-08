param(
    [string]$Python = "python",
    [string]$Iscc = "ISCC.exe"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build Windows installers on Windows." }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $ProjectRoot
try {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    & $Python -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw "Lint failed" }
    & $Python -m ruff format --check src tests
    if ($LASTEXITCODE -ne 0) { throw "Format failed" }
    & $Python -m mypy src tests
    if ($LASTEXITCODE -ne 0) { throw "Types failed" }
    & $Python -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { throw "Package build failed" }
    & $Python -m PyInstaller --noconfirm packaging\windows\foxsuite.spec
    if ($LASTEXITCODE -ne 0) { throw "Frozen build failed" }
    & dist\FoxSuite\foxsuite-cli.exe --help
    if ($LASTEXITCODE -ne 0) { throw "Frozen CLI smoke failed" }
    & $Python packaging\smoke.py --desktop dist\FoxSuite\FoxSuite.exe --cli dist\FoxSuite\foxsuite-cli.exe
    if ($LASTEXITCODE -ne 0) { throw "Frozen desktop HTTP/WebSocket/backup smoke failed" }
    & $Iscc packaging\windows\foxsuite.iss
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
    Get-FileHash dist\installer\*.exe -Algorithm SHA256
} finally {
    Pop-Location
}
