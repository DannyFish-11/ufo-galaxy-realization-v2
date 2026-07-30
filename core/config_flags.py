"""配置开关/数值的统一读取。

为什么要有这个模块
------------------
语音栈里有 **5 份逐字相同**的 ``_flag()`` 和 **2 份**几乎相同的 ``_num()``,分别长在
``voice_duplex_session`` / ``voice_dialog_policy`` / ``voice_echo_guard`` /
``acoustic_echo_canceller`` / ``system_audio_capture_service`` 里。复制粘贴出来的助手
最大的问题不是重复本身,而是**修一处修不到其它处** —— 下面那个 bug 就是活例子。

顺带修掉的一个真 bug:空值会把开关打开
--------------------------------------
原 ``_flag`` 是::

    os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")

``os.getenv(name, default)`` 的 default **只在变量不存在时生效**;变量存在但值为空串时
返回的是 ``""``。而 ``"".strip().lower()`` 是 ``""``,不在那个假值元组里 → 返回
``True``。也就是说:

    GALAXY_VOICE_DUPLEX=        # 空值

会把一个**默认关闭**的开关打开。

这不是纸上推演。``main.py`` 顶部的注释自己写着:设置面板自动生成的 ``.env`` 会把
**全部** schema 键写成 ``KEY=``(空值)。``main.py`` 里做了防护(只注入非空值),但那个
防护只在 main.py 里 —— 凡是别的途径把 ``.env`` 灌进环境的场景都会中招,而这些恰恰是
最常见的部署方式:

* Docker Compose 的 ``env_file:``
* systemd 的 ``EnvironmentFile=``
* ``set -a; . .env; set +a``

这几种都会把空值原样设进环境。于是"面板上明明关着的开关,部署到容器里就自己开了"。

判定这是遗漏而不是有意为之的依据:**同文件里的 ``_num()`` 处理了这个情况**
(``if raw is None or not raw.strip(): return default``)。同一个作者在数值那边想到了,
在布尔这边漏了。

本模块统一按"**空值/纯空白 = 视同未设置**"处理。
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Union

logger = logging.getLogger("Galaxy.ConfigFlags")

#: 视为"关"的字面量。大小写与前后空白都不敏感。
_FALSY = ("0", "false", "no", "off", "n", "f")

#: 视为"开"的字面量。显式列出是为了让**无法识别的值**能被察觉(见 ``flag()``)。
_TRUTHY = ("1", "true", "yes", "on", "y", "t")


def _raw(name: str) -> Optional[str]:
    """取环境变量;**空串/纯空白一律视同未设置**(返回 None)。

    这正是原 ``_flag`` 漏掉的一步。
    """
    val = os.environ.get(name)
    if val is None or not val.strip():
        return None
    return val.strip()


def flag(name: str, default: Union[bool, str]) -> bool:
    """读布尔开关。

    Args:
        name: 环境变量名。
        default: 未设置(含**空值**)时的取值。可以给 ``bool``,也可以给原先那种
            ``"0"``/``"1"`` 字符串 —— 兼容既有调用点的写法,避免为了统一助手而去改
            一堆调用处、把一次纯重构变成一次有风险的批量改动。

    无法识别的值(既不在真值表也不在假值表,比如 ``GALAXY_AEC=maybe``)会**告警并退回
    默认**,而不是被静默当成"开"。原实现是"只要不是那 4 个假值就算开",于是拼错的值
    (``GALAXY_AEC=flase``)会静默生效成"开" —— 那是最难发现的一类配置错误。
    """
    fallback = default if isinstance(default, bool) else str(default).strip().lower() in _TRUTHY
    raw = _raw(name)
    if raw is None:
        return fallback
    low = raw.lower()
    if low in _TRUTHY:
        return True
    if low in _FALSY:
        return False
    logger.warning(
        "%s=%r 不是可识别的布尔值(可用:%s / %s),已退回默认值 %s。",
        name,
        raw,
        "/".join(_TRUTHY[:3]),
        "/".join(_FALSY[:3]),
        fallback,
    )
    return fallback


def num(
    name: str,
    default: float,
    *,
    lo: Optional[float] = None,
    hi: Optional[float] = None,
) -> float:
    """读数值;非法值告警并退回默认(不静默吞掉配置错误)。

    ``lo``/``hi`` 给了就夹紧 —— 原先各调用点自己在外面 ``max(0.0, min(1.0, ...))``,
    夹紧逻辑散在各处,顺手收进来。
    """
    raw = _raw(name)
    if raw is None:
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            logger.warning("%s=%r 不是合法数值,已退回默认值 %s。", name, raw, default)
            value = default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def integer(name: str, default: int, *, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    """读整数。经 ``num()`` 保证同样的空值/非法值语义,再取整。"""
    value = num(name, float(default), lo=None if lo is None else float(lo), hi=None if hi is None else float(hi))
    return int(value)


def text(name: str, default: str = "") -> str:
    """读字符串;空值视同未设置。"""
    raw = _raw(name)
    return raw if raw is not None else default
