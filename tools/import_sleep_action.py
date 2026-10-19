"""Rebuild the sleep action from pinned PNG frames (requires Pillow).

This deterministic import does not establish permission to redistribute the art.
See assets/actions/sleep_SOURCE.json and third_party/NOTICE.md for provenance.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image


REVISION = "45857f860a221a4af1fd2469d658cc7ad8b4462e"
REPOSITORY = "woainiunai/yellow-belly-creature-desktop"
FRAMES = {
    "00.png": "4bef0859fa2279e1b3cfc28450c52e33ac40abc597af780b6528cd77dcad038a",
    "01.png": "d460a2f57d56013ac55971595f24d48a5b010c03468627063dddc4740cb8f921",
    "02.png": "a9ab51747b2aa7c1150201487ef9bc401abcbed360730fc6ae1c7e42c66ae901",
}


def build(source_dir: Path | None, output: Path) -> None:
    sheet = Image.new("RGBA", (192 * len(FRAMES), 208))
    for index, (name, expected) in enumerate(FRAMES.items()):
        if source_dir:
            contents = (source_dir / name).read_bytes()
        else:
            url = (f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/"
                   f"assets/animations/sleep/{name}")
            with urlopen(Request(url, headers={"User-Agent": "Naiwa-sleep-import"}),
                         timeout=30) as response:
                contents = response.read()
        if hashlib.sha256(contents).hexdigest() != expected:
            raise ValueError(f"Source hash mismatch: {name}")
        with Image.open(BytesIO(contents)) as source:
            if source.mode != "RGBA" or source.size != (220, 224):
                raise ValueError(f"Unexpected source dimensions or mode: {name}")
            # Use one shared crop and scale to preserve pose and Z positions.
            frame = source.crop((8, 28, 203, 178)).resize(
                (176, 135), Image.Resampling.LANCZOS)
            sheet.alpha_composite(frame, (index * 192 + 8, 65))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, optimize=False, compress_level=9)
    print(f"Wrote {output}: RGBA {sheet.width}x{sheet.height}, 3 frames")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "assets/actions/sleep.png")
    arguments = parser.parse_args()
    build(arguments.source_dir, arguments.output)
