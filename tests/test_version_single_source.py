"""tests/test_version_single_source.py — 版本号只有一个。

同一个系统曾经报出过五个版本号：
* 启动横幅和 ``--version``：v2.3.21
* ``core`` / ``galaxy_gateway`` 的 ``__version__``：3.0.0
* ``/api/v1/system/status``：2.0.0
* 镜像标签：2.3.23
* README：v10.0

现在唯一来源是 ``core/version.py``。Python 代码直接 import 它；
取不了 Python 常量的地方（Dockerfile 的 LABEL、启动脚本横幅、npm 包、README）由本文件逐一核对。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.version import GALAXY_VERSION, __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_the_version_is_a_plain_semver():
    assert _SEMVER.match(__version__), __version__
    assert GALAXY_VERSION == f"v{__version__}"


def test_every_python_surface_reports_the_same_version():
    import core
    import galaxy_gateway
    from core.ascii_art import GALAXY_VERSION as banner_version

    assert core.__version__ == __version__
    assert galaxy_gateway.__version__ == __version__
    assert banner_version == GALAXY_VERSION


@pytest.mark.parametrize(
    "path",
    ["core/routes/system.py", "galaxy_gateway/app.py", "galaxy_gateway/routes/health.py", "launcher/services.py"],
)
def test_no_python_surface_hardcodes_a_version_literal(path):
    """接口与启动总结卡曾各写一份（2.0.0 / 3.0.0 / 2.0 / v2.3.21）—— 现在只许引用常量。"""
    src = (REPO_ROOT / path).read_text(encoding="utf-8")
    offenders = re.findall(r'(?:"version":\s*|version=)"v?\d+\.\d+(?:\.\d+)?"', src)
    offenders += re.findall(r'"Galaxy L4 · v\d+\.\d+\.\d+"', src)
    assert not offenders, f"{path} 写死了版本号，改为引用 core.version: {offenders}"


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.agentcpm"])
def test_image_labels_match(dockerfile):
    src = (REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    labels = re.findall(r'LABEL version="([^"]+)"', src)
    assert labels == [__version__], f"{dockerfile} 的镜像标签 {labels} ≠ {__version__}"


@pytest.mark.parametrize("script", ["deploy/scripts/start_unified.sh", "installer/start_galaxy.bat"])
def test_startup_script_banners_match(script):
    src = (REPO_ROOT / script).read_text(encoding="utf-8")
    shown = set(re.findall(r"Intelligence System\s+(v\d+\.\d+\.\d+)", src))
    assert shown == {GALAXY_VERSION}, f"{script} 横幅里的版本 {shown} ≠ {GALAXY_VERSION}"


@pytest.mark.parametrize(
    "package",
    ["package.json", "electron/package.json", "electron/renderer/panel/package.json"],
)
def test_npm_packages_match(package):
    assert json.loads((REPO_ROOT / package).read_text(encoding="utf-8"))["version"] == __version__


def test_readme_states_the_same_version():
    head = "\n".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:6])
    assert GALAXY_VERSION in head, f"README 抬头应写 {GALAXY_VERSION}"
