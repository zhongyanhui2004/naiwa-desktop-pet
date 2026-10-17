"""Exercise single-instance handoff and recovery using only processes we start."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def wait_for(path: Path, text: str, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and text in path.read_text(encoding="utf-8"):
            return
        time.sleep(0.1)
    raise AssertionError(f"Expected log entry: {text}")


def stop(process):
    if process.poll() is None:
        if sys.platform == "win32":
            # The Windows venv redirector may create an interpreter child.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            process.terminate()
    process.wait(timeout=10)
    time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, str(ROOT / "main.py")]
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    with tempfile.TemporaryDirectory(prefix="奶娃-单实例-") as temporary:
        folder = Path(temporary)
        launch = command + ["--no-tray", "--data-dir", str(folder)]
        first = subprocess.Popen(launch, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            log = folder / "naiwa.log"
            wait_for(log, "Started Naiwa")
            second = subprocess.run(launch, cwd=ROOT, env=environment, timeout=20,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert second.returncode == 0, "Second launch did not hand off cleanly"
            wait_for(log, "Existing pet restored")
            assert first.poll() is None, "Original instance stopped unexpectedly"
        finally:
            stop(first)
        previous_starts = log.read_text(encoding="utf-8").count("Started Naiwa")
        restarted = subprocess.Popen(launch, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if log.read_text(encoding="utf-8").count("Started Naiwa") > previous_starts:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Could not recover a stale instance lock")
            assert restarted.poll() is None
        finally:
            stop(restarted)
    print("PASS: single instance, restore existing pet, recover after interrupted process")


if __name__ == "__main__":
    main()
