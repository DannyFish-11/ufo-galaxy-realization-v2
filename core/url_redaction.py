"""把可能带凭据的 URL 收敛成**可以安全打日志**的形式。

为什么需要它
------------
本仓库里有好几类 URL 是**自带凭据**的,把它们原样写进日志就是明文泄露密钥:

* ``GALAXY_NATS_URL`` —— ``core/nats_bus.py`` 调 ``nats.connect(target, ...)`` 时
  **没有传任何 user/password/token 参数**,也就是说在这个仓库里 NATS 鉴权**只能**靠
  ``nats://user:pass@host:4222`` 这种 URL 内嵌形式;
* ``SECRETVAULT_URL`` —— 密钥库自己的地址,同样可能带 token;
* 双工语音的 realtime 地址 —— Gemini 那一支就是
  ``wss://…BidiGenerateContent?key={key}``,API key 直接拼在 query 里。

这个函数原先长在 ``core/voice_duplex_session.py`` 里(那是它被第一次需要的地方)。移到
这里是因为它不是语音特有的:让 ``nats_bus`` / ``credential_vault`` 去 import 语音模块显然
不对,而各自再抄一份就会重演"复制粘贴的助手修一处修不到其它处"那类问题 —— 本仓库刚因为
5 份逐字相同的 ``_flag()`` 吃过一次亏(见 ``core/config_flags.py``)。

只保留 scheme/host/port
-----------------------
诊断日志要回答的是"连的是哪台机器",这三样就够了。path / query / fragment / userinfo 一律
丢掉 —— 它们才是凭据可能藏身的地方。

**这不是"脱敏就够了"的意思。** 静态分析(CodeQL 的
``py/clear-text-logging-sensitive-data``)不会因为你套了个清洗函数就放行:把 secret 喂进一
个返回值会被打印的函数,数据流上那条边只会更明显。真正安全的写法是**让被打印的值根本不
来自密钥**。这个函数管的是另一半:值本身确实来自用户配的地址、而那个地址可能夹带凭据 ——
这时脱敏是对的解法。两件事都要做,别互相替代。
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

logger = logging.getLogger("Galaxy.UrlRedaction")

#: 无法解析时的占位。刻意不回显原串 —— 畸形输入里照样可能有凭据。
INVALID = "(无效地址)"


def safe_endpoint(url: str) -> str:
    """``url`` → ``scheme://host:port``;解析不出来返回 :data:`INVALID`。

    不抛异常:打日志本身绝不该成为崩溃来源。
    """
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").strip()
        if not host:
            return INVALID
        scheme = (parts.scheme or "").strip()
        port = parts.port  # 端口非法时 urlsplit 在这里抛 ValueError,由下面接住
    except Exception as exc:  # noqa: BLE001
        logger.debug("解析 URL 失败: %s", exc)
        return INVALID
    prefix = f"{scheme}://" if scheme else ""
    return f"{prefix}{host}:{port}" if port else f"{prefix}{host}"


def normalise_base_url(value: str, *, default_scheme: str = "http") -> str:
    """给缺 scheme 的地址补上,使其能被 :func:`urllib.parse.urlsplit` 正确拆开。

    为什么必须有这一步
    ------------------
    ``urlsplit`` 对没有 scheme 的地址的行为**取决于主机名长什么样**,而且是反直觉的::

        urlsplit("http://localhost:32550") → scheme='http'      netloc='localhost:32550'
        urlsplit("localhost:32550")        → scheme='localhost' netloc=''  path='32550'   ← 主机没了
        urlsplit("192.168.1.7:9000")       → scheme=''          netloc=''  path='192...'

    也就是说 ``localhost:32550`` 会被当成 "scheme 是 localhost、路径是 32550",主机名整个
    丢掉;而 ``192.168.1.7:9000`` 因为点分数字不是合法 scheme,反而落进 path 里侥幸可用。
    **同一类输入两种结果**,而且坏掉的那种是最常见的写法。

    这不是纸上推演:``GALAXY_MINICPM_SERVER_URL`` / ``GALAXY_NATS_URL`` 这类地址是用户在
    面板里手填的,填 ``localhost:32550`` 而不是 ``http://localhost:32550`` 完全正常。

    统一做法:没有 ``://`` 就补 ``default_scheme://``。已有 scheme 的原样返回。
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    return f"{default_scheme}://{raw.lstrip('/')}"


__all__ = ["safe_endpoint", "normalise_base_url", "INVALID"]
