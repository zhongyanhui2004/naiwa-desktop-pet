"""Rebuild the relax action from pinned PNG frames (requires Pillow).

This imports artwork only; it does not establish permission to redistribute it.
See assets/actions/relax_SOURCE.json and third_party/NOTICE.md for provenance.
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
    "00.png": "ea4733e05fdd7290b2081804598d5a9cc795d75a5a63f91d034688374ef0a044",
    "01.png": "18a7e2193f54d35e3f317e941b58aa950b753512a53cbcf55b01f94c3a7819d4",
    "02.png": "b5a66139bfbcea8d06c087afa36f70ee73e73d525614edf6d32b6db538f705ef",
    "03.png": "bc509fcaf13497ecd8903daa5f4e7ebdf3dd7c1587f43fba9ea5268eefa42086",
}
CANVAS = (192, 208)
CROP = (7, 0, 553, 529)
RESIZED = (180, 174)
OFFSET = (6, 26)


def build(source_dir: Path | None, output: Path) -> None:
    sheet = Image.new("RGBA", (CANVAS[0] * len(FRAMES), CANVAS[1]))
    for index, (name, expected) in enumerate(FRAMES.items()):
        if source_dir:
            contents = (source_dir / name).read_bytes()
        else:
            url = (f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/"
                   f"assets/animations/relax/{name}")
            with urlopen(Request(url, headers={"User-Agent": "Naiwa-relax-import"}),
                         timeout=30) as response:
                contents = response.read()
        if hashlib.sha256(contents).hexdigest() != expected:
            raise ValueError(f"Source hash mismatch: {name}")
        with Image.open(BytesIO(contents)) as source:
            if source.mode != "RGBA" or source.size != (615, 536):
                raise ValueError(f"Unexpected source dimensions or mode: {name}")
            # A shared transform keeps the character and feet still while the
            # cloud expands. The complete visible union fits the established
            # canvas; feet are at y=187 and the final cloud extends to y=200.
            frame = source.crop(CROP).resize(RESIZED, Image.Resampling.LANCZOS)
            sheet.alpha_composite(frame, (index * CANVAS[0] + OFFSET[0], OFFSET[1]))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, optimize=False, compress_level=9)
    print(f"Wrote {output}: RGBA {sheet.width}x{sheet.height}, {len(FRAMES)} frames")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "assets/actions/relax.png")
    arguments = parser.parse_args()
    build(arguments.source_dir, arguments.output)
