"""core/gateway_tls.py — 网关此刻是不是在说 TLS。**只这一处判定。**

为什么单独一个文件
==================
"网关开没开 TLS" 这件事有两类读者:

* **起服务的**(``galaxy_gateway/app.py``) —— 决定 uvicorn 带不带证书;
* **给设备发地址的**(``core/agent_card.build_candidates``、
  ``TailscaleManager.get_connection_url``) —— 决定写 ``ws://`` 还是 ``wss://``。

这两边原先各判各的,而且判出了相反的结论:服务端默认不开 TLS(没配证书就明文),
tailnet 那条候选地址却写死了 ``wss://``。结果是**客户端拨 TLS、服务端说明文,
握手必然失败** —— 一个语法完全正确、却永远连不上的地址,还被一条测试钉住了
("两条路统一成 wss")。

``wss://`` 到一个裸 IP 本来也没有可行的实现路径:公共 CA 不给 IP 发证书,
Tailscale/headscale 的证书是发给 MagicDNS 名的。tailnet 内的加密与身份由
WireGuard 负责,在它里面再套一层拿不到可信证书的 TLS,只会把路堵死。

所以规则只有一条:**地址的协议跟着服务端走。** 配了证书就 ``wss``,没配就 ``ws``。
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


def tls_paths() -> Optional[Tuple[str, str]]:
    """配了 TLS 就返回 ``(cert, key)``,否则 ``None``。

    两个都得有才算开 —— 只配了一半时服务端按明文起,这里也必须报"没开",
    否则又回到"两边判出相反结论"。
    """
    cert = os.getenv("GALAXY_TLS_CERT", "").strip()
    key = os.getenv("GALAXY_TLS_KEY", "").strip()
    if cert and key:
        return cert, key
    return None


def ws_scheme() -> str:
    """设备连网关该用的 WebSocket 协议:``"wss"`` 或 ``"ws"``。"""
    return "wss" if tls_paths() else "ws"
