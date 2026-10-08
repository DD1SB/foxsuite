# Build on the target OS; never pretend a Linux executable is a Windows release.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent.parent
data, binaries, hidden = [], [], []
for package in ("foxops", "foxlive", "tzdata", "uvicorn", "websockets", "serial", "jinja2"):
    collected_data, collected_binaries, collected_hidden = collect_all(package)
    data += collected_data
    binaries += collected_binaries
    hidden += collected_hidden
hidden += collect_submodules("foxcore") + collect_submodules("foxbridge")
data += [(str(root / "LICENSE"), ".")]
analysis = Analysis(
    [str(root / "packaging/windows/desktop.py"), str(root / "packaging/windows/cli.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=data,
    hiddenimports=hidden, noarchive=False,
)
library = PYZ(analysis.pure)
hooks = [item for item in analysis.scripts if item[0] not in {"desktop", "cli"}]
desktop_script = next(item for item in analysis.scripts if item[0] == "desktop")
cli_script = next(item for item in analysis.scripts if item[0] == "cli")
desktop = EXE(library, hooks + [desktop_script], [], exclude_binaries=True,
              name="FoxSuite", console=False, upx=False)
console = EXE(library, hooks + [cli_script], [], exclude_binaries=True,
              name="foxsuite-cli", console=True, upx=False)
bundle = COLLECT(desktop, console, analysis.binaries, analysis.datas,
                 name="FoxSuite", upx=False)
