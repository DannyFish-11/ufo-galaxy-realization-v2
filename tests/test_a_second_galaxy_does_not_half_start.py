"""端口被占(多半已经有一个 Galaxy 在跑)时,第二份不往下起 —— 也不写「就绪」。

第 8 轮真跑:上一份还没退干净时又起了一份。第二份的日志::

    ERROR | API gateway: API 网关端口 9000 无法绑定(OSError: [Errno 98] Address already in use)……
    WARNING | 传输 tcp 的端口 19421 被占(这台机器上可能还有一个 Galaxy 进程):只发不收
    WARNING | 传输 mesh 的端口 19422 被占……
    ✓ 就绪 · 5 正常 · 4 降级
        接口   http://localhost:9000

它接着起核心服务、节点、基础设施,最后写「就绪 · 接口 http://localhost:9000」—— 那个地址上答话的是**另一个**进程
(对着它打的请求全都落到了旧代码上,真跑核对因此白跑了一遍)。现在端口预检一失败就停在这里,退出码 1。
"""

from __future__ import annotations

import asyncio
import inspect
import socket

import pytest


def test_an_occupied_gateway_port_raises_the_dedicated_error():
    from launcher.service_manager import ServiceManager
    from launcher.services import GatewayPortTaken, SystemConfig, UnifiedWebUI

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        config = SystemConfig()
        config.web_ui_port = port
        config.host = "127.0.0.1"
        ui = UnifiedWebUI(ServiceManager(config), config)
        with pytest.raises(GatewayPortTaken, match=str(port)):
            asyncio.run(ui.start())


def test_start_stops_right_there_instead_of_starting_a_second_copy():
    from launcher.services import GalaxyUnified

    src = inspect.getsource(GalaxyUnified.start)
    handler = src[src.index("except GatewayPortTaken") :]
    handler = handler[: handler.index("except Exception")]
    assert "raise SystemExit(1)" in handler, "端口被占时要在这里停下"
    assert src.index("except GatewayPortTaken") < src.index("cs = CoreServiceLauncher("), "要在起核心服务之前停"


def test_the_probe_still_lives_where_doctor_and_tests_look_for_it():
    from launcher import port_guard, services

    assert services._probe_port_bindable is port_guard._probe_port_bindable
    assert services._PORT_PROBE_HOST == "127.0.0.1"
