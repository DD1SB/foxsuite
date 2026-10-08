param(
    [string]$Python = "",
    [string]$Iscc = "ISCC.exe"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build Windows installers on Windows." }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Test-SupportedPython {
    param([string]$Executable, [string[]]$Prefix = @())
    try {
        $result = & $Executable @Prefix -c 'import sys; print("yes" if sys.version_info >= (3, 12) and sys.maxsize > 2**32 else "no")' 2>$null
        return ($LASTEXITCODE -eq 0 -and $result -eq "yes")
    } catch {
        return $false
    }
}

function Find-InnoCompiler {
    param([string]$Requested)
    $command = Get-Command -Name $Requested -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Source }
    if (Test-Path -LiteralPath $Requested -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Requested).Path
    }
    if ($Requested -eq "ISCC.exe") {
        $roots = @(
            [Environment]::GetEnvironmentVariable("ProgramFiles(x86)"),
            [Environment]::GetEnvironmentVariable("ProgramFiles")
        )
        $local = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
        if ($local) { $roots += (Join-Path $local "Programs") }
        foreach ($root in $roots) {
            if (-not $root) { continue }
            $path = Join-Path $root "Inno Setup 6\ISCC.exe"
            if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
        }
    }
    throw "Inno Setup 6 compiler (ISCC.exe) was not found. Install Inno Setup 6 or pass -Iscc PATH_TO_ISCC_EXE."
}

Push-Location $ProjectRoot
try {
    # The interpreter is only used to create the isolated environment. All
    # package installation, checks and bundling use that environment's Python.
    if ($Python) {
        $candidates = @([pscustomobject]@{ Executable = $Python; Prefix = @() })
    } else {
        $candidates = @(
            [pscustomobject]@{ Executable = "py"; Prefix = @("-3") }
            [pscustomobject]@{ Executable = "python"; Prefix = @() }
            [pscustomobject]@{ Executable = "python3"; Prefix = @() }
        )
    }
    $selected = $null
    foreach ($candidate in $candidates) {
        if (-not (Get-Command -Name $candidate.Executable -CommandType Application -ErrorAction SilentlyContinue)) {
            continue
        }
        if (Test-SupportedPython -Executable $candidate.Executable -Prefix $candidate.Prefix) {
            $selected = $candidate
            break
        }
    }
    if (-not $selected) {
        throw "64-bit Python 3.12+ was not found. Install it or pass -Python PATH_TO_PYTHON_EXE."
    }
    $IsccCommand = Find-InnoCompiler -Requested $Iscc

    $BuildVenv = Join-Path $ProjectRoot ".venv-windows-build"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $BuildPython -PathType Leaf)) {
        if (Test-Path -LiteralPath $BuildVenv) {
            throw "Incomplete build environment at $BuildVenv. Remove that directory and rerun the build."
        }
        $BasePython = $selected.Executable
        $BaseArgs = $selected.Prefix
        & $BasePython @BaseArgs -m venv $BuildVenv
        if ($LASTEXITCODE -ne 0) { throw "Could not create build environment at $BuildVenv." }
    }
    if (-not (Test-SupportedPython -Executable $BuildPython)) {
        throw "Build environment at $BuildVenv needs 64-bit Python 3.12+. Recreate it and rerun."
    }
    & $BuildPython -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)'
    if ($LASTEXITCODE -ne 0) { throw "Build environment at $BuildVenv is not isolated." }
    $VenvConfig = Join-Path $BuildVenv "pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $VenvConfig -PathType Leaf) -or
        -not (Select-String -LiteralPath $VenvConfig -Pattern '^include-system-site-packages\s*=\s*false\s*$' -Quiet)) {
        throw "Build environment at $BuildVenv exposes global Python packages. Recreate it and rerun."
    }

    & $BuildPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip in the build environment." }
    # Python 3.12+ no longer installs setuptools into new venvs by default.
    # These are also declared in pyproject.toml for the no-isolation build.
    & $BuildPython -m pip install --upgrade "setuptools>=69" "wheel>=0.42" "build>=1"
    if ($LASTEXITCODE -ne 0) { throw "Could not install the package build backend and tools." }
    & $BuildPython -m pip install -e ".[dev,ui-test,windows-build]"
    if ($LASTEXITCODE -ne 0) { throw "Could not install FoxSuite build/test dependencies." }

    & $BuildPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    & $BuildPython -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw "Lint failed" }
    & $BuildPython -m ruff format --check src tests
    if ($LASTEXITCODE -ne 0) { throw "Format failed" }
    & $BuildPython -m mypy src tests
    if ($LASTEXITCODE -ne 0) { throw "Types failed" }
    & $BuildPython -m build --no-isolation
    if ($LASTEXITCODE -ne 0) { throw "Package build failed" }
    & $BuildPython -m PyInstaller --noconfirm packaging\windows\foxsuite.spec
    if ($LASTEXITCODE -ne 0) { throw "Frozen build failed" }
    & dist\FoxSuite\foxsuite-cli.exe --help
    if ($LASTEXITCODE -ne 0) { throw "Frozen CLI smoke failed" }
    & $BuildPython packaging\smoke.py --desktop dist\FoxSuite\FoxSuite.exe --cli dist\FoxSuite\foxsuite-cli.exe
    if ($LASTEXITCODE -ne 0) { throw "Frozen desktop HTTP/WebSocket/backup smoke failed" }
    & $IsccCommand packaging\windows\foxsuite.iss
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
    Get-FileHash dist\installer\*.exe -Algorithm SHA256
} finally {
    Pop-Location
}
