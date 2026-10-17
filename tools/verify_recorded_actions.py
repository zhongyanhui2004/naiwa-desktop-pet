"""Validate all real recording frames, including the retained opaque belly."""
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "assets" / "actions"


def main():
    metadata = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for action in metadata["actions"]:
        sheet = Image.open(ROOT / action["sheet"])
        width, height, count = action["frame_width"], action["frame_height"], action["frame_count"]
        assert sheet.mode == "RGBA"
        assert sheet.size == (width * count, height)
        for index in range(count):
            frame = sheet.crop((index * width, 0, (index + 1) * width, height))
            assert frame.getbbox(), (action["id"], index, "empty frame")
            assert frame.getpixel((0, 0))[3] == 0
            assert frame.getpixel((width - 1, height - 1))[3] == 0
            assert frame.getpixel((96, 150))[3] == 255, (action["id"], index, "belly removed")
        print(f"PASS: {action['id']}, {count} frames; transparent background and opaque belly")


if __name__ == "__main__":
    main()
