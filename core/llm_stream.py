"""core/llm_stream.py — 真流式增量通道(token 流的请求级上下文)
=================================================================

把「LLM 边生成边吐字」从模型调用层一路送到消费端(SSE 面板 / 分句 TTS)的最小
管道。设计目标:

- **零签名侵入**:openclawd.process / handle_request 的深链一个参数都不用加。
  消费端(如 /chat/stream)用 :func:`use_stream` 在自己的请求上下文里挂一个
  :class:`TokenStream`;答案生成点(openclawd._react_loop)用
  :func:`current_stream` 取出来、显式传给适配器。走 ``contextvars``,同一请求
  链路内可见,跨请求/跨任务互不串扰。
- **只有"答案调用"会流出**:适配器只在被显式传入 ``stream=`` 时才流式。内部
  辅助 LLM 调用(意图分类/决策解析/记忆压缩…)拿不到 sink,内部推理绝不会
  泄漏到用户气泡。
- **可作废**:级联换档 / 路由故障转移 / 工具轮重启时,上游调 :meth:`TokenStream.reset`
  作废已流出的草稿;消费端(前端清空气泡、TTS 掐断已排队的句子)各自响应。
- **永不反噬**:回调异常全部吞掉,流式通道坏了最多退化成"整段一次到"的旧行为,
  绝不影响主调用链的正确性。
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger("Galaxy.LLMStream")

# ── 进程级活跃流登记 ────────────────────────────────────────────────────────
# contextvars 只在**本请求链路内**可见,外部（可观测面/流式主干状态）拿不到
# "现在有几路真的在流"。这里补一个进程级计数:use_stream 进出即增减,异常路径
# 由 finally 保证注销,绝不泄漏。它是"实时流真的在跑"的**唯一可证实证据**——
# 注意仅限本进程,跨进程看不到就是看不到（见 realtime_streaming_backbone 的
# scope 标注),绝不把"本进程没有"报成"系统没有"。
_registry_lock = threading.Lock()
_active_streams: set = set()
_stream_totals: Dict[str, int] = {"started": 0, "completed": 0}


def _register_stream(sink: "TokenStream") -> None:
    with _registry_lock:
        _active_streams.add(id(sink))
        _stream_totals["started"] += 1


def _unregister_stream(sink: "TokenStream") -> None:
    with _registry_lock:
        _active_streams.discard(id(sink))
        _stream_totals["completed"] += 1


def stream_registry_snapshot() -> Dict[str, Any]:
    """本进程 token 流的可观测快照（scope 明示为进程内）。"""
    with _registry_lock:
        return {
            "scope": "process_local",
            "active": len(_active_streams),
            "started_total": _stream_totals["started"],
            "completed_total": _stream_totals["completed"],
        }


class TokenStream:
    """增量文本接收器。

    Args:
        on_delta: 每段新生成文本的回调(同事件循环内调用,须快速非阻塞——
            典型实现是 ``queue.put_nowait``)。
        on_reset: 已流出内容被作废时的回调(级联升级/failover/工具轮)。
    """

    def __init__(
        self,
        on_delta: Callable[[str], None],
        on_reset: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_delta = on_delta
        self._on_reset = on_reset
        self.chars = 0  # 本段(自上次 reset 起)已流出的字符数
        self.total_chars = 0
        self.resets = 0

    def feed(self, text: str) -> None:
        """流出一段新文本。空串跳过;回调异常吞掉(不反噬生成主流程)。"""
        if not text:
            return
        try:
            self._on_delta(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TokenStream.on_delta 回调失败(忽略): %s", exc)
        self.chars += len(text)
        self.total_chars += len(text)

    def reset(self) -> None:
        """作废本段已流出的内容(消费端应清空对应展示/朗读队列)。"""
        self.resets += 1
        had = self.chars
        self.chars = 0
        if self._on_reset is None:
            return
        try:
            self._on_reset()
        except Exception as exc:  # noqa: BLE001
            logger.debug("TokenStream.on_reset 回调失败(忽略): %s", exc)
        if had:
            logger.debug("TokenStream reset:作废 %d 字符(第 %d 次)", had, self.resets)


# 请求级上下文:消费端挂 sink,生成点取 sink。默认 None = 无流式消费者。
_current: contextvars.ContextVar[Optional[TokenStream]] = contextvars.ContextVar(
    "galaxy_llm_token_stream",
    default=None,
)


def current_stream() -> Optional[TokenStream]:
    """取当前请求上下文里挂的 TokenStream(没有则 None)。"""
    try:
        return _current.get()
    except Exception:  # noqa: BLE001
        return None


@contextlib.contextmanager
def use_stream(sink: Optional[TokenStream]) -> Iterator[None]:
    """在 with 块内把 sink 挂为当前请求的令牌流(块结束自动还原)。"""
    token = _current.set(sink)
    if sink is not None:
        with contextlib.suppress(Exception):
            _register_stream(sink)
    try:
        yield
    finally:
        # 注销必须在 finally:异常/取消路径也不能把活跃计数留成幽灵。
        if sink is not None:
            with contextlib.suppress(Exception):
                _unregister_stream(sink)
        with contextlib.suppress(Exception):
            _current.reset(token)
