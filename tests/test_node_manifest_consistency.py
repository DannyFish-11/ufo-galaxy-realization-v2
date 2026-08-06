"""tests/test_node_manifest_consistency.py
===========================================

**五个地方各自记着"有哪些节点"，它们必须说同一件事。**

修复前
------
::

    磁盘 nodes/*/main.py            125
    node_dependencies.json          125   ← 唯一对的那个
    config/unified_config.json      109   ← 5 个幽灵 + 少 21 个
    deploy/compose/full.yml         130   ← 5 个幽灵
    registry/device_node_map.yaml    11   ← 4 个幽灵

「幽灵」= 声称有、磁盘上没有：``Node_37_LinuxDBus`` / ``38_BLE`` / ``41_MQTT`` /
``42_CANbus`` / ``48_Serial``。五个物理总线节点，设计好了，实现从来没跟上。

它们为什么从"无害"变成"有害"
----------------------------
以前留着不痛不痒：``full.yml`` 里那 5 个 service 只在有人真跑 ``--profile full``
时才崩（``Dockerfile.node`` 是 ``COPY . .``，构建不报错，运行时
``python nodes/Node_37_LinuxDBus/main.py`` 才 file-not-found）；设备映射表里那 4 条
解析出来也没人拿去启动。

**按需激活接通之后就不一样了**：一台 BLE 设备注册进来，会解析到 ``Node_38_BLE``
并真的去启动它 —— 而那个目录不存在。启动失败，日志里多一条谁也看不懂的告警，
设备侧只知道"没能力"。让一条本来就不成立的规则去驱动真实动作，比没有规则更糟。

这份测试钉什么
--------------
1. 任何清单都不许声称一个磁盘上没有的节点（幽灵）；
2. 磁盘上的节点，启动器的配置里必须都有（否则 CLI 根本不认识它）；
3. ``full.yml`` 的 service 数与磁盘一致 —— "130 节点"这个说法从此有据可依。

刻意**不**要求 ``device_node_map.yaml`` 覆盖全部节点：它是设备 → 节点的表，
只有设备型节点该在里面（理由见 ``core/node_activation_policy`` 的模块说明）。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"
UNIFIED_CONFIG = REPO_ROOT / "config" / "unified_config.json"
NODE_DEPS = REPO_ROOT / "node_dependencies.json"
COMPOSE_FULL = REPO_ROOT / "deploy" / "compose" / "full.yml"
DEVICE_MAP = REPO_ROOT / "registry" / "device_node_map.yaml"


def _on_disk() -> set:
    return {d.name for d in NODES_DIR.iterdir() if d.is_dir() and (d / "main.py").exists()}


def _declared():
    """各清单各自声称有哪些节点。"""
    out = {}
    out["config/unified_config.json"] = set(json.loads(UNIFIED_CONFIG.read_text(encoding="utf-8"))["nodes"])
    out["node_dependencies.json"] = set(json.loads(NODE_DEPS.read_text(encoding="utf-8"))["nodes"])
    if COMPOSE_FULL.exists():
        out["deploy/compose/full.yml"] = set(
            re.findall(r"NODE_NAME:\s*(Node_\d+_\w+)", COMPOSE_FULL.read_text(encoding="utf-8"))
        )
    if DEVICE_MAP.exists():
        y = yaml.safe_load(DEVICE_MAP.read_text(encoding="utf-8")) or {}
        out["registry/device_node_map.yaml"] = {
            m["implementation"]["node"] for m in y.get("mappings", []) if m.get("implementation", {}).get("node")
        }
    return out


# ── 1. 不许有幽灵 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("source", sorted(_declared()))
def test_no_manifest_declares_a_node_that_is_not_on_disk(source: str):
    """声称有、磁盘上没有 —— 这类条目现在会驱动真实的启动动作，必须清零。"""
    ghosts = sorted(_declared()[source] - _on_disk())
    assert not ghosts, (
        f"{source} 声称有这些节点，但 nodes/ 下面没有对应目录：{ghosts}\n"
        "按需激活接通之后，这类条目会让运行时真的去启动一个不存在的节点。"
    )


# ── 2. 启动器认识磁盘上每一个节点 ────────────────────────────────────────────


def test_launcher_config_covers_every_node_on_disk():
    """``config/unified_config.json`` 是 CLI 启动器读的表，少一个就等于那个节点不存在。

    修复前它少 21 个 —— ``python main.py nodes status`` 根本列不出它们，
    ``--group all`` 自然也不会碰它们。
    """
    missing = sorted(_on_disk() - _declared()["config/unified_config.json"])
    assert not missing, f"启动器配置里没有这些磁盘上的节点：{missing}"


def test_node_dependencies_covers_every_node_on_disk():
    """``node_dependencies.json`` 是 startup_policy / group 的来源，
    也是 :mod:`core.node_activation_policy` 定档的依据 —— 少一个就落到默认档。"""
    missing = sorted(_on_disk() - _declared()["node_dependencies.json"])
    assert not missing, f"node_dependencies.json 里没有这些磁盘上的节点：{missing}"


# ── 3. "130 节点"这个说法要有据可依 ──────────────────────────────────────────


def test_compose_full_matches_disk_exactly():
    """``full.yml`` 的 node service 与磁盘一一对应。

    文档里到处写着「130 个节点」，而那个 130 正是数 ``full.yml`` 数出来的 ——
    其中 5 个是幽灵。清掉之后这个数字终于是真的。
    """
    if not COMPOSE_FULL.exists():
        pytest.skip("deploy/compose/full.yml 不存在")
    comp, disk = _declared()["deploy/compose/full.yml"], _on_disk()
    assert comp == disk, f"compose 多出：{sorted(comp - disk)}；compose 缺少：{sorted(disk - comp)}"


def test_device_map_is_a_subset_not_a_full_manifest():
    """设备映射表**不该**覆盖全部节点 —— 它只管设备型的。

    钉这条是为了防止有人"为了一致"把一百多个非设备节点也塞进去，造出一堆永远
    匹配不上的规则（理由见 core/node_activation_policy 的模块说明）。
    """
    devmap = _declared().get("registry/device_node_map.yaml", set())
    assert devmap, "设备映射表空了 —— 设备型节点没人认领"
    assert devmap < _on_disk(), "设备映射表覆盖了全部节点 —— 它不是节点清单"


# ── 4. 启动器的组表不许漏掉任何组 ────────────────────────────────────────────


def test_every_group_in_the_config_is_reachable_from_the_cli():
    """配置里出现的每个组，``--group`` 都得能选中。

    补全 21 个节点之后多出 ``development`` / ``extended`` 两个组。忘了加进
    ``NODE_GROUPS`` 的话，``--group development`` 会被 argparse 直接拒掉。
    """
    from launcher.nodes import NODE_GROUPS

    groups = {v.get("group", "core") for v in json.loads(UNIFIED_CONFIG.read_text(encoding="utf-8"))["nodes"].values()}
    missing = sorted(groups - set(NODE_GROUPS))
    assert not missing, f"这些组在配置里存在，却不能用 --group 选中：{missing}"


def test_group_all_does_not_silently_skip_any_group():
    """``--group all`` 必须覆盖**全部**组。

    ``start_all()`` 原来只按一张写死的 priority_order 取组 —— 表里没列到的组会被
    **静默丢掉**：不报错、不提示，那些节点就是不会被碰。补全节点之后多出两个组，
    正好踩中。现在改成"先按优先级排，剩下的接在后面"，新增组不可能再被漏。
    """
    import asyncio

    import launcher.nodes as ln

    seen = []

    class _Recorder(ln.SystemManager):
        def __init__(self):
            pass  # 不碰真实进程

        async def start_group(self, group, wait=True):
            seen.append(group)

    # 先按真实配置跑一遍。
    asyncio.run(_Recorder().start_all())
    assert set(seen) == set(ln.NODES), f"--group all 漏掉了：{sorted(set(ln.NODES) - set(seen))}"

    # 再塞一个 priority_order 里**没有**的组 —— 这才真正测到那条兜底。
    #
    # 只跑上面那一半是不够的：现有的组恰好都写进了 priority_order，把兜底整句删掉
    # 测试照样绿（变异验证当场证明的）。真正要守的是"将来新增一个组也不会被静默
    # 丢掉"，那就必须造一个表里没有的组。
    seen.clear()
    original = ln.NODES
    ln.NODES = dict(original)
    ln.NODES["某个将来才会有的组"] = []
    try:
        asyncio.run(_Recorder().start_all())
    finally:
        ln.NODES = original

    assert "某个将来才会有的组" in seen, (
        "--group all 静默丢掉了一个 priority_order 里没列到的组。"
        "写死的优先级表必须配一条兜底，否则每加一个新组就少启动一批节点，而且不报错。"
    )
