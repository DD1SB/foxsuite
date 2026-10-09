param(
    [string]$Python = "",
    [string]$Iscc = "ISCC.exe"
)
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Build Windows installers on Windows." }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Test-SupportedPython {
    param([string]$Executable)
    try {
        $null = & $Executable -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) and sys.maxsize == 2**63 - 1 else 1)' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-SupportedPython {
    param([string]$Requested)
    $candidates = if ($Requested) { @($Requested) } else { @("python.exe", "python3.exe") }
    foreach ($candidate in $candidates) {
        $command = Get-Command -Name $candidate -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command -and (Test-SupportedPython -Executable $command.Source)) {
            return $command.Source
        }
    }
    # The launcher is optional and only discovers a real interpreter. It never
    # creates the venv or runs any build step.
    if (-not $Requested) {
        $launcher = Get-Command -Name "py.exe" -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($launcher) {
            try {
                $executable = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-SupportedPython -Executable $executable)) {
                    return $executable
                }
            } catch {
                # Missing/broken launcher installations do not change the requirements.
            }
        }
    }
    throw "64-bit Python 3.12+ was not found. Install Python with python.exe on PATH or pass -Python PATH_TO_PYTHON_EXE."
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
    $BasePython = Find-SupportedPython -Requested $Python
    $IsccCommand = Find-InnoCompiler -Requested $Iscc

    $BuildVenv = Join-Path $ProjectRoot ".venv-windows-build"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $BuildPython -PathType Leaf)) {
        if (Test-Path -LiteralPath $BuildVenv) {
            throw "Incomplete build environment at $BuildVenv. Remove that directory and rerun the build."
        }
        & $BasePython -m venv $BuildVenv
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
    & $BuildPython -m pip install -e ".[dev]"
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
    # The venv's smoke runner checks both frozen executables, including CLI --help.
    & $BuildPython packaging\smoke.py --desktop dist\FoxSuite\FoxSuite.exe --cli dist\FoxSuite\foxsuite-cli.exe
    if ($LASTEXITCODE -ne 0) { throw "Frozen desktop HTTP/WebSocket/backup smoke failed" }
    & $IsccCommand packaging\windows\foxsuite.iss
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }
    Get-FileHash dist\installer\*.exe -Algorithm SHA256
} finally {
    Pop-Location
}
