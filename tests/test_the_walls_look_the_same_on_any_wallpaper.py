"""中间态的四面墙：浅壁纸与深壁纸上是同一堵墙。

覆盖层的窗口是透明的，桌面在窗口背后，CSS 混合触不到 OS 合成那一层。墙原先只是一层淡紫（整体 alpha ≤ .52）：
叠在深壁纸上是一圈深紫，叠在浅壁纸上几乎看不见 —— 所有者看到的是「深的能看见、浅的就没了」。

现在每面墙自己带一层深色底，**近端不透明**，沿同一条衰减曲线化回桌面；淡紫叠在这块底上，于是两种壁纸上
看到的近端是同一块实的深紫，往里按 (1-t)² 变淡。浓度 --n 不再乘在整面墙的 opacity 上（那会把底压成半透明），
改乘进淡紫那一层的 alpha。
"""

from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "electron" / "renderer" / "index.html").read_text(encoding="utf-8")


def _block(selector: str) -> str:
    return re.search(re.escape(selector) + r"\s*\{([^}]*)\}", HTML).group(1)


def _stops(var: str) -> list:
    body = re.search(r"--" + var + r":(.*?);", HTML, re.S).group(1)
    return re.findall(r"rgba\((\d+),(\d+),(\d+),([^)]*(?:\([^)]*\))?[^)]*)\)\s+(\d+)%", body)


def test_the_base_is_opaque_at_the_near_edge_and_gone_at_the_far_end():
    stops = _stops("wall-base")
    assert stops, "墙没有自己的深色底"
    assert float(stops[0][3]) == 1.0, "近端的底必须不透明，否则浅壁纸会透进来"
    assert float(stops[-1][3]) == 0.0, "远端必须化回桌面，不能留硬边"
    alphas = [float(s[3]) for s in stops]
    assert alphas == sorted(alphas, reverse=True), "底的 alpha 必须沿纵深单调衰减"


def test_the_base_and_the_lilac_share_one_decay_curve():
    base = [(s[4], float(s[3])) for s in _stops("wall-base")]
    lilac = re.findall(
        r"calc\(([\d.]+) \* var\(--n\)\)\)\s+(\d+)%", re.search(r"--wall-grad:(.*?);", HTML, re.S).group(1)
    )
    assert [(pos, float(a)) for a, pos in lilac] == [(p, a) for p, a in base[:-1]], "两层的站点必须同一条曲线"


def test_every_wall_paints_the_lilac_over_the_base():
    for side in ("t", "b", "l", "r"):
        bg = re.search(r"\.wall-" + side + r" \{ (background:[^}]*)\}", HTML).group(1)
        assert "var(--wall-grad)" in bg and "var(--wall-base)" in bg, f".wall-{side} 少了一层"
        assert bg.index("--wall-grad") < bg.index("--wall-base"), "淡紫要在底的上面（第一层是最上层）"


def test_density_is_in_the_lilac_alpha_not_on_the_whole_walls_opacity():
    wall = _block(".wall")
    assert (
        "opacity: var(--wop)" in wall and "--n" not in wall.split("filter")[0]
    ), "--n 乘在整面墙的 opacity 上会把深色底也压成半透明，浅壁纸就又透进来了"
    assert "var(--n)" in re.search(r"--wall-grad:(.*?);", HTML, re.S).group(1)
