"""Exercise Windows interpreter discovery with PowerShell and controlled PATH results."""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "build.ps1"
HARNESS = r"""
param([string]$BuildScript, [string]$RealPython)
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$functions = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)
foreach ($definition in $functions) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
$script:Commands = @{}
$script:Queries = [System.Collections.Generic.List[string]]::new()
$script:LauncherTarget = $RealPython
$script:LauncherExitCode = 0
function Get-Command {
    param($Name, $CommandType, $ErrorAction)
    if ($CommandType -ne "Application") { throw "Expected application discovery" }
    $script:Queries.Add($Name)
    if ($script:Commands.ContainsKey($Name)) {
        [pscustomobject]@{ Source = $script:Commands[$Name] }
    }
}
function Invoke-Launcher {
    if ($args.Count -ne 3 -or $args[0] -ne "-3" -or
        $args[1] -ne "-c" -or $args[2] -ne 'import sys; print(sys.executable)') {
        throw "Launcher used for more than discovery"
    }
    $global:LASTEXITCODE = $script:LauncherExitCode
    $script:LauncherTarget
}
function Invoke-Python312 {
    & $RealPython -c ('import sys; sys.version_info = (3, 12); ' + $args[1])
}
function Invoke-Python311 {
    & $RealPython -c ('import sys; sys.version_info = (3, 11); ' + $args[1])
}
function Invoke-Python32Bit {
    & $RealPython -c ('import sys; sys.maxsize = 2**31 - 1; ' + $args[1])
}
function Invoke-NoisyPython311 { 'startup banner'; Invoke-Python311 @args }
function Invoke-BrokenPython { throw "Not callable" }
function Assert-Equal($Actual, $Expected) {
    if ($Actual -ne $Expected) { throw "Expected '$Expected', got '$Actual'" }
}
function Assert-MissingPython($Requested = "") {
    try { Find-SupportedPython -Requested $Requested }
    catch {
        if ($_.Exception.Message -notlike '*64-bit Python 3.12+*' -or
            $_.Exception.Message -notlike '*python.exe on PATH*') { throw }
        return
    }
    throw "Unsupported Python was accepted"
}
"""


@pytest.fixture
def run_powershell(tmp_path: Path) -> Callable[[str], None]:
    executable = shutil.which("pwsh") or shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("PowerShell is required to exercise Windows build discovery")

    def run(scenario: str) -> None:
        script = tmp_path / "discovery.ps1"
        script.write_text(HARNESS + scenario, encoding="utf-8")
        result = subprocess.run(
            [executable, "-NoProfile", "-File", str(script), str(BUILD_SCRIPT), sys.executable],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    return run


@pytest.mark.parametrize(
    "scenario",
    [
        # A valid python.exe alone is sufficient; the launcher is never queried.
        r"""
$script:Commands['python.exe'] = $RealPython
Assert-Equal (Find-SupportedPython) $RealPython
Assert-Equal ($script:Queries -join ',') 'python.exe'
""",
        # Prefer python.exe even when a broken launcher is installed.
        r"""
$script:Commands['python.exe'] = $RealPython
$script:Commands['py.exe'] = 'Invoke-BrokenPython'
Assert-Equal (Find-SupportedPython) $RealPython
Assert-Equal ($script:Queries -join ',') 'python.exe'
""",
        # The launcher returns the actual interpreter, without a launcher prefix.
        r"""
$script:Commands['py.exe'] = 'Invoke-Launcher'
Assert-Equal (Find-SupportedPython) $RealPython
Assert-Equal ($script:Queries -join ',') 'python.exe,python3.exe,py.exe'
""",
        # An explicit interpreter wins over both PATH and launcher candidates.
        r"""
$script:Commands[$RealPython] = $RealPython
$script:Commands['python.exe'] = 'Invoke-BrokenPython'
$script:Commands['py.exe'] = 'Invoke-BrokenPython'
Assert-Equal (Find-SupportedPython -Requested $RealPython) $RealPython
Assert-Equal ($script:Queries -join ',') $RealPython
""",
        # Invalid explicit selections must fail instead of silently falling back.
        r"""
$script:Commands['bad-python.exe'] = 'Invoke-Python311'
$script:Commands['python.exe'] = $RealPython
Assert-MissingPython 'bad-python.exe'
Assert-Equal ($script:Queries -join ',') 'bad-python.exe'
""",
        r"""
Assert-MissingPython
$script:Commands['python.exe'] = 'Invoke-BrokenPython'
Assert-MissingPython
$script:Commands['python.exe'] = 'Invoke-Python311'
Assert-MissingPython
$script:Commands['python.exe'] = 'Invoke-Python32Bit'
Assert-MissingPython
$script:Commands['python.exe'] = 'Invoke-NoisyPython311'
Assert-MissingPython
""",
        # A launcher result is checked for version and architecture too.
        r"""
$script:Commands['py.exe'] = 'Invoke-Launcher'
$script:LauncherTarget = 'Invoke-Python311'
Assert-MissingPython
$script:LauncherTarget = 'Invoke-Python32Bit'
Assert-MissingPython
$script:LauncherTarget = $RealPython
$script:LauncherExitCode = 1
Assert-MissingPython
""",
        r"""
Assert-Equal (Test-SupportedPython -Executable $RealPython) $true
Assert-Equal (Test-SupportedPython -Executable 'Invoke-Python312') $true
Assert-Equal (Test-SupportedPython -Executable 'Invoke-Python311') $false
Assert-Equal (Test-SupportedPython -Executable 'Invoke-Python32Bit') $false
Assert-Equal (Test-SupportedPython -Executable 'Invoke-NoisyPython311') $false
Assert-Equal (Test-SupportedPython -Executable 'Invoke-BrokenPython') $false
""",
    ],
    ids=[
        "python-without-launcher",
        "python-before-launcher",
        "launcher-discovers-interpreter",
        "explicit-interpreter",
        "invalid-explicit-interpreter",
        "missing-or-unsupported-python",
        "invalid-launcher-results",
        "version-and-architecture",
    ],
)
def test_python_discovery(run_powershell: Callable[[str], None], scenario: str) -> None:
    run_powershell(scenario)


@pytest.mark.parametrize("launcher_only", [False, True], ids=["python", "launcher-fallback"])
@pytest.mark.parametrize("reuse", [False, True], ids=["new-venv", "existing-venv"])
def test_build_uses_isolated_interpreter(
    run_powershell: Callable[[str], None], launcher_only: bool, reuse: bool
) -> None:
    # Run the actual pipeline with external commands and filesystem checks stubbed.
    # Discovery/version checks still execute real Python; no packages or installers run.
    setup = (
        "$script:Commands['py.exe'] = 'Invoke-Launcher'\n"
        "$script:LauncherTarget = 'Invoke-BasePython'\n"
        if launcher_only
        else "$script:Commands['python.exe'] = 'Invoke-BasePython'\n"
    )
    setup += f"$script:VenvExists = ${str(reuse).lower()}\n"
    run_powershell(
        setup
        + r"""
$Python = ''
$Iscc = 'ISCC.exe'
$ProjectRoot = 'checkout'
$script:Commands['ISCC.exe'] = 'Invoke-Iscc'
$script:BaseCreates = 0
$script:BuildCalls = [System.Collections.Generic.List[object]]::new()
$script:IsccCalls = 0
function Invoke-BasePython {
    if ($args[0] -eq '-c') {
        & $RealPython @args
    } elseif ($args.Count -eq 3 -and ($args -join ' ') -eq '-m venv build-venv') {
        $script:BaseCreates += 1
        $script:VenvExists = $true
        $global:LASTEXITCODE = 0
    } else { throw 'Base interpreter used after bootstrap' }
}
function Join-Path {
    param($Path, $ChildPath)
    switch ($ChildPath) {
        '.venv-windows-build' { 'build-venv' }
        'Scripts\python.exe' { 'Invoke-BuildPython' }
        'pyvenv.cfg' { 'venv-config' }
        default { throw "Unexpected path $ChildPath" }
    }
}
function Test-Path {
    param($LiteralPath, $PathType)
    if ($LiteralPath -eq 'Invoke-BuildPython' -or $LiteralPath -eq 'venv-config') {
        return $script:VenvExists
    }
    return $false
}
function Select-String { param($LiteralPath, $Pattern, [switch]$Quiet) return $true }
function Invoke-BuildPython {
    $script:BuildCalls.Add(@($args))
    if ($args[0] -eq '-c' -and $args[1] -like '*version_info*') {
        & $RealPython @args
    } else { $global:LASTEXITCODE = 0 }
}
function Invoke-Iscc { $script:IsccCalls += 1; $global:LASTEXITCODE = 0 }
function Get-FileHash { param($Path, $Algorithm) }
$existing = $script:VenvExists
$body = $ast.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.TryStatementAst]
}
& ([scriptblock]::Create(($body.Body.Statements.Extent.Text -join "`n")))
Assert-Equal $script:BaseCreates ([int](-not $existing))
Assert-Equal $script:IsccCalls 1
$installs = @($script:BuildCalls | Where-Object { $_[0] -eq '-m' -and $_[1] -eq 'pip' })
Assert-Equal $installs.Count 2
Assert-Equal ($installs[0] -join ' ') '-m pip install --upgrade pip'
Assert-Equal ($installs[1] -join ' ') '-m pip install -e .[dev]'
$modules = @($script:BuildCalls | Where-Object { $_[0] -eq '-m' } | ForEach-Object { $_[1] })
Assert-Equal ($modules -join ',') 'pip,pip,pytest,ruff,ruff,mypy,build,PyInstaller'
$smokes = @($script:BuildCalls | Where-Object { $_[0] -eq 'packaging\smoke.py' })
Assert-Equal $smokes.Count 1
"""
    )
