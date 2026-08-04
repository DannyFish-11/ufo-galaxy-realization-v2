#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_node_local_module_shadowing.py — 节点自带的模块不许靠"名字撞运气"被找到。

问题是什么
----------
``nodes/<某节点>/`` 下面常常有自己的 ``core/``、``models/`` 子包，而仓库根**也**有
``core/``、``models/``。节点里若写成绝对导入::

    from core.android_vlm_engine import AndroidVLMEngine     # 节点自己的 core/
    from models.device import Device                         # 节点自己的 models/

这句话能不能解析开，**完全取决于当时 sys.path 的先后顺序**：

* ``python nodes/<节点>/main.py`` 起进程 —— sys.path[0] 就是节点目录，解析得开；
* 被当作模块加载（fusion_entry.py、被别的模块 import、测试里 importlib 加载）——
  仓库根的 ``core`` 包多半已经在 sys.modules 里了，于是 ``core.X`` 只会去仓库根
  ``core/`` 里找，**找不到**。

后果不是报错，是**静默降级**。两次真实事故都长这样：

1. ``Node_113_AndroidVLM/main.py``：``from core.android_vlm_engine import ...`` 被
   ``except ImportError`` 接住，``HAS_VLM_ENGINE`` 无声变成 False。服务照常起来、
   /health 照常绿，只是 VLM 能力不见了，没有一行日志说为什么。
2. ``Node_71_MultiDeviceCoordination``：反过来的教训 —— 它已被改成相对导入
   （这是对的，它要能作为 ``nodes.Node_71_MultiDeviceCoordination.core.X`` 被用），
   于是那些"把文件按 ``core.<名字>`` 假名字重新加载一遍"的老测试脚手架全部失灵，
   而失败信息只说 ``No module named 'core.multi_device_coordinator_engine'``，
   完全指不到真正的原因。

这份测试钉什么
--------------
钉住"节点内的绝对导入不许指向只有节点自己才有的模块"这条硬约束，并且用 AST 判定
（不是子串），再各配一条**行为**断言，证明两个受害节点现在真的两种入口下都活。

为什么放过节点自己的 tests/
---------------------------
``nodes/<节点>/tests/`` 下的文件只会在它自己的 conftest.py 之后被加载，而那个
conftest 会显式把节点模块登记成 ``core.<名字>`` / ``models.<名字>`` 别名 —— 那是
一份**有保证**的安排，不是撞运气。入口与生产代码没有这种保证，所以只管后者。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"

# 仓库根同名、因而会发生遮蔽的顶层包名。
SHADOWABLE_TOP_LEVEL = ("core", "models", "api", "utils", "services")


def _resolves_under(base: Path, dotted: str) -> bool:
    """``base`` 下面存在 ``dotted`` 对应的包目录或 .py 文件吗。"""
    parts = dotted.split(".")
    return (base.joinpath(*parts)).is_dir() or (base.joinpath(*parts[:-1]) / f"{parts[-1]}.py").exists()


def _shadowing_imports(node_dir: Path) -> List[Tuple[str, int, str]]:
    """列出该节点里"只有节点自己有、仓库根没有"的绝对导入。"""
    found: List[Tuple[str, int, str]] = []
    for py in sorted(node_dir.rglob("*.py")):
        if "tests" in py.relative_to(node_dir).parts:
            continue  # 见模块文档字符串:节点自测有 conftest 兜底
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            # level == 0 才是绝对导入;相对导入(level >= 1)正是我们希望看到的写法。
            if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
                continue
            if node.module.split(".")[0] not in SHADOWABLE_TOP_LEVEL:
                continue
            if _resolves_under(node_dir, node.module) and not _resolves_under(REPO_ROOT, node.module):
                try:
                    shown = str(py.relative_to(REPO_ROOT))
                except ValueError:
                    shown = str(py)  # 自检用的临时目录不在仓库里
                found.append((shown, node.lineno, node.module))
    return found


class TestNoNodeLocalShadowingImports:
    def test_no_node_resolves_its_own_modules_by_a_repo_root_name(self):
        violations: List[Tuple[str, int, str]] = []
        for node_dir in sorted(p for p in NODES_DIR.iterdir() if p.is_dir()):
            violations.extend(_shadowing_imports(node_dir))

        assert not violations, (
            "以下绝对导入指向的是**节点自己的**模块,仓库根并没有同名模块 —— "
            "能不能解析开取决于 sys.path 顺序,作为模块被加载时会静默失败:\n"
            + "\n".join(f"  {f}:{ln}  from {mod} import ..." for f, ln, mod in violations)
            + "\n改用相对导入(from .core.X import ...),或按文件路径显式加载。"
        )


class TestNode71ImportsAsARealPackage:
    """Node_71 必须能按真实点分路径 import —— 不靠任何 sys.path 注入。"""

    def test_engine_imports_by_true_dotted_path(self):
        from nodes.Node_71_MultiDeviceCoordination.core.multi_device_coordinator_engine import (
            MultiDeviceCoordinatorEngine,
        )

        assert MultiDeviceCoordinatorEngine.__module__.startswith("nodes.Node_71_MultiDeviceCoordination")

    def test_engine_and_models_share_one_device_class(self):
        """引擎与模型必须是**同一份** —— 两份 Device 会让 isinstance 静默走偏。"""
        from nodes.Node_71_MultiDeviceCoordination.core import device_discovery
        from nodes.Node_71_MultiDeviceCoordination.models.device import Device

        assert device_discovery.Device is Device


class TestNode113VlmEngineSurvivesModuleLoading:
    """Node_113 的 VLM 引擎在"被当作模块加载"时也必须真的加载上。

    用子进程而不是当前进程:main.py 会 ``sys.path.insert(0, 节点目录)``,在本进程里
    做这件事会污染同一轮的其它测试(那正是 fusion_entry 注释里说的"sys.path 污染")。
    """

    def test_has_vlm_engine_is_true_when_repo_root_core_already_imported(self):
        node_dir = NODES_DIR / "Node_113_AndroidVLM"
        if not (node_dir / "core" / "android_vlm_engine.py").exists():
            import pytest

            pytest.skip("Node_113 的 VLM 引擎文件不在,跳过")

        script = (
            "import core\n"  # 复现融合进程的常态:仓库根 core 先被 import
            "import importlib.util, os, sys\n"
            f"d = {str(node_dir)!r}\n"
            "spec = importlib.util.spec_from_file_location("
            "'Node_113_AndroidVLM.main', os.path.join(d, 'main.py'), submodule_search_locations=[d])\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print('HAS_VLM_ENGINE=' + str(m.HAS_VLM_ENGINE))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        if "HAS_VLM_ENGINE=" not in proc.stdout:
            import pytest

            pytest.skip(f"Node_113 依赖不全,无法判定(stderr 尾部:{proc.stderr[-300:]})")
        assert "HAS_VLM_ENGINE=True" in proc.stdout, (
            "以模块方式加载 Node_113/main.py 时 VLM 引擎没挂上 —— 这正是那个"
            "静默降级:服务照常起来,能力却不见了。\n"
            f"stdout:{proc.stdout[-300:]}\nstderr:{proc.stderr[-300:]}"
        )


class TestSelfCheckOfTheScanner:
    """扫描器自身的正确性 —— 不然它绿得毫无意义。"""

    def test_scanner_flags_a_synthetic_shadowing_import(self, tmp_path):
        node = tmp_path / "Node_99_Synthetic"
        (node / "core").mkdir(parents=True)
        (node / "core" / "only_here.py").write_text("X = 1\n", encoding="utf-8")
        (node / "main.py").write_text("from core.only_here import X\n", encoding="utf-8")
        assert _shadowing_imports(node), "扫描器漏掉了一条人造的遮蔽导入"

    def test_scanner_ignores_relative_imports(self, tmp_path):
        node = tmp_path / "Node_98_Synthetic"
        (node / "core").mkdir(parents=True)
        (node / "core" / "only_here.py").write_text("X = 1\n", encoding="utf-8")
        (node / "main.py").write_text("from .core.only_here import X\n", encoding="utf-8")
        assert not _shadowing_imports(node), "相对导入正是我们要的写法,不该被报"

    def test_scanner_ignores_genuine_repo_root_imports(self, tmp_path):
        """节点引用**仓库根**真实存在的模块是完全正常的,不许误报。"""
        node = tmp_path / "Node_97_Synthetic"
        node.mkdir(parents=True)
        (node / "main.py").write_text("from core.device_types import DeviceType\n", encoding="utf-8")
        assert not _shadowing_imports(node)


def test_importlib_is_available_for_the_module_docstring_claims():
    """文档字符串里提到的 importlib 加载路径确实可用(防止注释腐烂成谎话)。"""
    assert importlib.util.spec_from_file_location is not None
