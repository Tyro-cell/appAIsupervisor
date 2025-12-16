from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


def _candidates_for_platform(platform: str) -> list[str]:
    local = [
        "assets/fonts/NotoSansSC-Regular.otf",
        "assets/fonts/NotoSansCJKsc-Regular.otf",
        "assets/fonts/SourceHanSansCN-Regular.otf",
        "fonts/NotoSansSC-Regular.otf",
        "fonts/NotoSansCJKsc-Regular.otf",
        "fonts/SourceHanSansCN-Regular.otf",
    ]
    if platform == "win":
        return local + [
            r"C:\Windows\Fonts\msyh.ttc",  # Microsoft YaHei
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
    if platform == "android":
        return local + [
            "/system/fonts/NotoSansCJK-Regular.ttc",
            "/system/fonts/NotoSansCJKsc-Regular.otf",
            "/system/fonts/NotoSansSC-Regular.otf",
            "/system/fonts/DroidSansFallback.ttf",
        ]
    if platform == "ios":
        return local + [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        ]
    return local


def find_cjk_font(platform: str) -> Optional[str]:
    """
    Returns a font file path that likely supports CJK, or None.
    Preference order:
    1) Project-bundled fonts (assets/fonts or fonts)
    2) System fonts (platform-specific)
    """
    for p in _candidates_for_platform(platform):
        try:
            path = Path(p)
            if path.is_file():
                return str(path)
        except Exception:
            continue
    return None

