"""Check the built application outside its working folder with no Python PATH."""
import json
import hashlib
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "奶娃桌宠" / "奶娃桌宠.exe"
REPORT = ROOT / "artifacts" / "portable-report.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    dist = args.dist_dir.resolve()
    exe = dist / "奶娃桌宠" / "奶娃桌宠.exe"
    REPORT.unlink(missing_ok=True)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "QT_QPA_PLATFORM"}}
    environment["PATH"] = os.environ.get("SystemRoot", "C:/Windows") + "/System32"
    process = subprocess.Popen([
        str(exe), "--smoke-test", "--no-tray", "--data-dir", str(ROOT / "artifacts" / "portable-data"),
        "--report", str(REPORT), "--preview-dir", str(ROOT / "artifacts" / "portable-preview"),
    ], cwd=tempfile.gettempdir(), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        output, errors = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        output, errors = process.communicate()
        raise RuntimeError("Portable launch timed out. " + errors.decode("utf-8", errors="replace"))
    print(output.decode("utf-8", errors="replace"))
    print(errors.decode("utf-8", errors="replace"))
    assert process.returncode == 0, process.returncode
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    assert data["ok"] and data["frozen"]
    assert data["version"] == "2.0.0", "Portable application version is outdated"
    assert set(data["custom_actions"]) == {"q_wave", "q_wiggle", "q_drag", "sleep", "relax"}, "Actions were not bundled"
    assert data["custom_actions"]["q_drag"]["trigger"] == "drag"
    assert not data["custom_actions"]["q_drag"]["automatic"], "Dragging must not be a random action"
    assert data["custom_actions"]["sleep"]["trigger"] == "sleep"
    assert not data["custom_actions"]["sleep"]["automatic"], "Sleep must be a persistent state, not a random action"
    assert data["sleep_animation_available"] and data["auto_sleep_enabled"]
    assert data["sleep_persists"] and data["wake_restores_idle"]
    assert not data["custom_actions"]["relax"]["automatic"], "Relax should only be triggered manually"
    assert data["relax_animation_available"] and data["relax_returns_idle"] and data["silent"]
    assert not (exe.parent / "_internal" / "winsound.pyd").exists(), "Audio playback module must not be bundled"
    print(json.dumps(data, ensure_ascii=False))
    archive = dist / "奶娃桌宠-Windows-x64.zip"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        archived_exe = bundle.read("奶娃桌宠/奶娃桌宠.exe")
        assert hashlib.sha256(archived_exe).digest() == hashlib.sha256(exe.read_bytes()).digest(), "ZIP contains an outdated executable"
        assert not any(name.endswith("/_internal/icuuc.dll") for name in bundle.namelist()), "Unrelated ICU must not shadow Windows ICU"
        assert not any(Path(name).suffix.lower() in {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}
                       for name in bundle.namelist()), "Silent application must not bundle audio files"
        print(f"ZIP intact: {archive.stat().st_size / 1024 / 1024:.1f} MB, {len(bundle.namelist())} entries")


if __name__ == "__main__":
    main()
