"""launcher/tailnet_startup.py — 桌面启动器里「电脑自己入网 + 局域网可被发现」这两件事。

为什么在启动器里再做一遍
========================
网关的 lifespan(``galaxy_gateway/bootstrap/lifecycle.py``)启动时会让这台电脑自己加入自建
tailnet、并在局域网发布 ``_galaxy._tcp``。但**桌面版由启动器自己建 FastAPI 应用**,
只把 ``/ws/device/{id}`` 挂上去,**不跑那个 lifespan** —— 于是这两步在桌面版里从来没发生过:
手表配对拿到了钥匙、进了网,电脑自己却不在网里;同一 Wi-Fi 下的手机/手表也广播不到。

两处共用 ``core.tailnet_self_join.autojoin_at_startup`` 和
``galaxy_gateway.mdns_announcer.start_lan_announcer``,这里只管桌面版需要的那层:
记住结果、给启动横幅一句诚实的话、停机时收掉广播。

放在独立文件里是因为 ``launcher/services.py`` 有行数预算,不该为这个再涨。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Launcher.Tailnet")

#: 横幅明细的一行:(名称, 内容, 状态)
Detail = Tuple[str, str, str]


class TailnetStartup:
    def __init__(self, web_ui_port: int):
        self.web_ui_port = web_ui_port
        #: ``ensure_joined`` 的结果;自动入网关着、或没来得及做时为 ``None``
        self.self_join: Optional[Dict[str, Any]] = None
        self._mdns: Any = None

    async def autojoin(self) -> None:
        """配了 headscale 而这台电脑还没入网时,先自己入网。没入成不抛、不挡启动。"""
        try:
            from core.tailnet_self_join import autojoin_at_startup

            self.self_join = await autojoin_at_startup()
        except Exception as exc:  # noqa: BLE001 — 入不了网不挡启动,横幅会如实说
            logger.debug("自动入网跳过: %s", exc)

    def not_on_tailnet_details(self) -> List[Detail]:
        """Tailscale 没起来时,横幅该说的话。

        装了、配了、却没入成(比如要管理员权限)和「没装」是两回事,下一步也不同,
        不能都说成「未安装」。
        """
        sj = self.self_join
        if sj and sj["state"] not in ("joined", "not_configured"):
            return [
                ("Tailscale", f"没能加入自建 tailnet:{sj['detail']}", "warn"),
                ("修复", sj["how_to_fix"], "info"),
            ]
        return [("Tailscale", "未安装 (LAN 直连模式)", "warn")]

    def start_lan_discovery(self) -> Detail:
        """发布 ``_galaxy._tcp``,返回横幅的一行。"""
        try:
            from galaxy_gateway.mdns_announcer import start_lan_announcer

            self._mdns = start_lan_announcer(self.web_ui_port)
        except Exception as exc:  # noqa: BLE001 — 发现不了不挡启动
            logger.debug("局域网发布跳过: %s", exc)
            self._mdns = None
        if self._mdns is not None:
            return ("局域网发现", "已发布 _galaxy._tcp", "ok")
        return ("局域网发现", "未发布(已关闭、zeroconf 未装或探不到局域网地址)", "warn")

    def stop(self) -> None:
        if self._mdns is not None:
            try:
                self._mdns.stop()
            finally:
                self._mdns = None
