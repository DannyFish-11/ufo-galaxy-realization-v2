"""nodes/common/url_guard.py — 出站抓取的 SSRF 守卫。

要挡什么
--------
本仓有一批节点的**本职就是按调用方给的 URL 去抓东西**(Node_08_Fetch、
Node_121_Web、Node_15_OCR、Node_93_VideoProcessor …)。CodeQL 的 ``py/full-ssrf``
在这些地方一共报了 13 条,而它们确实都是真的:节点监听 ``0.0.0.0``,任何能发请求的人
都能让这台机器**代替自己**去访问它够得着、而对方够不着的东西 ——

* ``http://127.0.0.1:9000/api/v1/...`` —— 本机的统一启动器,那上面有 354 条内部接口;
* ``http://192.168.x.x/...`` —— 家里的路由器管理页、NAS、摄像头;
* ``http://169.254.169.254/...`` —— 云上的实例元数据(临时凭证就在那儿)。

这不是"理论上可能",而是这类节点的默认能力:它们本来就是拿来抓 URL 的。

为什么是白名单式的**地址**判定,不是 URL 黑名单
----------------------------------------------
按字符串黑掉 ``localhost`` / ``127.0.0.1`` 是挡不住的:``http://127.1``、
``http://0x7f.1``、``http://[::1]``、``http://2130706433``、以及最直接的
"注册一个域名把 A 记录指向 127.0.0.1" —— 写法无穷,而它们最终都归结到同一件事:
**这个名字解析出来的 IP 是不是内网地址**。所以判定放在解析之后,对着
``ipaddress`` 的分类做,而不是对着字符串。

而且**所有**解析结果都要查,不是第一个:一个域名可以同时返回一个公网 IP 和一个
``127.0.0.1``,只查第一条就等于没查。

重定向
------
只在发起前查一次是不够的 —— 一个公网 URL 完全可以 302 到 ``169.254.169.254``,
而那一跳是客户端自己发的,调用点根本看不见。所以这里提供的是一个**带请求钩子的
客户端**(``guarded_async_client``):钩子对每一次出站请求生效,包括每一跳重定向。
只把校验放在调用点、然后照常 ``follow_redirects=True``,等于只锁了大门没锁后窗。

诚实说明:没有解决 DNS rebinding
-------------------------------
本模块在校验时解析一次、httpx 发请求时会**再解析一次**,两次之间理论上可以变。
彻底堵住需要把校验时得到的 IP 钉给连接层(自定义 transport / 连接到 IP 再带
Host 头),那会改动 TLS 校验与代理行为,代价明显大于这里要防的东西。
这一条如实写在这里,而不是假装覆盖了 —— 真正的攻击面里,"302 到元数据地址"
比 rebinding 常见得多,而那一条已经被钩子挡住了。

内网抓取仍然是需要的
--------------------
这套系统本身就是跨设备的:节点之间、节点与网关之间会互相取东西。所以默认拒绝之外
留了两个口子,都必须**显式**打开:

* ``GALAXY_ALLOW_INTERNAL_FETCH=true`` —— 整个进程放行(部署级决定);
* ``assert_url_allowed(url, allow_internal=True)`` —— 单次放行(代码级决定,
  用在"我知道我在打自己人"的地方)。

默认是拒绝。一个默认放行、要人记得去关的守卫,和没有守卫没有区别。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from typing import Iterable, List, Optional, Set
from urllib.parse import urlsplit

logger = logging.getLogger("Galaxy.Nodes.UrlGuard")

__all__ = [
    "UrlNotAllowed",
    "assert_url_allowed",
    "internal_fetch_allowed",
    "resolved_addresses",
    "guarded_async_client",
]

#: 只允许这两种 scheme。``file://``、``gopher://``、``ftp://`` 之类在"抓网页"
#: 这个语境里没有正当用途,而它们恰恰是 SSRF 最爱的载体(``file:///etc/passwd``)。
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UrlNotAllowed(ValueError):
    """URL 未通过出站守卫。

    刻意继承 ``ValueError`` 而不是自定义基类:调用点大多已经在 ``except Exception``
    里把错误转成 HTTP 4xx/5xx,不该因为引入这个守卫而多写一层捕获。
    """


def internal_fetch_allowed() -> bool:
    """进程级是否允许抓内网。默认 **False**。"""
    return str(os.getenv("GALAXY_ALLOW_INTERNAL_FETCH", "")).strip().lower() in ("1", "true", "yes", "on")


def _is_blocked_address(ip: ipaddress._BaseAddress) -> Optional[str]:
    """这个地址该不该拦?返回拦截理由,不拦返回 None。"""
    # IPv4-mapped IPv6(``::ffff:127.0.0.1``)必须先摊平再判 ——
    # IPv6Address.is_loopback 只认 ``::1``,对映射地址一律返回 False。
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        # 169.254.0.0/16 —— 云元数据服务(169.254.169.254)就在这个段里。
        return "link-local (含云实例元数据地址)"
    if ip.is_private:
        return "private/内网"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved or ip.is_unspecified:
        return "reserved/unspecified"
    return None


def resolved_addresses(host: str, port: int = 0) -> List[str]:
    """把主机名解析成**全部**地址。解析不出来就抛 ``UrlNotAllowed``。

    解析失败按拒绝处理而不是放行:一个解析不了的名字本来也抓不到东西,
    而"解析失败就放过去"会让守卫在 DNS 抖动时静默失效。
    """
    try:
        infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"无法解析主机名 {host!r}: {exc.__class__.__name__}") from exc
    out: List[str] = []
    seen: Set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def assert_url_allowed(url: str, *, allow_internal: Optional[bool] = None) -> None:
    """校验一个出站 URL;不允许就抛 :class:`UrlNotAllowed`。

    ``allow_internal`` 省略时取进程级设置(``GALAXY_ALLOW_INTERNAL_FETCH``)。
    显式传 ``True`` 表示"这一次我知道自己在打内网",传 ``False`` 表示"即使
    进程级放行了,这一次也不许"。
    """
    if allow_internal is None:
        allow_internal = internal_fetch_allowed()

    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UrlNotAllowed(f"只允许 http/https,收到 {parts.scheme or '(空)'!r}")

    host = parts.hostname
    if not host:
        raise UrlNotAllowed("URL 里没有主机名")

    # 直接写 IP 的情况不必解析 —— 也别去解析,那会让一个纯字面量触发 DNS 查询。
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    addresses: Iterable[str] = [host] if literal is not None else resolved_addresses(host, parts.port or 0)

    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            # getaddrinfo 理论上只会给出合法地址;真出现异常值时按拒绝处理。
            raise UrlNotAllowed(f"解析出无法识别的地址 {raw!r}") from None
        reason = _is_blocked_address(ip)
        if reason is None:
            continue
        if allow_internal:
            logger.info("放行内网出站请求 host=%s addr=%s (%s) —— 已显式开启", host, raw, reason)
            continue
        raise UrlNotAllowed(
            f"拒绝访问 {host} → {raw}({reason})。"
            f"确实需要抓内网时,设 GALAXY_ALLOW_INTERNAL_FETCH=true,"
            f"或在调用处传 allow_internal=True。"
        )


def guarded_async_client(*, allow_internal: Optional[bool] = None, **kwargs):
    """构造一个**每一跳都过守卫**的 ``httpx.AsyncClient``。

    与"在调用点校验一次再照常请求"的差别就是重定向:后者只锁了大门。
    ``event_hooks["request"]`` 对客户端发出的每一个请求生效,重定向那几跳也在内。

    用法与 ``httpx.AsyncClient`` 完全一致::

        async with guarded_async_client(timeout=30.0) as client:
            resp = await client.get(url)

    已有的 ``event_hooks`` 会被保留,守卫插在最前面。
    """
    import httpx  # 惰性 import:并非每个节点都装了 httpx,而本模块的校验部分不需要它

    async def _guard(request: "httpx.Request") -> None:
        assert_url_allowed(str(request.url), allow_internal=allow_internal)

    hooks = dict(kwargs.pop("event_hooks", None) or {})
    hooks["request"] = [_guard, *(hooks.get("request") or [])]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
