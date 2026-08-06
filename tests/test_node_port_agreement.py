"""tests/test_node_port_agreement.py
====================================

**启动器敲哪个口,节点就得绑哪个口。**

这条不成立时会发生什么
----------------------
不是"少一条告警"那么轻。实测(把节点按启动器的真实调用方式逐个拉起来,读节点自己
打印的 ``Uvicorn running on``)发现 monitoring 组三个节点端口整体错位一位::

    Node_65_LoggerCentral   启动器敲 8064   节点绑 8065
    Node_67_HealthMonitor   启动器敲 8066   节点绑 8067
    Node_68_Security        启动器敲 8067   节点绑 8068

错位之后端口互相串了门:启动器敲 8067 拿到 200,把它记成 **Security 已就绪** ——
而 8067 上跑的其实是 HealthMonitor。三个节点明明都活着,报告说 ``成功: 1/3``,
而那个"1"还认错了人。**如果 Security 真的挂了,这套机制会告诉你它是好的。**

容器里同样致命:``deploy/compose/full.yml`` 给 node-65 映射 ``8064:8064``,
``Dockerfile.node`` 的 HEALTHCHECK 也 curl ``localhost:8064``,而节点绑 8065 ——
健康检查永远不会通过,容器一直 unhealthy,而别的服务还
``depends_on: condition: service_healthy``。

为什么是静态判据
----------------
真跑 125 个节点要十几分钟,进不了 CI。这里退而求其次但仍然有区分度:凡是把端口
**写死成字面量**的节点,那个字面量必须等于权威值。走 ``resolve_node_port`` /
环境变量的节点不受这条约束 —— 它们按构造就一致。

三条一起才够
------------
只钉节点侧不够。启动器传什么、compose 传什么,是同一件事的另外两半:

* 启动器必须同时传 ``PORT`` 与 ``NODE_PORT`` —— 两条部署路径历史上各用一个名字,
  读 ``NODE_PORT`` 的节点在容器里对、在原生启动器下错。
* compose 的 ``NODE_PORT`` 必须等于权威值 —— 否则容器健康检查敲空气。
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Tuple

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"
COMPOSE_FULL = REPO_ROOT / "deploy" / "compose" / "full.yml"
LAUNCHER_NODES = REPO_ROOT / "launcher" / "nodes.py"

# uvicorn.run(app, host=..., port=8065)  /  uvicorn.run("main:app", ..., port=8065,)
_UVICORN_PORT_LITERAL = re.compile(r"uvicorn\.run\((?:[^()]|\([^()]*\))*?\bport\s*=\s*(\d{4})\b", re.S)


def _authority(node_name: str):
    from core.port_config import get_node_port

    try:
        return get_node_port(node_name)
    except Exception:
        return None


def _nodes_on_disk() -> List[str]:
    return sorted(d.name for d in NODES_DIR.iterdir() if d.is_dir() and (d / "main.py").exists())


def _hardcoded_ports() -> Dict[str, List[str]]:
    """节点名 → 它写死在 uvicorn.run 里的端口字面量(可能没有)。"""
    out: Dict[str, List[str]] = {}
    for name in _nodes_on_disk():
        src = (NODES_DIR / name / "main.py").read_text(encoding="utf-8", errors="replace")
        lits = _UVICORN_PORT_LITERAL.findall(src)
        if lits:
            out[name] = sorted(set(lits))
    return out


# ── 1. 节点侧:写死的端口必须等于权威值 ──────────────────────────────────────


def test_hardcoded_node_ports_match_the_authority():
    """凡是把端口写死的节点,那个数必须等于 config/unified_ports.yaml 说的数。

    这是修复前 8 个节点违反的那一条。修法有两种,都算通过:改字面量,或者改成
    走 ``nodes/common/node_port.resolve_node_port``(推荐,见该模块的说明)。
    """
    offenders: List[Tuple[str, str, int]] = []
    for name, lits in _hardcoded_ports().items():
        auth = _authority(name)
        if auth is None:
            continue  # 权威表里没有它 —— 归 test_every_node_on_disk_has_an_authoritative_port 管
        if str(auth) not in lits:
            offenders.append((name, "/".join(lits), auth))

    assert not offenders, "这些节点写死的端口与权威值不符(启动器会敲空气,容器健康检查会永远失败):\n" + "\n".join(
        f"  {n:<34} 写死 {lit}  权威 {auth}" for n, lit, auth in offenders
    )


def test_every_node_on_disk_has_an_authoritative_port():
    """磁盘上每个节点都得在权威表里有一条 —— 否则启动器不知道去敲哪儿。"""
    missing = [n for n in _nodes_on_disk() if _authority(n) is None]
    assert not missing, f"这些节点在 config/unified_ports.yaml 里没有端口:{missing}"


def test_authoritative_ports_do_not_collide():
    """两个节点不能分到同一个口 —— 否则先起来的那个会把另一个的健康检查骗过去。"""
    seen: Dict[int, List[str]] = {}
    for n in _nodes_on_disk():
        p = _authority(n)
        if p is not None:
            seen.setdefault(p, []).append(n)
    dupes = {p: v for p, v in seen.items() if len(v) > 1}
    assert not dupes, f"端口冲突:{dupes}"


# ── 2. 启动器侧:两套环境变量名都要传 ────────────────────────────────────────


@pytest.mark.parametrize("var", ["PORT", "NODE_PORT"])
def test_launcher_exports_both_port_env_names(var: str):
    """``launcher/nodes.py`` 起子进程时两个名字都要设。

    历史上它只设 ``PORT``,而 ``deploy/compose/full.yml`` 与 ``Dockerfile.node``
    设的是 ``NODE_PORT``。于是读 ``NODE_PORT`` 的节点(Node_23_Time、
    Node_80_MemorySystem)**在容器里对、在原生启动器下错** —— 取不到就退回代码里
    写死的字面量,而启动器敲的是权威值。
    """
    src = LAUNCHER_NODES.read_text(encoding="utf-8")
    assert re.search(rf'env\[["\']{var}["\']\]\s*=', src), f"launcher/nodes.py 没有给子进程设置 {var}"


# ── 3. 容器侧:compose 传的口必须等于权威值 ──────────────────────────────────


def test_compose_node_port_matches_the_authority():
    """``full.yml`` 每个 node service 的 ``NODE_PORT`` 都要等于权威值。

    它同时决定三件事:容器内进程绑哪个口、``ports:`` 映射哪个口、
    ``Dockerfile.node`` 的 HEALTHCHECK curl 哪个口。错一个,容器就永远 unhealthy。
    """
    if not COMPOSE_FULL.exists():
        pytest.skip("deploy/compose/full.yml 不存在")

    src = COMPOSE_FULL.read_text(encoding="utf-8")
    offenders = []
    for m in re.finditer(r"NODE_NAME:\s*(Node_\d+_\w+)\s*\n\s*NODE_PORT:\s*\"?(\d+)\"?", src):
        name, port = m.group(1), int(m.group(2))
        auth = _authority(name)
        if auth is not None and auth != port:
            offenders.append((name, port, auth))

    assert not offenders, "compose 的 NODE_PORT 与权威值不符:\n" + "\n".join(
        f"  {n:<34} compose {p}  权威 {a}" for n, p, a in offenders
    )
