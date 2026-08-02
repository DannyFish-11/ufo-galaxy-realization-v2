"""
core.log_redaction — 日志脱敏助手
=================================

B7 修复。审查发现全仓只有一个脱敏函数（``galaxy_gateway/android/handlers/auth.py``
里的 ``_mask()``，且只服务于 Android 认证握手），**没有通用的 URL 凭据脱敏**。
与 ``docker-compose.yml`` 把带密码的连接串放进环境变量这一点叠加，任何一处
``logger.info("... %s", uri)`` 都会把凭据落盘。

本模块提供三个原语，覆盖实际出现过的三种泄漏形态：

* :func:`redact_url`    —— ``mongodb://user:pass@host`` 这类连接串里的密码
* :func:`redact_secret` —— 已知是密钥的单值（API key / token）
* :func:`redact_text`   —— 来源不可控的自由文本（如上游 HTTP 响应体）

设计取舍
--------
1. **只做删减，不抛异常。** 脱敏函数出现在日志路径上，它自己崩了会把原本只是
   "日志难看"的问题升级成"业务中断"。所有函数对任意输入都返回字符串。
2. **宁可多删。** 判不准的一律当作敏感处理 —— 日志少一点信息可以接受，
   多一个凭据不行。
3. **不试图做全能扫描器。** 这里不是 DLP 产品；目标是把已知的、真实发生过的
   泄漏面堵住，而不是穷举所有可能的密钥形态。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

__all__ = ["redact_url", "redact_secret", "redact_text", "secret_fingerprint", "REDACTED"]

REDACTED = "***REDACTED***"

# scheme://user:password@host —— 捕获 userinfo 段里的密码部分
_URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<user>[^:/@\s]+):(?P<pw>[^@/\s]*)@")

# 自由文本里的 key=value / "key": "value" 形态。键名命中即整值替换。
_SENSITIVE_KEY = (
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|apikey|password|passwd|secret|authorization|bearer|private[_-]?key)"
)
_KV_RE = re.compile(rf'(?i)(["\']?{_SENSITIVE_KEY}["\']?\s*[:=]\s*)(["\']?)([^"\'&,;\s}}]+)(\2)')


def redact_url(value: Any) -> str:
    """把 URL / 连接串里的密码替换掉，其余部分保留以便排障。

    ``mongodb://admin:hunter2@db:27017/x`` → ``mongodb://admin:***REDACTED***@db:27017/x``

    保留用户名与主机端口是刻意的：排障时最常需要的就是"连的是哪台、用的哪个账号"，
    这两项本身不是密钥。查询串里的密钥也会一并处理。

    非字符串、空值、不含凭据的 URL 原样（转成字符串）返回。
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return text

    redacted = _URL_CREDENTIAL_RE.sub(rf"\g<scheme>\g<user>:{REDACTED}@", text)

    # 查询串里也可能带密钥：?token=xxx&api_key=yyy
    try:
        parts = urlsplit(redacted)
        if parts.query:
            new_query = _KV_RE.sub(rf"\1\2{REDACTED}\4", parts.query)
            if new_query != parts.query:
                redacted = urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except ValueError:
        # urlsplit 对畸形输入会抛 ValueError —— 此时已完成 userinfo 脱敏，直接返回。
        pass

    return redacted


def redact_secret(value: Any, keep: int = 0) -> str:
    """把一个**已知是密钥**的值脱敏。

    :param keep: 保留末尾几位以便区分是哪把 key。默认 ``0``（全遮）。

        注意与被本修复替换掉的旧写法的差别：``pixverse_adapter.py`` 原本打的是
        ``api_key[:8]`` —— 保留**前缀**。多数厂商的 key 前缀是固定的
        （``sk-`` / ``sk-ant-`` / ``AIza`` 之类），前 8 位往往既泄漏了熵、又
        无法区分同一厂商的两把 key。要留就留末尾。

    长度不足以安全保留时（``len <= keep``）一律全遮，避免短 key 被整个打出来。
    """
    if value is None:
        return REDACTED
    text = str(value)
    if not text:
        return REDACTED
    if keep <= 0 or len(text) <= max(keep, 8):
        return REDACTED
    return f"{REDACTED}{text[-keep:]}"


def secret_fingerprint(value: Any, *, length: int = 8) -> str:
    """返回密钥的**指纹**（SHA-256 前若干位十六进制），不含任何原始密钥material。

    动机：``redact_secret(keep=N)`` 保留末 N 位是为了让运维能判断"key 换没换"，
    但那毕竟把真实密钥的一部分写进了日志 —— CodeQL 的
    "Clear-text logging of sensitive information" 报的就是这个，而且它是对的：
    密钥的任何片段进日志都是泄漏，只是量的差别。

    指纹解决了同一个需求而不泄漏任何 material：同一把 key 指纹恒定、
    不同 key 指纹不同，且不可逆推。**需要区分密钥时应优先用它，而不是 keep=N。**

    :param length: 取十六进制摘要的前几位。默认 8 位（32 bit）足够区分人工管理
        规模下的几把 key；不要用它做安全判定，它只是个标签。
    """
    import hashlib

    if value is None:
        return "none"
    text = str(value)
    if not text:
        return "empty"
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    return f"sha256:{digest[:max(4, length)]}"


def redact_text(value: Any, *, max_len: int = 512) -> str:
    """脱敏一段**来源不可控**的自由文本，并限长。

    典型用法是上游 HTTP 响应体：OAuth 的 token 端点在失败时可能把请求参数
    （含 ``client_secret``）或已签发的 token 回显在错误体里，直接 ``resp.text``
    进日志就等于把凭据写进磁盘。

    限长是第二道保险：即使模式没匹配上，也不会把一整个响应体灌进日志。
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return text
    redacted = _KV_RE.sub(rf"\1\2{REDACTED}\4", text)
    if len(redacted) > max_len:
        redacted = redacted[:max_len] + f"…(截断，原长 {len(text)})"
    return redacted
