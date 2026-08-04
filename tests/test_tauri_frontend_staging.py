"""Tauri 二进制不该背着 68 MB 的构建期依赖。

背景
----
``tauri.conf.json`` 的 ``frontendDist`` 原本直接指向 ``electron/renderer``，
而 tauri 会把那个目录**整个**嵌进二进制。查过 tauri-codegen 的源码
(``embedded_assets.rs``)，资产收集是 ``WalkDir::new(&path).follow_links(true)``,
**没有任何过滤机制** —— 没有 .taurignore、没有 exclude 配置项。于是
``electron/renderer/panel/node_modules``(68 MB,运行期一字节用不到)也一起进去。

换 Tauri 的全部理由就是"别再每个应用背一份 Chromium"。二进制里塞 68 MB
构建期依赖，等于把省下来的又还回去。

现在 ``build.rs`` 先把运行期资产暂存到 ``desktop-tauri/frontend/``,
``frontendDist`` 指向那里。实测(同机、只改 frontendDist 各构建一次):

    源目录 87.7 MB → debug 二进制 349.2 MB
    源目录  7.8 MB → debug 二进制 331.1 MB      省 18.1 MB

注意源目录省了 79.8 MB 却只换来二进制省 18.1 MB —— tauri 对嵌入资产做了压缩,
而 node_modules 全是高度可压缩的文本。**别按源目录体积推算二进制收益**,
这份文档最初就是这么推错过一次的。

这个文件钉的是**这条链不许被悄悄接回去**。它不需要 Rust 工具链 —— CI 里
没有任何作业构建 Tauri，所以这层结构检查是唯一会跑的守卫。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_TAURI = _ROOT / "desktop-tauri"
_RENDERER = _ROOT / "electron" / "renderer"

#: 与 build.rs 的 EXCLUDE 保持一致。本文件的 test_denylist_matches_build_rs
#: 会逐条核对两边没有漂移。
_EXCLUDE = [
    "panel/node_modules",
    "panel/src",
    "panel/package.json",
    "panel/package-lock.json",
    "panel/tsconfig.json",
    "panel/tsconfig.node.json",
    "panel/vite.config.ts",
    "panel/DESIGN.md",
    "types",
    "presence_motion.test.js",
]


def _staged_files() -> list[str]:
    """按黑名单复刻 build.rs 的取舍，返回会被嵌入的相对路径。"""
    out = []
    for f in _RENDERER.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(_RENDERER).as_posix()
        if any(rel == e or rel.startswith(e + "/") for e in _EXCLUDE):
            continue
        out.append(rel)
    return out


class TestFrontendDistPointsAtStaging:
    def test_config_uses_the_staging_dir(self) -> None:
        conf = json.loads((_TAURI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        dist = conf["build"]["frontendDist"]
        assert dist == "../frontend", (
            f"frontendDist 是 {dist!r} —— 指回 electron/renderer 的话，" f"panel/node_modules 会重新被嵌进二进制"
        )

    def test_staging_dir_is_gitignored(self) -> None:
        """入库就会变成第二份可编辑的前端 —— 那正是'不复制前端'原则要防的事。"""
        ignore = (_TAURI / ".gitignore").read_text(encoding="utf-8")
        assert re.search(r"^frontend/\s*$", ignore, re.M), "desktop-tauri/frontend/ 没有被 gitignore"

    def test_build_rs_excludes_node_modules(self) -> None:
        rs = (_TAURI / "src-tauri" / "build.rs").read_text(encoding="utf-8")
        assert "panel/node_modules" in rs, "build.rs 不再排除 node_modules —— 68 MB 会回到二进制里"

    def test_denylist_matches_build_rs(self) -> None:
        """本文件的复刻黑名单必须与 build.rs 一致，否则下面几条测的是别的东西。"""
        rs = (_TAURI / "src-tauri" / "build.rs").read_text(encoding="utf-8")
        block = re.search(r"const EXCLUDE: &\[&str\] = &\[(.*?)\];", rs, re.S)
        assert block, "build.rs 里找不到 EXCLUDE 列表"
        in_rs = set(re.findall(r'"([^"]+)"', block.group(1)))
        assert in_rs == set(_EXCLUDE), f"黑名单漂移了：只在一边的有 {in_rs ^ set(_EXCLUDE)}"


class TestStagedSetIsComplete:
    """漏掉一个运行期文件的后果是"只在 Tauri release 构建里坏掉"——CI 不构建
    Tauri，没人会发现。所以这里正面核对：页面引用的每个本地资源都得在暂存集里。
    """

    def test_every_script_index_html_loads_is_staged(self) -> None:
        html = (_RENDERER / "index.html").read_text(encoding="utf-8")
        refs = re.findall(r'<script\s+src="([^"]+)"', html)
        assert refs, "index.html 里一个 <script src> 都没有，解析大概出错了"
        staged = set(_staged_files())
        for r in refs:
            if r.startswith(("http://", "https://", "//")):
                continue
            assert r in staged, f"index.html 加载的 {r} 不在暂存集里 —— Tauri 构建出来会 404"

    def test_panel_dist_entry_is_staged(self) -> None:
        """main.rs 用 WebviewUrl::App("panel/dist/index.html") 打开面板窗口。"""
        assert "panel/dist/index.html" in _staged_files(), "面板入口没被暂存，panel 窗口会 404"

    def test_shaders_are_staged(self) -> None:
        staged = _staged_files()
        assert any(s.startswith("shaders/") for s in staged), "着色器没被暂存，覆盖层会退化到 DOM 兜底"


class TestTheSavingIsReal:
    """自证：上面几条只有在'被排除的东西确实很大'时才有意义。

    node_modules 若已被删掉（比如 CI 的精简检出），这些断言会全绿但毫无内容 ——
    所以这里直接量，量不到就明确跳过而不是假装通过。
    """

    def test_excluding_node_modules_saves_most_of_the_tree(self) -> None:
        nm = _RENDERER / "panel" / "node_modules"
        if not nm.is_dir():
            pytest.skip("panel/node_modules 未安装（跳过体积核对，结构检查仍在上面几条里）")
        total = sum(f.stat().st_size for f in _RENDERER.rglob("*") if f.is_file())
        staged = sum((_RENDERER / r).stat().st_size for r in _staged_files())
        assert staged < total * 0.25, (
            f"暂存后仍占 {staged / total:.0%} —— 黑名单没起作用"
            f"（全树 {total / 1e6:.1f} MB，暂存 {staged / 1e6:.1f} MB）"
        )
