"""tests/test_port_surface_aliases.py
======================================

**同一个服务面在不同部署形态下端口相同，那不是冲突。**

修复前
------
``config/unified_ports.yaml`` 里 ``unified_launcher`` 与 ``gateway`` 都写着 9000，
``scripts/validate_ports.py`` 一律判成::

    ✗ PORT CONFLICT: port 9000 assigned to both 'infra:unified_launcher'
                     and 'infra:gateway'

于是它在 ``main`` 上长期红着。而这两条其实是**同一份 API 网关表面**的两条部署路径，
任何一次部署只会有其中一条在跑：

* 桌面单进程 ``python main.py`` → ``launcher/services.py:589`` 起的 uvicorn
  （它自己的报错信息里就自称"API 网关端口"）；
* 容器 → ``galaxy-gateway`` 容器 ``ports: "9000:9000"`` 发布到宿主；
  ``galaxy`` 容器只 ``expose`` 不映射，在自己的网络命名空间里。

两条路径下宿主的 9000 上都只有一个进程。真会撞的只有"手动同时起两个"，而
``launcher/services.py:599`` 早就有一次预绑定自检把它变成一句能照做的话。

为什么不是加一条豁免了事
------------------------
豁免只是让校验器闭嘴，"这两个是同一个面"这件事仍然只存在于两行中文描述里 ——
下一个人看到还是得把整条部署链重走一遍才敢说它不是缺陷。

改成在 yaml 里显式声明 ``same_surface_as``，判据反而**更强**：校验器不仅不再误报，
还会要求两者端口**必须相等**。将来谁把其中一个挪走而忘了另一个，立刻红 ——
原来那条"端口不许重复"根本管不了这个。
"""

from __future__ import annotations

import pathlib
import sys

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PORTS_YAML = REPO_ROOT / "config" / "unified_ports.yaml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture(scope="module")
def vp():
    import validate_ports

    return validate_ports


@pytest.fixture(scope="module")
def ports_yaml():
    return yaml.safe_load(PORTS_YAML.read_text(encoding="utf-8")) or {}


# ── 1. 声明存在且被读出来 ────────────────────────────────────────────────────


def test_gateway_declares_the_shared_surface(vp, ports_yaml):
    """``gateway`` 必须显式声明它和 ``unified_launcher`` 是同一个面。

    删掉这条声明，校验器就会回到 PORT CONFLICT 误报 —— 变异验证过。
    """
    aliases = vp.extract_surface_aliases(ports_yaml)

    assert aliases.get("gateway") == "unified_launcher", f"没读到那条声明:{aliases}"


# ── 2. 声明让误报消失 ────────────────────────────────────────────────────────


def test_declared_surface_is_not_reported_as_a_conflict(vp, ports_yaml):
    node_ports = vp.extract_node_ports(ports_yaml)
    infra_ports = vp.extract_infra_ports(ports_yaml)
    aliases = vp.extract_surface_aliases(ports_yaml)

    errors = vp.check_port_uniqueness(node_ports, infra_ports, aliases)

    assert not [e for e in errors if "9000" in e], f"声明过的同一服务面仍被判成冲突:{errors}"


def test_without_the_declaration_it_is_still_reported(vp, ports_yaml):
    """不传 aliases 时照样报 —— 说明豁免是**声明驱动**的，不是把检查删了。

    少了这条，上一条测试就无法区分"声明生效了"和"冲突检查整个失效了"。
    """
    node_ports = vp.extract_node_ports(ports_yaml)
    infra_ports = vp.extract_infra_ports(ports_yaml)

    errors = vp.check_port_uniqueness(node_ports, infra_ports, aliases=None)

    assert [e for e in errors if "9000" in e], "去掉声明之后冲突检查也不响了 —— 那是检查坏了"


# ── 3. 声明本身要被校验 ──────────────────────────────────────────────────────


def test_declared_surfaces_must_share_the_same_port(vp):
    """这是把声明变成判据的那一半:端口不一致就是声明在说谎。"""
    errors = vp.check_surface_aliases({"gateway": 9001, "unified_launcher": 9000}, {"gateway": "unified_launcher"})

    assert errors and "MISMATCH" in errors[0], f"端口不一致却没报:{errors}"


def test_declaring_a_nonexistent_target_is_an_error(vp):
    """指向一个不存在的服务 —— 那是笔误，不能静默通过。"""
    errors = vp.check_surface_aliases({"gateway": 9000}, {"gateway": "根本没有这个服务"})

    assert errors and "SURFACE ALIAS" in errors[0]


def test_the_real_config_passes_both_checks(vp, ports_yaml):
    """仓库里当前这份配置必须自洽。"""
    infra_ports = vp.extract_infra_ports(ports_yaml)
    aliases = vp.extract_surface_aliases(ports_yaml)

    assert not vp.check_surface_aliases(infra_ports, aliases)
