"""进程内共用一份默认 TLS 信任库。

## 被修的问题

httpx 每建一个客户端（``httpx.AsyncClient()``）就把整份 CA 证书重新载入一遍 —— 实测一次 40–80 毫秒（Linux、空闲），
真机的 i5 + 本地大模型在占 CPU 时是几百毫秒。而这些客户端大多是**在事件循环线程上现建现用**的（探测 Ollama、
发现厂商、各个适配器……）：启动日志里的卡顿采样、首轮对话的几秒停顿，都能看到 ``ssl.create_default_context``
压在循环上。仓库里有五十来处这样的调用，一处处改成传 ``verify=ctx`` 既多又容易漏新的。

## 做法

httpx 的传输层在构造时调 ``create_ssl_context(verify=…, cert=…, trust_env=…)``。这里把它包一层：**只有最普通的那种
调用**（``verify=True``、没有客户端证书）按 ``trust_env`` 与 ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` 缓存同一个
上下文；``verify=False``、自带 CA 文件、客户端证书这些都原样走 httpx 自己的路径。共用 ``SSLContext`` 是
线程安全的，httpx 自己也不改它。第一份在安装时就由旁边的线程建好，不压在第一个请求上。

httpx 内部函数换名 / 换位置时这里**退回不装**（返回 ``False``），不会让启动失败 —— 只是回到逐个客户端重新载入。
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Tuple

_installed = False


def install_shared_tls_context() -> bool:
    """让 httpx 默认的 TLS 上下文进程内只建一次。装上（或早已装上）返回 ``True``。"""
    global _installed
    if _installed:
        return True
    try:
        import httpx._transports.default as transport

        original = transport.create_ssl_context
    except Exception:  # noqa: BLE001 — httpx 内部换了结构：不装，不报错
        return False

    cache: Dict[Tuple[Any, ...], Any] = {}
    lock = threading.Lock()

    def create_ssl_context(*args: Any, **kwargs: Any) -> Any:
        if args or kwargs.get("verify", True) is not True or kwargs.get("cert") is not None:
            return original(*args, **kwargs)
        key = (
            kwargs.get("trust_env", True),
            os.environ.get("SSL_CERT_FILE"),
            os.environ.get("SSL_CERT_DIR"),
            tuple(sorted((k, repr(v)) for k, v in kwargs.items() if k not in ("verify", "cert", "trust_env"))),
        )
        ctx = cache.get(key)
        if ctx is None:
            with lock:
                ctx = cache.get(key)
                if ctx is None:
                    ctx = cache[key] = original(*args, **kwargs)
        return ctx

    transport.create_ssl_context = create_ssl_context
    _installed = True
    # 第一份也别等到第一个请求里才建：启动时在旁边的线程里先建好，循环线程用的时候已经在缓存里
    threading.Thread(target=create_ssl_context, kwargs={"verify": True}, name="warm-tls", daemon=True).start()
    return True
