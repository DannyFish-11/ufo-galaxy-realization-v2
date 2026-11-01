"""launcher/port_guard.py —— API 网关端口的预检,与「端口被占就不往下起」。

从 ``launcher/services.py`` 搬出来(那个文件在大小门禁的基线上);``launcher.services`` 原地 re-export,
doctor 与测试照旧按 ``launcher.services._probe_port_bindable`` 取。
"""

from __future__ import annotations

import os
import socket

#: 端口预检专用的探测地址。刻意只探环回口,绝不绑通配地址,详见
#: :func:`_probe_port_bindable`。
_PORT_PROBE_HOST = "127.0.0.1"


class GatewayPortTaken(RuntimeError):
    """API 网关的端口绑不上(多半是已经有一个 Galaxy 在跑)。启动在这里停下,不半起第二份。"""


def _probe_port_bindable(port: int) -> str:
    """试绑一次端口。可绑返回空串;不可绑返回人话原因。

    只做一次真实的 bind/close,不留监听——这是判断"端口是不是已经被占了"
    最直接也最可靠的办法(比连一下看通不通准确:后者对只绑了 IPv4 或正在
    启动中的服务会误判)。

    Windows 上**不设** SO_REUSEADDR:它的语义是"允许强抢已被占用的端口",打开反而会让探测通过、真正 bind 时才炸。
    POSIX 上要设:它只放过 TIME_WAIT 残留(刚停掉的服务连着设备时留下的),仍拒绝正在监听的端口;不设就会
    把重启过快误报成"端口被占"(uvicorn 自己绑端口时是设了的)。

    **只探环回口,不绑通配地址。** 别的进程占着 ``0.0.0.0:P``(监听中,或没开 SO_REUSEADDR 的绑定)时,再去绑
    ``127.0.0.1:P`` 同样会 EADDRINUSE,所以环回探测足以覆盖本函数要防的场景——**本机已经有一个 Galaxy 占着
    这个端口**(真机上 Electron 拉起第二套后端抢 9000 就是这个形态)。

    已知不覆盖:某服务只绑在某块具体的非环回网卡上(如 ``192.168.1.5:P``)—— 本探测放行、uvicorn 绑
    ``0.0.0.0:P`` 仍失败,由调用方对 uvicorn 启动失败的处理如实兜底。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((_PORT_PROBE_HOST, int(port)))
        return ""
    except OSError as exc:
        return f"{exc.__class__.__name__}: {exc}"
