# Third-party notices

## Naiwa animation and metadata

Source: https://github.com/timerring/codex-pet-naiwa

Pinned revision: `3c0cd7ca231f02e0d4d6956fc6ce86eb9f0cfb50`

Unmodified files: `assets/naifrog/spritesheet.webp`, `assets/naifrog/pet.json`.
`assets/icon.png` and `assets/icon.ico` are derived from the first idle frame.
Upstream README and MIT license are included in this directory.

Upstream copyright: Copyright (c) 2026 timerring.
The upstream repository's original content is MIT licensed. Its README explicitly
excludes third-party material listed in its Credits from that MIT license.
This application does not assert new or broader rights over that material.

Upstream credits:
- https://github.com/Nitrogen216/awesome_pets
- https://github.com/LynnShaw/naiwa-pet

## Additional recorded animations

`assets/actions/q_wave.png` and `assets/actions/q_wiggle.png` were extracted
from the user's supplied screen recording on 2026-10-16. They retain the
recorded motion, with background removal and canvas alignment. Provenance
and processing ranges are in `assets/actions/SOURCE.json`. The original
recording is not included in the portable distribution. These images are
not covered by the MIT license of the newly written application code.

`assets/actions/q_drag.png` was extracted from the user's additional video
on 2026-10-16, preserving the recorded riding motion on a transparent canvas.
Its source hash and extraction range are recorded in
`assets/actions/q_drag_SOURCE.json`. This image is likewise not covered by
the application code's MIT license. The source video is not distributed.

## PySide6, Shiboken6 and Qt 6.12.0

Copyright (C) The Qt Company Ltd. and other contributors.
This application uses the open-source LGPLv3 distribution of PySide6-Essentials
and Shiboken6. Qt shared libraries remain separate in the portable `_internal`
directory so that compatible replacements can be used.
The original license texts distributed with the wheels are included under
`third_party/qt/` and `third_party/shiboken6/`.

Unmodified library source packages:
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
- https://download.qt.io/official_releases/qt/6.12/6.12.0/single/
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/

Qt licensing information: https://doc.qt.io/qtforpython-6/licenses.html

## Packaging

Built using PyInstaller 6.22.3, GPLv2 with its bootloader exception.
Python 3.12 is distributed under the Python Software Foundation License.
Bundled dependency notices are collected into this directory by `build.py`.
