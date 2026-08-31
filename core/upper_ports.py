"""``core.upper_ports`` —— ``core/`` 要用上层的东西时,从这里取,不要 ``import``。

问题
----
``scripts/check_import_boundaries.py`` 立的规矩是"gateway 依赖 core,不是反过来"。
实测越界 **70 处、30 个文件**(``core/`` → ``galaxy_gateway/`` 53,
``core/`` → ``enhancements/`` 17)。这道闸在 CI 上一直是**告警模式**跑的 ——
一道永远报警又永远不失败的闸,和没有闸是一回事。

这 70 处不是随手写的。逐个看过之后,它们全是同一种形状::

    try:
        from galaxy_gateway.android_bridge import android_bridge
        ...
    except Exception:
        <降级>

也就是"上层组件是可选的,没有就降级"。函数内延迟导入是为了避免 import 期循环,
本身是个正当写法 —— 问题只在于:**依赖关系散在 30 个文件里,没人能一眼看全**,
而且它让"core 能不能脱离 gateway 独立成立"这件事无法机械校验。

做法:端口 + 绑定表
--------------------
``core/`` 侧只认**端口名**::

    bridge = upper_ports.resolve("gateway.android_bridge.android_bridge")

端口名到真实目标的映射放在 ``config/upper_layer_ports.json``,那是**数据不是代码**。
于是 ``core/`` 的源码里不再出现任何上层模块名,57 个上层依赖集中在一张可审的表里。

**这到底解决了什么,没解决什么 —— 说清楚**

解决了:

* ``core/`` 不再在代码里点名上层,分层规则可以机械校验,闸能开 ``--strict``;
* 散在 30 个文件里的 70 处上行依赖,收敛成一张 57 行的表,增删一眼看得见;
* 绑定可替换、可移除 —— :func:`register` 让上层(或测试)显式注入实现,
  这才是真正的倒置接口;表里的默认值只是"没人注入时用什么"。

**没有**解决:

* 这些代码路径在运行时**仍然需要**上层存在。晚绑定不是解耦。把
  ``galaxy_gateway/`` 整个删掉,涉及的功能照样不能用 —— 只是不再在 import 期炸,
  而是走各调用点既有的降级分支。

行为等价
--------
:func:`resolve` 做的事就是 ``import_module`` + ``getattr``,与原来的
``from X import y`` 逐字等价(``import_module`` 走 ``sys.modules`` 缓存;属性每次
重新取,所以上层把单例换掉时这里跟着变,和 import 语句的语义一致)。

失败时抛 :class:`PortUnavailable`,它**继承 ``ImportError``** —— 各调用点原有的
``except ImportError`` / ``except Exception`` 原样接得住,一处降级分支都不用改。
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict

__all__ = [
    "PortUnavailable",
    "binding_of",
    "declared_ports",
    "is_available",
    "register",
    "resolve",
    "unregister",
]

logger = logging.getLogger(__name__)

BINDINGS_PATH = Path(__file__).resolve().parent.parent / "config" / "upper_layer_ports.json"

_lock = threading.RLock()
_bindings: Dict[str, str] | None = None
_overrides: Dict[str, Any] = {}


class PortUnavailable(ImportError):
    """端口取不到:没登记、绑定的模块导不进来、或模块里没有那个属性。

    继承 ``ImportError`` 是刻意的 —— 改造前每个调用点捕的都是 ``ImportError``
    或 ``Exception``,继承之后那些降级分支一行都不用动就依然生效。
    """


def _load_bindings() -> Dict[str, str]:
    global _bindings
    with _lock:
        if _bindings is None:
            try:
                raw = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
                _bindings = dict(raw.get("ports", {}))
            except (OSError, ValueError) as exc:
                # 表读不到不是致命的:所有调用点本来就有降级分支。但必须说出来 ——
                # 静默地让一整层依赖消失,比报错难查得多。
                logger.error("upper_ports: 绑定表读取失败,所有上层端口将不可用。path=%s reason=%s", BINDINGS_PATH, exc)
                _bindings = {}
        return _bindings


def declared_ports() -> Dict[str, str]:
    """绑定表的一份拷贝(端口名 → ``"模块:属性"``)。给测试和审查用。"""
    return dict(_load_bindings())


def binding_of(port: str) -> str | None:
    """*port* 绑到哪个目标;没登记返回 ``None``。"""
    return _load_bindings().get(port)


def register(port: str, value: Any) -> None:
    """显式注入一个实现,优先于绑定表。

    这是真正的倒置接口:上层在启动时把自己装进来,或测试装一个替身进来,
    ``core/`` 侧的代码一个字都不用改。
    """
    with _lock:
        _overrides[port] = value


def unregister(port: str) -> None:
    """撤掉 :func:`register` 装进来的实现,回到绑定表。"""
    with _lock:
        _overrides.pop(port, None)


def resolve(port: str) -> Any:
    """取出 *port* 背后的东西;取不到抛 :class:`PortUnavailable`。"""
    with _lock:
        if port in _overrides:
            return _overrides[port]

    target = _load_bindings().get(port)
    if not target:
        raise PortUnavailable(f"端口 '{port}' 没有登记在 {BINDINGS_PATH.name} 里")

    module_name, _, attr = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — 上层模块导入期的任何异常都算"这个端口不可用"
        raise PortUnavailable(f"端口 '{port}' 的绑定 '{target}' 导入失败: {exc}") from exc

    if not attr:
        return module
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise PortUnavailable(f"端口 '{port}' 的绑定 '{target}' 里没有 '{attr}'") from exc


def is_available(port: str) -> bool:
    """*port* 现在能不能取到。注意它会**真的**去导入,不是只查表。"""
    try:
        resolve(port)
    except PortUnavailable:
        return False
    return True
