"""
Build HachiROM-vX.Y.Z.exe with PyInstaller.
Usage:  python build.py
"""
import subprocess, sys, shutil, os, re
from pathlib import Path

ROOT  = Path(__file__).parent
DIST  = ROOT / "dist"
BUILD = ROOT / "build"

# Read version from hachirom/__init__.py without importing the package
init_text = (ROOT / "hachirom" / "__init__.py").read_text()
m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
VERSION = m.group(1) if m else "0.0.0"
EXE_NAME = f"HachiROM-v{VERSION}"

def main():
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)

    # roms/ directory may not exist yet — create empty one to satisfy --add-data
    roms_dir = ROOT / "roms"
    roms_dir.mkdir(exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", EXE_NAME,
        "--add-data", f"{ROOT / 'hachirom'}{os.pathsep}hachirom",
        "--add-data", f"{ROOT / 'roms'}{os.pathsep}roms",
        str(ROOT / "app" / "main.py"),
    ]

    subprocess.run(cmd, check=True)

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    exe = DIST / f"{EXE_NAME}{exe_suffix}"
    print(f"\nBuild complete: {exe}  (version {VERSION})")

    # Write the versioned name to a file so CI can reference it
    (DIST / "exe_name.txt").write_text(f"{EXE_NAME}{exe_suffix}")

if __name__ == "__main__":
    main()
