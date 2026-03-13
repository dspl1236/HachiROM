"""
Build HachiROM.exe / HachiROM (macOS/Linux app) with PyInstaller.
Usage:  python build.py
"""
import subprocess, sys, shutil, os
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

def main():
    # Clean previous builds
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "HachiROM",
        "--add-data", f"{ROOT / 'hachirom'}{os.pathsep}hachirom",
        "--add-data", f"{ROOT / 'roms'}{os.pathsep}roms",
        str(ROOT / "app" / "main.py"),
    ]

    subprocess.run(cmd, check=True)
    exe = DIST / ("HachiROM.exe" if sys.platform == "win32" else "HachiROM")
    print(f"\nBuild complete: {exe}")

if __name__ == "__main__":
    main()
