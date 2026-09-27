"""core/device_onboarding/gateway_address.py — "让那台设备来连哪个地址"。

配对命令、远程安装都要拼这个地址。放在这里而不是 ``agent_tools`` 里:接入路径
(``join_paths``)也要用它,而路径在工具层**下面** —— 下层去 import 上层就反了。
"""

from __future__ import annotations

from typing import Any


def gateway_http_base(card: Any) -> str:
    """配对命令里的主脑地址:局域网优先(新电脑多半还没进自建内网),其次名片里的其他路。"""
    cands = sorted(
        getattr(card, "candidates", None) or [], key=lambda c: (c.get("kind") != "lan", c.get("priority", 99))
    )
    for c in cands:
        url = str(c.get("url") or "")
        if "/ws/device/" in url:
            base = url.split("/ws/device/", 1)[0]
            return base.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    try:
        from core.electron_launch_guard import resolve_gateway_port

        port = resolve_gateway_port()
    except Exception:  # noqa: BLE001
        port = 0
    return f"http://<主脑电脑的地址>:{port or '<端口>'}"
