"""core/net_bind.py — 局域网发现类 socket 该绑在哪个接口上。

要解决什么
----------
CodeQL 的 ``py/bind-socket-all-network-interfaces`` 在本仓报了 5 处
``bind("0.0.0.0", …)``。逐条看下来,它们**都不是笔误**:

* ``core/adapters/udp_adapter.py`` —— 带 ``SO_BROADCAST`` 的局域网发现监听。
  广播包只会送到绑了通配地址的 socket,绑具体 IP 就收不到,功能直接没了。
* ``galaxy_gateway/p2p_connector.py`` —— STUN 客户端。要让 NAT 看到真实的
  出口映射,本地端口必须对所有接口开着等回包。
* ``nodes/Node_71_MultiDeviceCoordination`` 的两处 —— 同类的设备发现。

也就是说"改成 127.0.0.1"不是修复,是把跨设备发现关掉 —— 而跨设备正是这套系统
存在的理由。

那为什么还要这个模块
--------------------
因为风险是真的,只是形状不同:**绑 0.0.0.0 的后果取决于这台机器接在什么网络上**。
在家里的路由器后面,这就是设计意图;而同一份代码跑在咖啡馆 Wi-Fi、或者一台带公网
IP 的云主机上,发现端口就对整个互联网开着了。代码本身分辨不了这两种情形,
**只有部署的人知道**。

所以这里做的不是"消除风险",而是把一个**隐式的、写死在源码里的决定**变成一个
显式的、部署时可以改的决定:

    GALAXY_DISCOVERY_BIND_HOST=192.168.1.50   # 只在这块网卡上做发现

默认仍然是 ``0.0.0.0`` —— 换成别的默认值会让绝大多数用户的设备发现在升级后
悄悄失效,那种"为了安全指标好看而弄坏功能"的改动比不改更糟。

诚实说明:这不会让 CodeQL 那 5 条消失
------------------------------------
静态分析看到的仍然是一个可能为 ``"0.0.0.0"`` 的值流进 ``bind()``。这是预期的 ——
本模块的目的是让这个选择**有名字、有出处、能被改**,而不是把告警藏起来。
告警的处置结论记在 ``config/codeql_findings_ledger.json`` 里。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("Galaxy.Net.Bind")

__all__ = ["discovery_bind_host", "DISCOVERY_BIND_ENV"]

#: 部署级开关。留空或不设 → ``0.0.0.0``。
DISCOVERY_BIND_ENV = "GALAXY_DISCOVERY_BIND_HOST"

_DEFAULT = "0.0.0.0"


def discovery_bind_host(default: str = _DEFAULT) -> str:
    """返回发现类 socket 应当绑定的地址。

    ``default`` 允许调用方表达"这一处即使没配也不该用 0.0.0.0",目前没有这样的
    调用方,但留着比事后再加一个平行开关好。

    取值被 ``strip()`` 之后为空串时按未配置处理 —— 环境变量里一个手滑的空格
    不应该把发现绑到一个不存在的地址上。
    """
    raw = os.getenv(DISCOVERY_BIND_ENV, "")
    host = str(raw).strip()
    if not host:
        return default
    if host != default:
        # 只在**偏离默认**时说话。每次启动都打一行"绑了 0.0.0.0"是噪声,
        # 而"这台机器上发现被限定在某块网卡"是运维需要一眼看到的事实。
        logger.info("发现类 socket 绑定地址由 %s 指定为 %s(默认 %s)", DISCOVERY_BIND_ENV, host, default)
    return host
