from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile
import time

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from naiwa import PetWindow
from version import APP_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="奶娃桌宠")
    parser.add_argument("--panel", action="store_true", help="启动时打开小窝")
    parser.add_argument("--no-tray", action="store_true", help="不创建托盘图标（用于测试）")
    parser.add_argument("--data-dir", type=Path, help="指定设置与日志目录")
    parser.add_argument("--quit-after", type=float, help="指定秒数后正常退出（用于验证）")
    parser.add_argument("--smoke-test", action="store_true", help="检查资源和界面后退出")
    parser.add_argument("--report", type=Path, help="写入验证报告")
    parser.add_argument("--preview-dir", type=Path, help="保存桌宠与小窝截图")
    args = parser.parse_args()

    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Naiwa.DesktopPet.1")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("奶娃桌宠")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("NaiwaDesktopPet")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setQuitOnLastWindowClosed(False)
    smoke_data = tempfile.TemporaryDirectory(prefix="naiwa-smoke-") if args.smoke_test and args.data_dir is None else None
    data = args.data_dir or (Path(smoke_data.name) if smoke_data else
                            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local"))) / "NaiwaDesktopPet")
    data.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "naiwa.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")

    def cleanup_smoke_data():
        if smoke_data is not None:
            # Windows cannot remove the temporary log while its handle is open.
            logging.getLogger().removeHandler(handler)
            handler.close()
            smoke_data.cleanup()

    def log_exception(kind, value, traceback):
        logging.error("Unhandled error", exc_info=(kind, value, traceback))
        app.exit(1)

    sys.excepthook = log_exception
    lock = None
    server = None
    # Preview and validation runs must never replace or focus the real pet.
    testing = args.smoke_test or args.preview_dir is not None or args.quit_after is not None
    if not testing:
        lock = QLockFile(str(data / "instance.lock"))
        lock.setStaleLockTime(0)
        server_name = "naiwa-" + hashlib.sha256(str(data.resolve()).encode()).hexdigest()[:20]
        if not lock.tryLock(100):
            socket = QLocalSocket()
            socket.connectToServer(server_name)
            if socket.waitForConnected(1500):
                socket.write(b"show")
                socket.waitForBytesWritten(1000)
                socket.disconnectFromServer()
            return 0
        QLocalServer.removeServer(server_name)
        server = QLocalServer(app)
        if not server.listen(server_name):
            logging.warning("Single instance notification unavailable: %s", server.errorString())

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        pet = PetWindow(root / "assets", data / "settings.json",
                        enable_tray=not args.no_tray and not args.smoke_test)
    except Exception as error:
        logging.exception("Cannot start pet")
        if not args.smoke_test:
            QMessageBox.critical(None, "奶娃还没准备好", f"启动失败：{error}\n\n请保留完整程序文件夹。日志：{data / 'naiwa.log'}")
        cleanup_smoke_data()
        return 1
    app.setWindowIcon(pet.app_icon)
    if server is not None:
        def existing_instance_request():
            while server.hasPendingConnections():
                connection = server.nextPendingConnection()
                connection.disconnectFromServer()
                connection.deleteLater()
            pet.show_pet()
            pet.open_panel()
            logging.info("Existing pet restored by another launch")
        server.newConnection.connect(existing_instance_request)

    app.aboutToQuit.connect(pet.save_preferences)
    pet.show_pet()
    if args.panel:
        pet.open_panel()

    if args.smoke_test or args.preview_dir:
        def verify():
            try:
                pet.open_panel()
                app.processEvents()
                sleep_animation_available = "sleep" in pet.custom_actions
                if not sleep_animation_available:
                    raise RuntimeError("Sleep animation was not loaded")
                pet.play("sleep", speak=False)
                # Make the animation older than many cycles without delaying
                # the smoke test; waking resets its animation clock normally.
                sleep_position = pet.pos()
                pet.action_started -= 600
                pet._tick()
                sleep_persists = pet.sleeping and pet.action == "sleep" and pet.pos() == sleep_position
                if not sleep_persists:
                    raise RuntimeError("Sleep did not persist without movement")
                pet.wake(speak=False)
                wake_restores_idle = not pet.sleeping and pet.action == "idle"
                if not wake_restores_idle:
                    raise RuntimeError("Waking did not restore idle")
                relax_animation_available = "relax" in pet.custom_actions
                if not relax_animation_available:
                    raise RuntimeError("Relax animation was not loaded")
                pet.play("relax", speak=False)
                pet.action_until = time.monotonic() - 1
                pet._tick()
                relax_returns_idle = pet.action == "idle" and not pet.sleeping
                if not relax_returns_idle:
                    raise RuntimeError("Relax action did not finish")
                app.processEvents()
                report = {
                    "ok": True,
                    "version": APP_VERSION,
                    "sprite_size": [1536, 2288],
                    "animation_frames": {name: len(frames) for name, frames in pet.atlas.frames.items()},
                    "look_directions": len(pet.atlas.look),
                    "custom_actions": {name: {"frames": action.clip.count, "fps": action.clip.fps,
                                               "loops": action.loops, "automatic": action.random,
                                               "trigger": action.trigger}
                                       for name, action in pet.custom_actions.items()},
                    "auto_actions_enabled": pet.preferences.auto_actions,
                    "sleep_animation_available": sleep_animation_available,
                    "auto_sleep_enabled": pet.preferences.auto_sleep,
                    "sleep_persists": sleep_persists,
                    "wake_restores_idle": wake_restores_idle,
                    "relax_animation_available": relax_animation_available,
                    "silent": True,
                    "relax_returns_idle": relax_returns_idle,
                    "pet_visible": pet.isVisible(),
                    "panel_visible": pet.panel.isVisible(),
                    "frozen": bool(getattr(sys, "frozen", False)),
                }
                if args.preview_dir:
                    args.preview_dir.mkdir(parents=True, exist_ok=True)
                    if not pet.grab().save(str(args.preview_dir / "pet.png")):
                        raise RuntimeError("Cannot save pet preview")
                    if not pet.panel.grab().save(str(args.preview_dir / "panel.png")):
                        raise RuntimeError("Cannot save panel preview")
                    for name in pet.custom_actions:
                        pet.play(name, speak=False)
                        pet.bubble_text = ""
                        pet._display_key = None
                        pet._refresh_frame()
                        app.processEvents()
                        if not pet.grab().save(str(args.preview_dir / f"{name}.png")):
                            raise RuntimeError(f"Cannot save action preview: {name}")
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                logging.info("Smoke test passed: %s", report)
                pet.quit_pet()
            except Exception:
                logging.exception("Smoke test failed")
                app.exit(1)
        QTimer.singleShot(400, verify)
    elif args.quit_after is not None:
        QTimer.singleShot(max(100, round(args.quit_after * 1000)), pet.quit_pet)

    logging.info("Started Naiwa Desktop Pet %s", APP_VERSION)
    exit_code = app.exec()
    if server is not None:
        server.close()
    if lock is not None:
        lock.unlock()
    cleanup_smoke_data()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
