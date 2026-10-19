"""节点缺东西（设备 / Key / 命令）时照实说没执行 —— 不「模拟执行」再回 ``success: True``。

全面排查第 7 轮：ADB（没连手机）、OctoPrint（没配 Key）、GitHubFlow（没配 Token / 没配生成模型的 Key）都会模拟
一个成功；没有任何调用方读 ``mock`` 那一位，看的都是 ``success``。最糟的一处：配了 ``GITHUB_TOKEN`` 却没配
``GEMINI_API_KEY`` 时，「审查 PR」把一段写死的「✅ 代码审查通过……建议合并」当评论发到真的 PR 上。

模拟只在显式打开时才有（``USE_MOCK_DRIVERS=true``，启动器原样传给每个节点，见 ``nodes/common/mock_drivers.py``）。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from nodes.common.mock_drivers import NotConfigured

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(node: str):
    spec = importlib.util.spec_from_file_location(f"_{node}_main", REPO_ROOT / "nodes" / node / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def real_drivers(monkeypatch):
    monkeypatch.delenv("USE_MOCK_DRIVERS", raising=False)


def test_adb_without_a_phone_says_nothing_was_done(real_drivers):
    adb = _load("Node_33_ADB").ADBController("adb")
    out = asyncio.run(adb.execute("tap", {"x": 10, "y": 20}))
    assert out["success"] is False and "安卓设备" in out["error"]


def test_adb_without_the_adb_command_says_so(real_drivers):
    adb = _load("Node_33_ADB").ADBController("adb")
    adb.degrade_reason = "adb binary not found on this host"
    out = asyncio.run(adb.execute("tap", {"x": 10, "y": 20}))
    assert out["success"] is False and "adb binary not found" in out["error"]


def test_octoprint_without_a_key_does_not_start_a_print(real_drivers):
    printer = _load("Node_49_OctoPrint").OctoPrintController("http://localhost:5000", "")
    out = asyncio.run(printer.execute("print_start", {"filename": "a.gcode"}))
    assert out["success"] is False and "OCTOPRINT_API_KEY" in out["error"]


def test_github_without_a_token_does_not_hand_back_a_made_up_pr(real_drivers, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mod = _load("Node_106_GitHubFlow")
    flow = mod.GitHubFlow()
    with pytest.raises(NotConfigured, match="GITHUB_TOKEN"):
        asyncio.run(flow.github.create_pull_request("o/r", "t", "b", "feature/x"))
    req = mod.CreatePRRequest(repo="o/r", title="t", head="feature/x")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(mod.create_pr(req))
    assert caught.value.status_code == 503 and "GITHUB_TOKEN" in caught.value.detail


def test_a_pr_is_never_given_a_made_up_review(real_drivers, monkeypatch):
    """有 Token、没有生成模型的 Key：不能把一段写死的「审查通过，建议合并」发到真的 PR 上。"""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    flow = _load("Node_106_GitHubFlow").GitHubFlow(github_token="ghp_test")
    posted = []

    async def fake_request(method, endpoint, data=None):
        if method == "POST":
            posted.append((endpoint, data))
        return {"number": 7, "title": "改一下", "body": "说明"}

    monkeypatch.setattr(flow.github, "_request", fake_request)
    with pytest.raises(NotConfigured, match="GEMINI_API_KEY"):
        asyncio.run(flow.review_pull_request("o/r", 7))
    assert posted == [], f"发出去了: {posted}"


def test_mocks_are_still_there_when_asked_for(monkeypatch):
    monkeypatch.setenv("USE_MOCK_DRIVERS", "true")
    out = asyncio.run(_load("Node_33_ADB").ADBController("adb").execute("tap", {"x": 1, "y": 1}))
    assert out["success"] is True and out["mock"] is True
