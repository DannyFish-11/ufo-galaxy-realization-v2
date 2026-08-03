"""tests/test_node_screenshot_paths.py — 截图落盘路径不能由请求方随便指定。

背景
----
``nodes/Node_34_Scrcpy`` 的 ``/screenshot`` 此前是::

    output_path = request.output_path or tempfile.mktemp(suffix=".png")
    ...
    with open(output_path, "wb") as f: f.write(...)

两个问题叠在同一行上:

1. ``tempfile.mktemp`` 只返回路径、并不创建文件。"拿到路径"与"写进去"之间的窗口
   足以让同机的其他用户抢先在那里放一个符号链接,把**设备屏幕截图**引到别处。
   这条是 CodeQL 的 ``py/insecure-temporary-file`` 报出来的。
2. ``output_path`` 直接来自请求体,而本节点 ``uvicorn.run(host="0.0.0.0")`` ——
   **局域网内谁都能 POST**。也就是说这是一个通过 HTTP 暴露的任意文件写入原语。
   **CodeQL 没有报这一条**;它是在修第 1 条时顺带看见的。

修法不是取消"自己命名"这个能力,而是把它约束成"在指定目录里命名"。

这份测试钉什么
--------------
钉行为:各种越界写法都必须落回目录内(或被拒),以及没给名字时用的是**会创建文件**
的 mkstemp 而不是只给路径的 mktemp。
"""

from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

SOURCE = Path(__file__).resolve().parent.parent / "nodes" / "Node_34_Scrcpy" / "main.py"


@pytest.fixture
def resolve(tmp_path, monkeypatch):
    """把 ``_resolve_output_path`` 抠出来单独跑。

    不 import 整个节点模块:它在导入期会去找 adb、建 FastAPI 应用、读环境 ——
    那些与本测试要验的东西无关,却会让这份测试在没装 adb 的机器上变成"跳过"。
    一份会因为无关依赖而跳过的安全测试,和没有这份测试没区别。
    """
    monkeypatch.setenv("GALAXY_SCREENSHOT_DIR", str(tmp_path / "shots"))
    src = SOURCE.read_text(encoding="utf-8")
    snippet = src[src.index("SCREENSHOT_DIR = ") : src.index('@app.post("/screenshot")')]
    ns: dict = {
        "os": os,
        "Path": Path,
        "tempfile": tempfile,
        "Optional": __import__("typing").Optional,
        "HTTPException": HTTPException,
    }
    exec(compile(snippet, str(SOURCE), "exec"), ns)  # noqa: S102 — 受控片段,来源是本仓源码
    return ns["_resolve_output_path"], Path(ns["SCREENSHOT_DIR"])


class TestPathContainment:
    @pytest.mark.parametrize(
        "requested",
        [
            "../../../../etc/cron.d/payload",
            "/etc/passwd",
            "../../.bashrc",
            "sub/../../../escape.png",
            "....//....//x.png",
        ],
    )
    def test_escape_attempts_stay_inside(self, resolve, requested):
        resolve_fn, base = resolve
        try:
            out = Path(resolve_fn(requested))
        except HTTPException as exc:
            assert exc.status_code == 400
            return
        assert out.parent == base.resolve(), f"{requested!r} 逃到了 {out}"

    def test_plain_name_is_accepted(self, resolve):
        resolve_fn, base = resolve
        assert Path(resolve_fn("shot.png")).parent == base.resolve()

    def test_directory_is_owner_only(self, resolve):
        resolve_fn, base = resolve
        resolve_fn("shot.png")
        assert base.is_dir()
        assert os.stat(base).st_mode & 0o777 == 0o700, "截图是屏幕内容,同机其他用户不该能列目录"


class TestDefaultPathIsCreatedAtomically:
    def test_default_creates_the_file(self, resolve):
        """没给名字时必须**已经把文件建出来**。

        这正是 mkstemp 与 mktemp 的差别:后者返回一个还不存在的路径,
        于是别人有机会在那个位置先放点东西。
        """
        resolve_fn, base = resolve
        path = Path(resolve_fn(None))
        assert path.is_file(), "默认路径上没有文件 —— 说明用回了只给路径的 mktemp"
        assert path.parent == base.resolve()

    def test_default_file_is_owner_only(self, resolve):
        resolve_fn, _ = resolve
        assert os.stat(resolve_fn(None)).st_mode & 0o777 == 0o600

    def test_two_calls_do_not_collide(self, resolve):
        resolve_fn, _ = resolve
        assert resolve_fn(None) != resolve_fn(None)


class TestSourceGuards:
    """mktemp 不许回来 —— 这两个节点的截图路径都走过一遍这个坑。"""

    @pytest.mark.parametrize(
        "rel",
        ["nodes/Node_34_Scrcpy/main.py", "nodes/Node_124_LinuxDesktopAuto/main.py"],
    )
    def test_no_mktemp_calls(self, rel):
        path = Path(__file__).resolve().parent.parent / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = [
            f"line {n.lineno}"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "mktemp"
        ]
        assert not bad, f"{rel} 里又出现了 tempfile.mktemp: {', '.join(bad)}"
