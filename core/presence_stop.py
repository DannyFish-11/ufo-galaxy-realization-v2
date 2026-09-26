"""core.presence_stop — 让它现在住手：在跑的请求、在念的话、在动的键鼠

要解决什么
----------
此前全仓没有一条"让它现在停下"的通路：README 写着 Esc 能关结果，代码里没有任何地方
处理 Esc；面板在请求进行中没有停止键；/chat/stream 断连时会取消任务，但面板从不断开。
而表达期它可能正在动你的鼠标键盘 —— 那恰恰是人最需要能叫停的时刻。

这里是「停」的全部机制，由 :class:`core.desktop_presence_runtime.DesktopPresenceRuntime`
与 ``RuntimeSession`` 以混入方式接上（那个文件在文件大小门禁的基线上，按仓库的规矩拆出来，
不抬基线）：

* :func:`stoppable` —— ``handle_request`` 的本体跑在一个**单独可取消的子任务**里；
* :class:`StopMixin` —— ``stop_current_activity``：取消在跑的请求、掐断朗读、打断常驻在场
  里正在说的那一句（会话留着）；
* :class:`ActingMixin` —— 「它此刻在不在动手」这一位，以及动手期间占着的叫停键
  （:mod:`core.stop_key`）。

与 ``halt_ambient_presence`` 的分工：那一条是**收摊**（关掉常驻在场，比如挂断双工）；
这一条是**住手** —— 会话本身留着，人还可以接着说。
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import functools
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

from core import stop_key as _stop_key

logger = logging.getLogger("Galaxy.PresenceStop")

__all__ = ["ActingMixin", "StopMixin", "note_bound_session", "stoppable", "stopped_result"]

# RUF006：发出去就不管的任务要留引用，免得被事件循环的弱引用回收到一半。
_BACKGROUND_TASKS: set = set()


@dataclasses.dataclass
class _InflightRequest:
    """一次正在跑的 ``handle_request``。「停」按它找到要取消的那个子任务。"""

    source: str
    task: Optional["asyncio.Future"] = None
    runtime_session_id: str = ""
    stopped: bool = False
    stop_reason: str = ""


# 子任务里「这一件事」是哪一个。只在子任务自己的 Context 里设，不漏到调用方。
_CURRENT_INFLIGHT: "contextvars.ContextVar[Optional[_InflightRequest]]" = contextvars.ContextVar(
    "galaxy_current_inflight_request", default=None
)


def note_bound_session(session: Any) -> None:
    """请求本体建好会话、挂进 Context 时调（``core.liminal_activity.bind_runtime_session``）。

    「停」据此知道这一件事对应哪个运行时会话 —— 交还给调用方的 ``runtime_session_id``
    与日志都靠它对得上。不在一次可停的请求里时什么都不做。
    """
    handle = _CURRENT_INFLIGHT.get()
    if handle is not None and not handle.runtime_session_id:
        handle.runtime_session_id = str(getattr(session, "runtime_session_id", "") or "")


def stopped_result(handle: _InflightRequest) -> Dict[str, Any]:
    """被停下的请求交还给调用方的结果。

    调用方拿到的是一个**正常返回值**，只是 ``stopped=True``、没有回复 —— 语音回路据此
    不念、/chat/stream 据此告诉面板"是你停下的"，而不是把它报成"后端什么都没给"。
    """
    return {
        "success": False,
        "response": "",
        "stopped": True,
        "stop_reason": handle.stop_reason or "user_stop",
        "runtime_session_id": handle.runtime_session_id,
        "trace_id": handle.runtime_session_id,
        "tristate": "silent",
        "entrypoint_source": handle.source,
    }


def stoppable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """让 ``handle_request`` 可以被「停」取消，而不连累调用方。

    不能直接取消调用方的任务：自发注意力循环是在自己的 tick 里 inline await
    ``handle_request`` 的（见 ``ambient_attention_loop._delegate``），语音回路也是。
    把 ``CancelledError`` 抛回那里，停掉的就不是"这一件事"，而是整条循环。
    所以本体单独成任务、单独可取消，被停下时调用方拿到 :func:`stopped_result`。

    反方向不变：调用方自己被取消时（/chat/stream 超时、客户端断连），asyncio 会顺着它
    正在等的这个子任务一并取消 —— 照旧把 ``CancelledError`` 抛上去。
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        handle = _InflightRequest(source=str(kwargs.get("source", "chat")))

        async def _body() -> Any:
            _CURRENT_INFLIGHT.set(handle)
            return await fn(self, *args, **kwargs)

        body = asyncio.ensure_future(_body())
        handle.task = body
        registry = self._inflight_registry()
        registry[id(body)] = handle
        try:
            return await body
        except asyncio.CancelledError:
            me = asyncio.current_task()
            outer_cancelling = bool(getattr(me, "cancelling", lambda: 0)()) if me is not None else False
            if handle.stopped and body.cancelled() and not outer_cancelling:
                return stopped_result(handle)
            raise
        finally:
            registry.pop(id(body), None)

    wrapper.__stoppable__ = True  # type: ignore[attr-defined]
    return wrapper


class StopMixin:
    """``DesktopPresenceRuntime`` 的「停」。依赖宿主的 ``_ambient_registry()``。"""

    def _inflight_registry(self) -> Dict[int, _InflightRequest]:
        """正在跑的请求（惰性建：仓库里有测试用 ``__new__`` 绕过 ``__init__`` 造轻量实例）。"""
        registry = getattr(self, "_inflight_requests", None)
        if registry is None:
            registry = {}
            self._inflight_requests = registry
        return registry

    def set_ambient_interrupt(self, handle: str, hook: Any) -> bool:
        """给一段常驻在场登记打断钩子（同步或协程均可）。人按「停」时执行。

        只让**正在说的这一句**停下，会话本身不关 —— 与 ``on_halt``（收摊）是两件事。
        句柄不存在时返回 ``False``。
        """
        entry = self._ambient_registry().get(handle)  # type: ignore[attr-defined]
        if entry is None:
            return False
        entry["on_interrupt"] = hook
        return True

    async def stop_current_activity(self, *, reason: str = "user_stop") -> Dict[str, Any]:
        """让它现在住手：取消在跑的请求、掐断在念的话、打断常驻在场里正在说的那一句。

        幂等 —— 什么都没在做时调用也返回成功，各项为空。钩子失败不阻止其它项：
        "停"不能因为某一处抛了异常就只停一半。
        """
        cancelled: List[Dict[str, str]] = []
        for handle in list(self._inflight_registry().values()):
            task = handle.task
            if task is None or task.done():
                continue
            handle.stopped = True
            handle.stop_reason = reason or "user_stop"
            task.cancel()
            cancelled.append({"source": handle.source, "runtime_session_id": handle.runtime_session_id})

        speech_interrupted = False
        try:
            from core.speech_output import interrupt_speech, is_speaking

            speech_interrupted = bool(is_speaking())
            interrupt_speech()
        except Exception as exc:  # noqa: BLE001
            logger.debug("停止时掐断朗读失败(非致命): %s", exc)

        interrupted: List[str] = []
        # 哪几段常驻在场没能打断。**只记句柄、不记异常内容** —— 这个结果会原样回给
        # HTTP 调用方（/api/v1/presence/stop），异常文本里可能有路径、堆栈、内部状态；
        # 细节进日志。
        failed: List[str] = []
        for h, entry in list(self._ambient_registry().items()):  # type: ignore[attr-defined]
            hook = entry.get("on_interrupt")
            if hook is None:
                continue
            try:
                outcome = hook()
                if inspect.isawaitable(outcome):
                    await outcome
                interrupted.append(h)
            except Exception:  # noqa: BLE001
                failed.append(h)
                logger.warning("常驻在场打断钩子失败 handle=%s", h, exc_info=True)

        if cancelled or speech_interrupted or interrupted:
            logger.info(
                "停止 | reason=%s 取消请求=%d 掐断朗读=%s 打断常驻在场=%d",
                reason or "-",
                len(cancelled),
                speech_interrupted,
                len(interrupted),
            )
        return {
            "stopped": cancelled,
            "speech_interrupted": speech_interrupted,
            "presences_interrupted": interrupted,
            "presences_failed": failed,
            "reason": reason,
        }


def _stop_key_callback() -> Optional[Callable[[], None]]:
    """人按下叫停键时要做的事。不在事件循环里时是 ``None`` —— 那时没有能停的东西。

    返回的函数跑在**键盘监听线程**里（见 :mod:`core.stop_key`），所以它只把「停」
    投递回事件循环，别的什么都不做：低层钩子的回调拖久了会被系统摘掉。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    def _stop_now() -> None:
        from core.desktop_presence_runtime import get_desktop_presence_runtime

        task = loop.create_task(get_desktop_presence_runtime().stop_current_activity(reason="stop_key"))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    def _fire() -> None:
        loop.call_soon_threadsafe(_stop_now)

    return _fire


class ActingMixin:
    """``RuntimeSession`` 的「此刻在不在动手」。见 :func:`core.liminal_activity.acting`。

    计数而不是布尔：电脑操作闭环里再调一次应用自动化是嵌套的两段，外层没结束内层先
    退出时不能把它报成「停了」。值挂在类上作默认（都是不可变的），第一次写时落到实例上。
    """

    _acting_depth: int = 0
    acting_reason: str = ""
    # 这一段动手有没有占着叫停键（core.stop_key 是按份计数的，占了几份就得还几份）。
    _holds_stop_key: bool = False

    @property
    def acting(self) -> bool:
        return self._acting_depth > 0

    def enter_acting(self, reason: str = "") -> None:
        self._acting_depth += 1
        if self._acting_depth == 1:
            self.acting_reason = reason
            # 开始动手：占叫停键（人按 Esc 能停）。占没占到由 core.stop_key 自己判断，
            # 渲染端只照 stop_key.label() 写 —— 这里不替它承诺。
            fire = _stop_key_callback()
            if fire is not None:
                _stop_key.acquire(fire)
                self._holds_stop_key = True

    def exit_acting(self) -> None:
        if self._acting_depth == 0:
            return
        self._acting_depth -= 1
        if self._acting_depth == 0:
            self.acting_reason = ""
            if self._holds_stop_key:
                self._holds_stop_key = False
                _stop_key.release()
