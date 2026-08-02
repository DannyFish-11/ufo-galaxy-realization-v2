"""``LegacyConnectionManagerAdapter`` 已清退,不许回来。

## 清退的依据

``core/legacy_adapters/connection_manager_adapter.py`` 是 PR-1 时期留的兼容垫片,
自己的文档字符串就写着::

    .. deprecated:: Batch PR-3
        Deprecation level: D1 (SOFT_DEPRECATED)
        Canonical replacement: core.unified.connection_manager.UnifiedConnectionManager
        Removal target: **Batch PR-5**

清退前核实过:**生产侧零消费者**。全仓唯一的非测试引用是
``core/legacy_adapters/__init__.py`` 自己的再导出 —— 也就是说,这个垫片存在的
唯一理由(给旧调用方留 API)已经不成立了,它只是在给一条早已没人走的路继续
挂着招牌。

## 为什么只清退这一个

同包的 ``device_agent_manager_adapter`` **不能一起动**:它被
``core/authority_boundary_classification.py`` 注册成了一个权威面
(``surface_id="legacy_device_agent_manager_adapter"``,并带 module_path),已经接进
治理模型。删它要先改治理分类,那是另一件事,不在这次范围里。

## 顺带记一笔:与"双 WebSocket 栈收敛"的关系

这项工作原本挂在"P3-4 双 WebSocketManager 栈收敛为一套"名下。核实后发现那个
描述**已经过期**:收敛早就发生了 ——

* ``core/unified/connection_manager.py`` (UCM) 是被声明的 canonical 在场真相源;
* ``galaxy_gateway/websocket_handler.py::GatewayWSManager`` 自己的文档就写着它是
  "thin ingress layer",**presence ownership 委托给 UCM**,本地只留
  connection-id → WebSocket 的查找表(网关用临时连接 id,需要这层映射);
* ``core/connection_manager.py`` 管的是**出站**到各服务的心跳/重连/退避
  (httpx),与"哪台设备在线"是两件事 —— 名字像而已,全文只有 2 处提到
  device_id/presence/online。

所以并不存在两套竞争的真相栈,UCM 那条 canonical 声明**是收敛的结果,不是障碍**。
真正剩下的只有这个零消费者垫片,清掉即可。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RETIRED_MODULE = REPO_ROOT / "core" / "legacy_adapters" / "connection_manager_adapter.py"


def test_module_file_is_gone():
    assert not RETIRED_MODULE.exists(), f"{RETIRED_MODULE.relative_to(REPO_ROOT)} 又回来了 —— 它已被清退"


def test_module_is_not_importable():
    """文件不在了还要确认 import 也失败。

    只查文件存在与否是不够的:``__init__.py`` 里若留着别名、或别处新建了同名
    模块,``import`` 仍可能成功,而清退就名存实亡了。
    """
    with pytest.raises(ImportError):
        __import__("core.legacy_adapters.connection_manager_adapter")


def test_package_no_longer_exports_the_adapter():
    """包的 ``__all__`` 与实际属性都不许再有它。"""
    import core.legacy_adapters as legacy_adapters

    assert "LegacyConnectionManagerAdapter" not in getattr(legacy_adapters, "__all__", [])
    assert not hasattr(legacy_adapters, "LegacyConnectionManagerAdapter")


def test_nothing_in_the_repo_references_it():
    """全仓不许再出现这个名字(含测试)。

    用 AST 找 import 与属性访问,不用 grep —— 本文件的文档字符串里如实写着它的
    名字(那是病历),grep 会把自己也算进去。
    """
    offenders: list[str] = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "external"}

    for path in REPO_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "connection_manager_adapter" in node.module:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
                    continue
            if isinstance(node, ast.Import):
                if any("connection_manager_adapter" in a.name for a in node.names):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
                    continue
            if isinstance(node, ast.Name) and node.id == "LegacyConnectionManagerAdapter":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr == "LegacyConnectionManagerAdapter":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert not offenders, "已清退的 LegacyConnectionManagerAdapter 仍被引用:\n" + "\n".join(offenders)


def test_the_canonical_replacement_is_still_there():
    """反面:清退的前提是**替代品还在**。

    没有这条,把 UCM 一起删掉也能让上面全部通过 —— 那不是清退,是拆房子。
    """
    from core.unified.connection_manager import get_unified_connection_manager

    assert get_unified_connection_manager() is not None


def test_the_sibling_adapter_is_untouched():
    """同包的 device_agent_manager_adapter 必须原样保留。

    它被 core/authority_boundary_classification.py 注册成了权威面,删它要先改
    治理分类。这条防止后来者顺手"一起清干净"。
    """
    import core.legacy_adapters as legacy_adapters

    assert hasattr(legacy_adapters, "LegacyDeviceAgentManagerAdapter")
