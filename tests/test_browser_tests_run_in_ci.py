"""浏览器行为测试必须真的在 CI 里跑 —— 而且缺浏览器时是红的，不是悄悄跳过。

``electron/renderer/browser-tests/`` 里是 node:test + Playwright 写的行为测试（真开 Chromium，
问屏幕上算出了什么）。它们在 pytest 之外，所以最容易出的事是：文件在、没人跑。
本文件钉住「跑」这件事本身（与 ``tests/test_overlay_motion_wiring.py`` 对 presence_motion
测试的做法一致），而不是测试的内容。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DIR = _ROOT / "electron" / "renderer" / "browser-tests"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _job() -> dict:
    jobs = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]
    assert "browser-behavior" in jobs, "ci.yml 里没有 browser-behavior 作业 —— 浏览器行为测试没人跑"
    return jobs["browser-behavior"]


def test_the_test_files_exist():
    for name in ("harness.js", "overlay.test.js", "panel.test.js", "package.json", "package-lock.json"):
        assert (_DIR / name).is_file(), f"{name} 不见了"


def test_ci_runs_them_with_a_locked_install_and_a_real_browser():
    steps = _job()["steps"]
    runs = [str(s.get("run", "")) for s in steps]
    assert any("npm ci" in r for r in runs), "依赖必须走 npm ci（读 lock），不是 npm install"
    assert any("playwright install" in r and "chromium" in r for r in runs), "CI 里没装 Chromium"
    runner = [s for s in steps if str(s.get("run", "")).strip() in ("npm test", "node --test *.test.js")]
    assert runner, "CI 里没有任何一步在跑这些测试"
    for s in runner:
        assert s.get("working-directory", "").endswith("electron/renderer/browser-tests")


def test_a_missing_browser_fails_in_ci_instead_of_skipping():
    """本地没装浏览器时测试会显式跳过；CI 里必须设这个开关，缺浏览器就红。"""
    steps = _job()["steps"]
    env = {}
    for s in steps:
        if str(s.get("run", "")).strip() == "npm test":
            env = s.get("env", {})
    assert (
        str(env.get("GALAXY_REQUIRE_BROWSER")) == "1"
    ), "没设 GALAXY_REQUIRE_BROWSER=1 —— 缺浏览器会被悄悄跳过，绿线是假的"
    harness = (_DIR / "harness.js").read_text(encoding="utf-8")
    assert "GALAXY_REQUIRE_BROWSER" in harness and "if (REQUIRE) throw err" in harness


def test_the_job_is_bounded():
    """本仓的规矩：测试相关的作业一个都不许无界（挂死时会耗到 runner 被回收）。"""
    assert int(_job()["timeout-minutes"]) <= 30


def test_playwright_is_pinned_exactly_and_locked():
    pkg = json.loads((_DIR / "package.json").read_text(encoding="utf-8"))
    version = pkg["devDependencies"]["playwright"]
    assert version[
        0
    ].isdigit(), f"playwright 版本 {version!r} 不是精确版本 —— 不同日子装出不同的浏览器协议，行为测试会无故变红"
    lock = json.loads((_DIR / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/playwright"]["version"] == version


@pytest.mark.parametrize("name", ["overlay.test.js", "panel.test.js"])
def test_each_test_file_can_skip_only_through_the_harness(name):
    """跳过只能走 harness.launch（它在 CI 里会改成抛错）；别处自己 skip 就绕过了那个开关。"""
    src = (_DIR / name).read_text(encoding="utf-8")
    assert "launch(t)" in src
    assert "t.skip(" not in src and ".skip(" not in src.replace("t.skip", "")
