"""tests/test_node_manifest_consistency.py
===========================================

**八个地方各自记着"有哪些节点"，它们必须说同一件事。**

修复前
------
::

    磁盘 nodes/*/main.py            125
    node_dependencies.json          125   ← 唯一对的那个
    config/unified_config.json      109   ← 5 个幽灵 + 少 21 个
    config/unified_ports.yaml       130   ← 5 个幽灵
    deploy/compose/full.yml         130   ← 5 个幽灵
    registry/device_node_map.yaml    11   ← 4 个幽灵
    config/capabilities.json        116   ← 5 个幽灵 + 7 条测试垃圾
    config/topology.json            102   ← 5 个幽灵 + 少 31 个 + 3 组 id 撞车

「幽灵」= 声称有、磁盘上没有：``Node_37_LinuxDBus`` / ``38_BLE`` / ``41_MQTT`` /
``42_CANbus`` / ``48_Serial``。

这五个协议**不是"没做完"，是做到别处去了**：它们以 ``core/adapters/*_adapter.py``
的形式落在了 AIP 传输层（``ble_adapter`` / ``mqtt_adapter`` / ``canbus_adapter`` /
``serial_adapter`` / ``dbus_adapter``，由 ``galaxy_gateway/bootstrap/lifecycle.py``
逐个 ``register_adapter`` 注册），``core/aip_transport.py`` 还专门给它们定了
``_NARROWBAND`` 传输特性。节点这条路线因此从来没人走 —— 但八份清单里的记录留下了。

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
UNIFIED_PORTS = REPO_ROOT / "config" / "unified_ports.yaml"
CAPABILITIES = REPO_ROOT / "config" / "capabilities.json"
TOPOLOGY = REPO_ROOT / "config" / "topology.json"
TOPOLOGY_GEN = REPO_ROOT / "fusion" / "generate_topology_config.py"


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
    if UNIFIED_PORTS.exists():
        # 第**六**份清单。第一版把它漏了 —— 结果是清掉 compose 里的幽灵之后，
        # scripts/validate_ports.py 立刻报 5 条 "MISSING IN COMPOSE"：端口表还
        # 声称那 5 个节点存在，而 compose 里已经没有它们了。收敛清单时漏掉任何
        # 一份，都会变成另一处的红。
        out["config/unified_ports.yaml"] = set(
            re.findall(r"^    (Node_\d+_\w+):", UNIFIED_PORTS.read_text(encoding="utf-8"), re.M)
        )
    if CAPABILITIES.exists():
        # 第**七**份。前六份收敛完之后它还剩 12 条对不上的：5 个幽灵总线节点，
        # 外加 7 条**测试写进来的垃圾**（``node_x`` / ``node_meta`` / ``node_sink``
        # / ``node_local`` / ``node_42`` / ``node_55`` / ``119``，时间戳挤在
        # 2026-07-27 12:17–12:18 一分钟内）。
        #
        # 后者是 core/capability_manager.py:180 那段注释描述的老问题：
        # ``register_capability()`` 会同步落盘，而默认路径是仓库内的绝对路径，
        # 于是跑一次测试就改写一个 git 跟踪文件。那个洞已经用 GALAXY_CONFIG_DIR
        # 堵上了，但**堵之前漏进来的东西还留在文件里**。
        out["config/capabilities.json"] = {
            c["node_id"]
            for c in json.loads(CAPABILITIES.read_text(encoding="utf-8"))["capabilities"]
            if c.get("node_id")
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


def test_port_registry_covers_every_node_on_disk():
    """``config/unified_ports.yaml`` 是端口权威表，磁盘上每个节点都得在里面。

    少一个的后果不是"没端口"，而是 ``core.port_config.get_node_port()`` 抛
    ``KeyError`` —— 而节点侧 ``resolve_node_port`` 会把它当成"权威表不可用"，
    退到环境变量或代码里的字面量。也就是说：**一个漏登记的节点会静默改用另一套
    端口来源**，而启动器探活敲的仍是权威表算出来的口。那正是本轮修的那类错位。
    """
    missing = sorted(_on_disk() - _declared()["config/unified_ports.yaml"])
    assert not missing, f"端口权威表里没有这些磁盘上的节点：{missing}"


def test_capability_registry_is_a_ledger_not_a_manifest():
    """``config/capabilities.json`` **不要求**覆盖磁盘上全部节点。

    刻意钉这条反向判据，是为了拦住"为了一致性把它也补齐"这个很自然但错误的动作：
    这个文件是 ``register_capability()`` 在运行时落盘的**账本**（每条带
    ``status`` 与 ``last_updated``），不是声明式清单。没注册过的节点不在里面是
    **正常**的；要求它等于磁盘，等于要求所有节点必须先跑起来才算配置正确。

    它唯一该守的是上面那条通用判据：不许声称一个磁盘上没有的节点。
    """
    declared = _declared()["config/capabilities.json"]
    assert declared, "能力账本空了"
    assert declared <= _on_disk(), "账本里有磁盘上不存在的节点 —— 应由上面的幽灵检查报出"


# ── 5. 拓扑产物与它的生成器 ──────────────────────────────────────────────────


def _topology_ids() -> set:
    return {n["id"] for n in json.loads(TOPOLOGY.read_text(encoding="utf-8"))["nodes"]}


def _disk_topology_ids() -> set:
    """磁盘节点名折成拓扑用的短 id：``Node_33_ADB`` → ``Node_33``。"""
    return {"_".join(n.split("_")[:2]) for n in _on_disk()}


def test_topology_matches_disk_exactly():
    """``config/topology.json`` 要和磁盘一一对应。

    这份不是文档，是 ``fusion/topology_manager.TopologyManager`` 读进去做
    **负载均衡路由**的表（``fusion/start_fusion.py:91`` → ``UnifiedOrchestrator``）。
    表里留着 5 个磁盘上不存在的节点，等于让路由器可能把请求派给一个不存在的目标。

    修复前：102 条里 5 个幽灵、缺 31 个真实节点。
    """
    if not TOPOLOGY.exists():
        pytest.skip("config/topology.json 不存在")
    topo, disk = _topology_ids(), _disk_topology_ids()
    assert topo == disk, f"拓扑多出：{sorted(topo - disk)}；拓扑缺少：{sorted(disk - topo)}"


def test_topology_ids_are_unique():
    """一个 id 只能对应一个节点。

    修复前有 3 组撞车，而且撞车的两边连 ``api_url`` 都一样::

        Node_23 → Calendar / Time    都指向 8023
        Node_48 → MediaGen / Serial  都指向 8048
        Node_56 → AgentSwarm/Planning 都指向 8056

    id 是路由的键。两个节点共用一个键，路由器按键查表时只会拿到其中一个，
    另一个**永远选不中**，而且不报错。这条比"数目对得上"更要紧：数目相等
    也可能是两个撞成一个、另一个补进来。
    """
    if not TOPOLOGY.exists():
        pytest.skip("config/topology.json 不存在")
    ids = [n["id"] for n in json.loads(TOPOLOGY.read_text(encoding="utf-8"))["nodes"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"这些 id 被多个节点共用：{dup}"


def test_topology_generator_derives_the_node_list_from_disk():
    """生成器必须**扫盘**取节点，不许再写死一份名单。

    原来它写死了 102 个名字，而紧挨着的那行注释写的是「从实际目录读取」——
    注释是对的，代码没照做。上面两条测试只能证明**当前产物**是对的；只要生成器
    还端着一份手抄名单，下一次重新生成就会把幽灵原样写回去。

    判据是行为的：真的调一次 ``discover_nodes()``，要求它等于磁盘。
    只查"源码里没有硬编码列表"是不够的 —— 换个写法（比如从别的常量拼）照样绕过。
    """
    if not TOPOLOGY_GEN.exists():
        pytest.skip("fusion/generate_topology_config.py 不存在")
    import importlib.util

    spec = importlib.util.spec_from_file_location("_topo_gen", TOPOLOGY_GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert set(mod.discover_nodes()) == _on_disk(), "生成器认的节点和磁盘不一致"
    assert set(mod.NODES) == _on_disk(), "模块级 NODES 不是扫盘得来的"
