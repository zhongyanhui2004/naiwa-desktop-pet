"""Check Windows batch encoding and cmd parsing without running the pet."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = ("启动奶娃.bat", "安装开发环境.bat", "打包Windows.bat")


def check_batch_bytes(path: Path) -> None:
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf"), f"{path.name}: UTF-8 BOM is not supported by cmd.exe"
    content.decode("utf-8", errors="strict")
    assert b"\r\n" in content, f"{path.name}: expected Windows CRLF line endings"
    remaining = content.replace(b"\r\n", b"")
    assert b"\r" not in remaining and b"\n" not in remaining, f"{path.name}: mixed or LF-only line endings"
    assert content.endswith(b"\r\n"), f"{path.name}: missing final CRLF"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This check requires Windows and cmd.exe.")

    for name in LAUNCHERS:
        check_batch_bytes(ROOT / name)

    with tempfile.TemporaryDirectory(prefix="奶娃 启动检查-") as temporary:
        folder = Path(temporary)
        project = folder / "中文 项目目录"
        project.mkdir()
        launcher = project / LAUNCHERS[0]
        shutil.copyfile(ROOT / LAUNCHERS[0], launcher)
        target = project / "dist" / "奶娃桌宠" / "奶娃桌宠.exe"
        target.parent.mkdir(parents=True)
        # This is deliberately not an executable: --check must only resolve it.
        target.write_bytes(b"launch-path-check-only\r\n")
        unrelated = folder / "无关 工作目录"
        unrelated.mkdir()
        cmd = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "cmd.exe")
        # /s keeps the explicit outer pair of command-string quotes predictable.
        command = f'"{cmd}" /d /s /c ""{launcher}" --check"'
        result = subprocess.run(
            command,
            cwd=unrelated,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
        output = result.stdout.decode("utf-8", errors="strict")
        errors = result.stderr.decode("utf-8", errors="strict")
        assert result.returncode == 0, f"Launcher returned {result.returncode}: {output!r} {errors!r}"
        assert str(target) in output, f"Launcher did not report the expected absolute target: {output!r}"
        assert not errors.strip(), f"cmd.exe reported a parsing or path error: {errors!r}"

    print("PASS: UTF-8/CRLF batch files and cmd launch-path check from a Chinese path with spaces")


if __name__ == "__main__":
    main()
