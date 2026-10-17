"""Build a portable Windows folder and ZIP, including notices and shared Qt DLLs."""
from pathlib import Path
from importlib.metadata import distribution
import argparse
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    debug = args.console
    destination = args.dist_dir.resolve()
    if not destination.is_relative_to(ROOT) or destination == ROOT:
        raise ValueError("Build output must be inside the project directory")
    for package, folder in [("PySide6-Essentials", "qt"), ("shiboken6", "shiboken6"), ("pyinstaller", "pyinstaller")]:
        metadata = distribution(package)
        target = ROOT / "third_party" / folder
        target.mkdir(parents=True, exist_ok=True)
        (target / "PACKAGE-METADATA.txt").write_text(metadata.read_text("METADATA") or "", encoding="utf-8")
        for file in metadata.files or []:
            if "licenses/" in str(file).replace("\\", "/"):
                shutil.copy2(metadata.locate_file(file), target / Path(file).name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, ROOT / "third_party" / "Python-LICENSE.txt")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--console" if debug else "--windowed", "--onedir",
        "--name", "奶娃桌宠", "--icon", str(ROOT / "assets" / "icon.ico"),
        "--distpath", str(destination),
        "--add-data", f"{ROOT / 'assets'};assets", "--exclude-module", "PySide6.QtTest",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        str(ROOT / "main.py"),
    ], cwd=ROOT, check=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    output = destination / "奶娃桌宠"
    # Qt 6.12 uses Windows' built-in ICU (unsuffixed exports). PyInstaller can
    # accidentally collect an unrelated ICU from PATH with suffixed exports.
    # Keep the Windows 10/11 system dependency rather than shadowing it.
    for filename in ("icuuc.dll", "icudt78.dll"):
        (output / "_internal" / filename).unlink(missing_ok=True)
    shutil.copytree(ROOT / "third_party", output / "third_party", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", output / "使用说明.md")
    shutil.copytree(ROOT / "docs", output / "docs", dirs_exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    if debug:
        print(f"Debug build: {output / '奶娃桌宠.exe'}")
        return
    archive = shutil.make_archive(str(destination / "奶娃桌宠-Windows-x64"), "zip", destination, "奶娃桌宠")
    print(f"\n程序：{output / '奶娃桌宠.exe'}\n便携包：{archive}")


if __name__ == "__main__":
    main()
