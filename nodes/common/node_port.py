"""节点自己该绑哪个端口 —— 一个地方回答，所有节点照抄。

为什么需要这个
==============
之前每个节点自己写死 ``uvicorn.run(app, port=8065)``。启动器另有一张表
(``config/unified_ports.yaml`` → ``core.port_config``),两边不需要一致也不会报错
—— 因为没有任何机制让它们对账。

实测(把 125 个节点按启动器的真实调用方式逐个拉起来,读节点自己打印的
``Uvicorn running on``)对不上 8 处::

    节点                       启动器去敲   节点实际绑
    Node_23_Time                  8024        8023
    Node_24_Weather               8025        8024
    Node_49_OctoPrint             8048        8049
    Node_64_Telemetry             8063        8064
    Node_65_LoggerCentral         8064        8065
    Node_67_HealthMonitor         8066        8067
    Node_68_Security              8067        8068
    Node_69_BackupRestore         8068        8069

后果不只是"误报启动超时"。monitoring 组三个节点全部错位,而错位之后端口互相
串了门:启动器敲 8067 拿到 200,把它记成 **Security 已就绪** —— 8067 上跑的其实是
HealthMonitor。三个节点明明都活着,报告说 1/3,而那个"1"还认错了人。如果
Security 真的挂了,这套机制会告诉你它是好的。

容器里更糟:``deploy/compose/full.yml`` 给 node-65 映射 ``8064:8064``,
``Dockerfile.node`` 的 HEALTHCHECK 也 curl ``localhost:8064``,而节点绑 8065 ——
**健康检查永远不会通过**,容器会一直是 unhealthy,而别的服务还 ``depends_on:
condition: service_healthy``。

为什么权威是 yaml,不是节点
==========================
一度想反过来改:让 yaml 服从"8000+编号"这个看起来更自然的约定。实测推翻了它 ——
另外 8 个节点(Node_26/56/57/58/59/60/63/80)**都老老实实听 yaml**,包括
Node_60=8160、Node_63=8163 这种明显不按编号来的值。也就是说 yaml 才是大多数节点
认的权威,错的是这 8 个既不读 yaml 也不读环境变量、把端口焊死在代码里的。
按那个提案改 yaml,会为了修 8 个而弄坏 8 个。

两套环境变量名
==============
还有一处此前没人对齐:原生启动器(``launcher/nodes.py``)传 ``PORT``,而
compose 与 ``Dockerfile.node`` 传 ``NODE_PORT``。Node_23 与 Node_80 读的是
``NODE_PORT`` —— 于是它们**在容器里对、在原生启动器下错**。这里两个都认。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["resolve_node_port"]


def _from_env(*names: str) -> Optional[int]:
    for n in names:
        raw = (os.environ.get(n) or "").strip()
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            logger.warning("环境变量 %s 不是合法端口号,忽略:%r", n, raw)
    return None


def resolve_node_port(node_name: str, fallback: int) -> int:
    """回答"``node_name`` 这个节点该绑哪个端口"。

    优先级(高 → 低):

    1. ``core.port_config.get_node_port()`` —— 唯一权威。它自己已经处理了
       ``GALAXY_PORT_<NODE_NAME>`` 运行时覆盖与 ``config/unified_ports.yaml``。
       放在第一位是刻意的:启动器探活时敲的就是这个值,容器的端口映射与
       HEALTHCHECK 也是从这份 yaml 生成的。让节点也从这里取,
       **"启动器敲哪个口 = 节点绑哪个口"就成了构造上成立的事**,而不是靠人对齐。
    2. ``NODE_PORT`` —— compose / ``Dockerfile.node`` 传的。
    3. ``PORT`` —— ``launcher/nodes.py`` 传的。
    4. ``fallback`` —— 节点原来写死的那个字面量。保留它是为了单独
       ``python nodes/Node_xx/main.py`` 跑一个节点时(不经启动器、不在容器里、
       yaml 也读不到)仍然能起来。

    Args:
        node_name: 完整节点名,如 ``"Node_65_LoggerCentral"``。
        fallback: 都取不到时用的字面量。

    Returns:
        端口号。**任何情况下都返回一个可用的整数,不抛异常** —— 端口解析失败不该
        让一个本来能跑的节点起不来。
    """
    try:
        from core.port_config import get_node_port

        return get_node_port(node_name)
    except Exception as exc:  # KeyError(未配置) / ImportError(单独跑节点时没有 core)
        logger.debug("port_config 未能解析 %s 的端口(%s),退到环境变量", node_name, exc)

    env_port = _from_env("NODE_PORT", "PORT")
    if env_port is not None:
        return env_port

    return fallback
