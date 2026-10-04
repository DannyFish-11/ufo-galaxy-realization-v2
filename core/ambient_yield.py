"""自发注意力给用户让路。

与 :mod:`core.ambient_attention_loop` 的分工：循环自己管「看什么、怎么决策、怎么路由」；
这里只管「这一拍该不该碰模型」—— 在文件大小门禁的基线上，按仓库的规矩拆出来、以混入接上。

为什么要让路
-----------
真机本地 gemma 一次决策 38~48 秒，而 SILENT 决策不打冷却，场景一直在变就是一个调用接一个调用。
Ollama 一次只算一个：用户发的「你好」排在自发观察后面，90 秒超时；整台机器的 CPU 也被占满，
面板、感知帧、对话流一起变慢。后台的自发观察给用户的请求让路，不是反过来。

三条规矩
--------
1. 用户的请求在跑 → 本拍不碰模型；
2. 一次决策调用进行中用户的请求到了 → **放弃这次调用**。取消协程会断开到模型服务的连接，
   Ollama 随之停掉这次生成；
3. 一次调用用了 T 秒，之后至少歇 ``_REST_FACTOR * T`` 秒 —— 把占用模型的时间比例压在 1/4 以内。
   快模型（云端 1~2 秒）几乎不受影响。

被让路挡下的那一拍记成「延后」：门控已经把那一帧当看过了，不记着的话那次变化永远没人看；
让路结束后补看一次。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("Galaxy.Ambient")

#: 一次决策调用用了 T 秒，之后至少歇 ``_REST_FACTOR * T`` 秒再看下一次。
_REST_FACTOR = 3.0
#: 决策调用进行中，每隔这么久看一眼有没有用户的请求到了。
_FOREGROUND_POLL_S = 0.25


def _foreground_busy() -> bool:
    """此刻有没有人在等的请求（用户的对话 / 语音 / 桌面操作）。查不到就当没有 —— 不因此停掉自发注意力。"""
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        return bool(get_desktop_presence_runtime().foreground_request_active())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ambient: 查前台请求失败(按没有处理): %s", exc)
        return False


class AmbientYieldMixin:
    """``AmbientAttentionLoop`` 的让路部分。依赖宿主提供 ``_get_decider()``。"""

    _rest_until: float
    _deferred: bool
    yielded: int

    def _init_yield_state(self) -> None:
        #: 上一次决策调用之后要歇到什么时候（time.time()）。
        self._rest_until = 0.0
        #: 有一拍因为让路 / 歇息被挡下了，让路结束后补看一次。
        self._deferred = False
        #: 让给用户请求的次数（含中途放弃的调用），观测用。
        self.yielded = 0

    def _should_yield_now(self) -> bool:
        """本拍要不要让路（用户的请求在跑，或上一次决策刚占了很久）。挡下就记成延后。"""
        if _foreground_busy():
            self.yielded += 1
        elif time.time() >= self._rest_until:
            return False
        self._deferred = True
        return True

    async def _decide_yielding(self, obs: Any) -> Optional[Any]:
        """调决策脑；调用进行中用户的请求到了就放弃这次调用。放弃时返回 ``None``。

        正常返回时按这次用时记下该歇多久。决策本身抛的异常原样往上抛，由调用方按 SILENT 处理。
        """
        started = time.monotonic()
        task = asyncio.ensure_future(self._get_decider().decide(obs))  # type: ignore[attr-defined]
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_FOREGROUND_POLL_S)
                if done:
                    break
                if _foreground_busy():
                    task.cancel()
                    try:
                        await task
                    except BaseException:  # noqa: BLE001 — 被取消的调用抛什么都不重要
                        pass
                    self._deferred = True
                    self.yielded += 1
                    logger.info(
                        "Ambient: 用户的请求到了，放弃正在进行的模型调用（已用 %.1fs），把模型让给它",
                        time.monotonic() - started,
                    )
                    return None
        except asyncio.CancelledError:
            task.cancel()
            raise
        self._rest_until = time.time() + _REST_FACTOR * (time.monotonic() - started)
        return task.result()
