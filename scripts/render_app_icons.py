#!/usr/bin/env python3
"""应用图标(任务栏 / 窗口 / 快捷方式 / 安装包)**由桌宠画出来**,不是一张手放的图。

所有者:「桌面最下面一行应用图标显示的还是星云图片,那个也同样改成一样的桌宠」。
托盘那只早就是桌宠了(``windows_service/pet_icon.py``),任务栏上那个却还是旧的星云图 ——
图是手放进仓库的,桌宠的样子、颜色改了它不会跟着变。

现在这些文件都由 ``pet_icon.render_app_icon`` 一笔一笔画出来(每个尺寸单独画,不是从大图缩):

    electron/assets/icon.ico        Windows 任务栏 / 窗口 / 快捷方式(16–256 多尺寸)
    electron/assets/icon.png        其余平台、electron-builder
    electron/assets/icon-256.png    托盘画不出桌宠时的兜底
    electron/assets/tray-64.png     同上
    desktop-tauri/src-tauri/icons/  Tauri 外壳的同一套

用法::

    python scripts/render_app_icons.py           # 重画并写回
    python scripts/render_app_icons.py --check   # 只核对,与现画的不一致就非零退出

``tests/test_every_pet_is_the_same_pet.py`` 也核对这几张就是桌宠。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from windows_service.pet_icon import render_app_icon  # noqa: E402 —— 必须先把仓库根放进 path

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

#: 文件名 → 边长。.ico 另画。
PNGS = {
    ROOT / "electron" / "assets" / "icon.png": 512,
    ROOT / "electron" / "assets" / "icon-256.png": 256,
    ROOT / "electron" / "assets" / "tray-64.png": 64,
    ROOT / "desktop-tauri" / "src-tauri" / "icons" / "icon.png": 512,
    ROOT / "desktop-tauri" / "src-tauri" / "icons" / "icon-256.png": 256,
}
ICOS = (
    ROOT / "electron" / "assets" / "icon.ico",
    ROOT / "desktop-tauri" / "src-tauri" / "icons" / "icon.ico",
)


def _png_bytes(size: int) -> bytes:
    buf = io.BytesIO()
    render_app_icon(size).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _ico_bytes() -> bytes:
    """每个尺寸单独画再装进同一个 .ico —— 16 像素那张要是从 256 缩下来,眼缝会糊成一片。"""
    images = [render_app_icon(s) for s in ICO_SIZES]
    buf = io.BytesIO()
    images[-1].save(buf, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    return buf.getvalue()


def expected() -> dict:
    out = {path: _png_bytes(size) for path, size in PNGS.items()}
    ico = _ico_bytes()
    out.update({path: ico for path in ICOS})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只核对,不写")
    args = ap.parse_args(argv)
    stale = []
    for path, data in expected().items():
        if path.exists() and path.read_bytes() == data:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    for path in stale:
        print(("不一致: " if args.check else "已重画: ") + str(path.relative_to(ROOT)))
    if not stale:
        print("应用图标都是现画的桌宠。")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
