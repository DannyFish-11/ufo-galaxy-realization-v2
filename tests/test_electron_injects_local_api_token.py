#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_electron_injects_local_api_token.py

鉴权默认翻成开启（``core/auth.py::is_auth_enabled``）之后，桌面面板必须还能用。

面板此前一行 ``Authorization`` 都不发（渲染层 ``lib/api.ts`` 与多个 hooks 各自
裸 ``fetch``，主进程另有一批 ``fetch(GATEWAY_BASE + ...)``）。默认一开，这些请求
全部 401 —— 而它们大都裹在 ``try/catch`` 里，用户看到的不是"401"，是"面板某块
空白 / 配置存不上 / 感知没画面"。所以令牌注入是这次改默认的**必要配套**，不是
锦上添花。

这里跑的是 ``electron/main.js`` 里那三个函数的**真身**（把源码切出来喂给 node
执行），不是照着源码抄一遍再断言 —— 后者只要注释里出现同样的字面量就会绿，
判不出实现有没有真的改对。

三条不变量
==========
1. 令牌**只能**发给本机网关。主机不是环回、或端口不是网关端口 → 不带。
   漏了这条，令牌会跟着任意第三方请求出门 —— 那是这台机器的钥匙。
2. 令牌路径必须与 Python 侧 ``core.auth._local_token_path`` **同源**。
   两边各写各的，就是本仓反复修的那类"判据不同源"缺陷，表现成"后端明明好的，
   面板全 401"。
3. 文件在但读不出 ≠ 还没签过，必须留痕。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAIN_JS = os.path.join(_REPO, "electron", "main.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 才能执行 main.js 的真身")


def _extract_helpers() -> str:
    """从 main.js 里切出令牌相关的三个函数（连注释）。

    切不出来就直接失败：说明这段被改名/挪走了，测试必须跟着看一眼，
    而不是悄悄跳过。
    """
    src = open(_MAIN_JS, encoding="utf-8").read()
    start = src.index("// ── 本机 API 令牌 ──")
    end = src.index("// 桌面连续感知")
    block = src[start:end]
    for name in ("localApiTokenPath", "resolveLocalApiToken", "isLocalGatewayUrl", "withLocalAuth"):
        assert f"function {name}(" in block, f"main.js 里找不到 {name}——注入点可能被挪走了"
    return block


def _run_js(body: str, *, data_dir: str, gateway_port: int = 9000, env=None) -> dict:
    """在 node 里执行真实的 helper 源码 + 一段断言脚本，回收 JSON 结果。"""
    harness = (
        "const path = require('path');\n"
        "const fs = require('fs');\n"
        f"const PROJECT_ROOT = {json.dumps(_REPO)};\n"
        f"const GATEWAY_PORT = {gateway_port};\n"
        "const _warns = [];\n"
        "const console = { warn: (...a) => _warns.push(a.join(' ')), log: () => {} };\n"
        + _extract_helpers()
        + "\nconst __out = (() => {\n"
        + body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify({...__out, _warns}));\n"
    )
    run_env = dict(os.environ)
    run_env.pop("GALAXY_API_TOKEN", None)
    run_env.pop("GALAXY_API_TOKENS", None)
    run_env["GALAXY_DATA_DIR"] = data_dir
    run_env.update(env or {})
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, env=run_env, timeout=30)
    assert proc.returncode == 0, f"node 执行失败：{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture
def token_dir(tmp_path):
    (tmp_path / "api_token.json").write_text(json.dumps({"token": "tok-abc123"}), encoding="utf-8")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# 一、令牌只发给本机网关
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://127.0.0.1:9000/api/config", True),
        ("http://localhost:9000/api/v1/panel/feed", True),
        ("ws://127.0.0.1:9000/ws/device/abc", True),
        ("http://[::1]:9000/api/config", True),
        # —— 以下都必须不带 ——
        ("http://127.0.0.1:9231/ipc", False),  # 本机但不是网关端口（IPC 接收端）
        ("http://127.0.0.1/api/config", False),  # 没端口 = 80，不是网关
        ("https://example.com:9000/api/config", False),  # 端口对但主机是外网
        ("https://evil.example/127.0.0.1:9000", False),  # 路径里带环回，骗不过 URL 解析
        ("file:///C:/app/index.html", False),  # 面板本体走 file://
        ("not a url", False),  # 解析不了 → 判不明白时不给
    ],
)
def test_token_goes_only_to_the_local_gateway(token_dir, url, expected):
    out = _run_js(
        f"return {{ match: isLocalGatewayUrl({json.dumps(url)}) }};",
        data_dir=token_dir,
    )
    assert out["match"] is expected


def test_port_is_compared_against_the_resolved_gateway_port(token_dir):
    """端口是判据的一半：网关跑在非默认端口时，9000 就不该再被认作本机网关。

    区分度在这里 —— 如果实现把端口写死成 9000，这条会红。
    """
    out = _run_js(
        "return { on8123: isLocalGatewayUrl('http://127.0.0.1:8123/api/config'),"
        " on9000: isLocalGatewayUrl('http://127.0.0.1:9000/api/config') };",
        data_dir=token_dir,
        gateway_port=8123,
    )
    assert out["on8123"] is True
    assert out["on9000"] is False


def test_header_is_attached_for_gateway_and_absent_otherwise(token_dir):
    out = _run_js(
        "const a = withLocalAuth('http://127.0.0.1:9000/api/config', {});\n"
        "const b = withLocalAuth('https://example.com/x', {});\n"
        "return { gw: (a.headers || {}).Authorization || null,"
        " outside: (b.headers || {}).Authorization || null };",
        data_dir=token_dir,
    )
    assert out["gw"] == "Bearer tok-abc123"
    assert out["outside"] is None


def test_existing_headers_and_options_survive_injection(token_dir):
    """注入不许把调用方原来的 method/body/headers 冲掉。"""
    out = _run_js(
        "const o = withLocalAuth('http://127.0.0.1:9000/api/config',"
        " { method: 'POST', body: 'x', headers: { 'Content-Type': 'application/json' } });\n"
        "return { method: o.method, body: o.body, ct: o.headers['Content-Type'],"
        " auth: o.headers.Authorization };",
        data_dir=token_dir,
    )
    assert out["method"] == "POST"
    assert out["body"] == "x"
    assert out["ct"] == "application/json"
    assert out["auth"] == "Bearer tok-abc123"


# ---------------------------------------------------------------------------
# 二、路径与 Python 侧同源
# ---------------------------------------------------------------------------


def test_token_path_matches_the_python_side(tmp_path, monkeypatch):
    """两边算出来的必须是同一个文件，否则"后端签了、面板读不到"。

    用 monkeypatch 而不是手动 set/pop ``GALAXY_DATA_DIR``：conftest 在**会话级**
    把它指向了一个临时目录做隔离，手动 ``pop`` 会把那层隔离整个拆掉 —— 之后同
    进程里的每个用例都退回仓库里的 ``./data``，于是本地令牌被签进工作树，后面
    任何"应该没有令牌"的用例都变成"有一枚"。这正是本仓修过的那类跨用例污染。
    """
    import importlib

    import core.auth as auth

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    py_path = auth._local_token_path()
    out = _run_js("return { p: localApiTokenPath() };", data_dir=str(tmp_path))
    assert os.path.normpath(out["p"]) == os.path.normpath(py_path)
    importlib.reload(auth)  # 还原模块级状态，别把 reload 过的模块留给下一条


def test_python_signed_token_is_what_js_reads(tmp_path, monkeypatch):
    """端到端一条：Python 签、JS 读，中间不许有翻译损耗。

    同上：环境改动一律走 monkeypatch，用例结束自动还原，不碰 conftest 的隔离。
    """
    import core.auth as auth

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for k in ("GALAXY_API_TOKEN", "GALAXY_API_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    signed = auth.ensure_local_token()

    assert signed
    out = _run_js("return { t: resolveLocalApiToken() };", data_dir=str(tmp_path))
    assert out["t"] == signed


def test_explicit_env_token_wins(tmp_path):
    """显式配置优先级与 Python 侧一致：配了就用配的，不去读自签文件。"""
    (tmp_path / "api_token.json").write_text(json.dumps({"token": "from-file"}), encoding="utf-8")
    out = _run_js(
        "return { t: resolveLocalApiToken() };",
        data_dir=str(tmp_path),
        env={"GALAXY_API_TOKEN": "from-env"},
    )
    assert out["t"] == "from-env"


# ---------------------------------------------------------------------------
# 三、取不到与没有，分得开
# ---------------------------------------------------------------------------


def test_missing_file_is_not_cached_forever(tmp_path):
    """后端签令牌发生在它自己启动时，很可能晚于面板第一次询问。

    第一次读不到就永久记住"没有"，面板会一直 401 到用户重启桌面。
    """
    out = _run_js(
        "const before = resolveLocalApiToken();\n"
        "fs.writeFileSync(localApiTokenPath(), JSON.stringify({ token: 'late-signed' }));\n"
        "const after = resolveLocalApiToken();\n"
        "return { before, after };",
        data_dir=str(tmp_path),
    )
    assert out["before"] is None
    assert out["after"] == "late-signed"


def test_unreadable_token_file_leaves_a_trace(tmp_path):
    """文件在但坏了 ≠ 还没签过。静默当成"没有"，用户只看到面板空白，查不到根因。"""
    (tmp_path / "api_token.json").write_text("{ this is not json", encoding="utf-8")
    out = _run_js("return { t: resolveLocalApiToken() };", data_dir=str(tmp_path))
    assert out["t"] is None
    assert any("读不出" in w for w in out["_warns"]), "读取失败没有留痕"


def test_injection_failure_does_not_swallow_the_request(tmp_path):
    """拿不到令牌时请求要照常发出去（由网关回 401），而不是在这里被吞掉。"""
    (tmp_path / "api_token.json").write_text("{ broken", encoding="utf-8")
    out = _run_js(
        "const o = withLocalAuth('http://127.0.0.1:9000/api/config', { method: 'GET' });\n"
        "return { method: o.method, auth: (o.headers || {}).Authorization || null };",
        data_dir=str(tmp_path),
    )
    assert out["method"] == "GET"
    assert out["auth"] is None


# ---------------------------------------------------------------------------
# 四、两个注入点都在
# ---------------------------------------------------------------------------


def test_both_injection_points_exist():
    """渲染进程与主进程是**两条独立的出口**，各有各的注入点，少一个就漏一半。

    session.webRequest 只拦页面发出的请求；主进程的 ``fetch`` 走 Node 全局
    fetch，根本不经过 session。
    """
    src = open(_MAIN_JS, encoding="utf-8").read()
    # 去掉注释再判，免得"注释里提了一句"就算数。
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    assert "onBeforeSendHeaders" in code, "渲染进程没有注入点"
    assert "resolveLocalApiToken()" in code

    # 主进程里发往网关的 fetch 必须都过 withLocalAuth。
    unguarded = [
        m.group(0) for m in re.finditer(r"fetch\(\s*`\$\{GATEWAY_BASE\}[^`]*`", code) if "/health" not in m.group(0)
    ]
    assert not unguarded, f"主进程仍有裸 fetch 直连网关，鉴权开启后会 401：{unguarded}"
