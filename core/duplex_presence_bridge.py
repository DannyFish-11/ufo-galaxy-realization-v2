"""core.duplex_presence_bridge — 把实时双工语音接回统一主体
=============================================================

问题:双工是一条**绕过中心**的旁路
-----------------------------------
``core.voice_duplex_session`` 开的是一条直连模型服务商的实时 WebSocket:音频上行、
音频下行,模型自己听、自己想、自己说。它跑起来的时候,``core.voice_loop`` 甚至**不再
初始化 ASR/TTS**(见 ``VoiceLoop.start`` 里那句提前 return)。

好处是延迟极低 —— 这正是要双工的原因。代价是它把统一主体绕开了整整三件事:

1. **三态**:``DesktopPresenceRuntime`` 全程不知道有会话在开。用户一直在跟它说话,
   外壳显示的却是静默 —— 主体在听,壳子说它睡着了。
2. **中心的控制权**:没有任何入口能从中心把这条会话停掉。统一主体里不该存在一条
   中心叫不停的常驻通路。
3. **记忆与上下文**:用户在双工里说的话只存在于那条 WebSocket 里。切回文字对话、
   换到手机、事后回看,全都查无此话 —— 同一个主体对同一段对话失忆。

本模块补这三条,分别对应 A1 / A2 / A3。

不做什么(同样重要)
--------------------
**不**把双工里的话再送进 ``handle_request`` 跑一遍。实时模型已经在回答了;再走一遍
中心的认知-执行链会得到**第二个回复**,用户会听见两次。所以 A3 的正确形状是
**旁录(observe)而非重放(replay)**:把用户与助手的轮次按仓库既有的"轮次单写"
入口 ``core.session_memory_facade.record_session_turn`` 落进同一份会话记忆,并给
认知场发一个"有请求到了"的信号,让持续认知场的激活度真实反映"人正在跟我说话"。

于是记忆是一份、上下文是连贯的、外壳是活的,而回复仍然只有实时模型那一个。

线程/事件循环
--------------
``DuplexPresenceBridge`` 的方法都是协程,且只在双工下行消费协程里被 await,
与 ``VoiceLoop`` 同一个事件循环。唯一的例外是 :meth:`close`,它也可能被
``VoiceLoop.stop()`` 调用 —— 同样在那个循环里。没有跨线程调用,因此不需要
``run_coroutine_threadsafe``。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("Galaxy.DuplexPresenceBridge")

#: 助手侧增量文本的累积上限。实时模型一次回复通常几百字;设上限只是防一条异常长的
#: 流把内存吃掉,正常情况永远碰不到。
_ASSISTANT_BUFFER_MAX = 32_768


class DuplexPresenceBridge:
    """一条双工会话与统一主体之间的接线。

    生命周期与被桥接的 ``DuplexSession`` 一一对应::

        bridge = DuplexPresenceBridge(session, conversation_session_id=sid)
        await bridge.open()          # 主体进入并保持 LIMINAL
        ...                          # note_user_turn / note_assistant_* 随事件调用
        await bridge.close()         # 主体回到 SILENT

    幂等:``open`` / ``close`` 重复调用安全。
    """

    def __init__(
        self,
        session: Any,
        *,
        conversation_session_id: str = "",
        source: str = "voice_duplex",
        device_id: str = "",
        user_id: str = "",
    ) -> None:
        self._session = session
        self._source = source
        self._device_id = device_id
        self._user_id = user_id
        # 会话 ID 缺省时自己造一个:没有它 record_session_turn 会直接 return,
        # 轮次就静默丢了 —— 那正是本模块要修的毛病,不能在自己身上重演。
        self._conversation_session_id = conversation_session_id or f"duplex-{int(time.time() * 1000):x}"
        self._handle: Optional[str] = None
        self._assistant_buffer: list = []
        self._closed = False

    # ── 属性 ────────────────────────────────────────────────────────────────

    @property
    def conversation_session_id(self) -> str:
        return self._conversation_session_id

    @property
    def presence_handle(self) -> Optional[str]:
        """常驻在场句柄;未开启时为 None。"""
        return self._handle

    # ── A1 + A2:在场与叫停 ─────────────────────────────────────────────────

    async def open(self) -> Optional[str]:
        """开启常驻在场(A1),并把叫停钩子交给中心(A2)。

        返回在场句柄;运行时不可用时返回 None 且**不抛出** —— 双工本身能不能跑
        不该取决于外壳在不在。
        """
        if self._handle is not None:
            return self._handle
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            runtime = get_desktop_presence_runtime()
            self._handle = runtime.open_ambient_presence(
                self._source,
                reason="realtime duplex voice session",
                on_halt=self._halt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("双工常驻在场开启失败(双工照常运行,外壳不更新): %s", exc)
            return None
        logger.info(
            "双工已接入统一主体 | handle=%s session=%s",
            self._handle,
            self._conversation_session_id,
        )
        return self._handle

    async def _halt(self) -> None:
        """中心叫停时执行:关掉那条实时 WebSocket。

        只关会话、不动在场登记 —— 回收由 ``halt_ambient_presence`` 负责,钩子
        在这里再去 close 一次在场会变成互相调用。
        """
        self._closed = True
        session = self._session
        if session is None:
            return
        try:
            await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("中心叫停双工:关闭会话失败: %s", exc)
            raise

    async def close(self) -> None:
        """持有方自己收摊:注销常驻在场,主体回到 SILENT。幂等、永不抛出。"""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        # 收尾时把还没落地的助手增量补写掉,否则最后一段回复会因为没等到
        # RESPONSE_DONE(用户直接挂断)而丢失。
        try:
            await self.note_assistant_done()
        except Exception as exc:  # noqa: BLE001
            logger.debug("双工收尾补写助手轮次失败(忽略): %s", exc)
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            get_desktop_presence_runtime().close_ambient_presence(handle)
        except Exception as exc:  # noqa: BLE001
            logger.warning("双工常驻在场关闭失败: %s", exc)

    # ── A3:意图回流中心 ────────────────────────────────────────────────────

    async def note_user_turn(self, text: str) -> None:
        """记下用户在双工里说的一句话(旁录,不触发第二次回复)。

        调用点应当是 ``FINAL_TRANSCRIPT`` **且被判定为真打断/正式发言**之后 ——
        应答性的"嗯""对"不该进记忆,它们不是内容。
        """
        text = (text or "").strip()
        if not text:
            return
        await self._record_turn("user", text)
        # 让持续认知场知道"人正在跟我说话"。没有这一下,双工期间认知场的激活度
        # 恒在自然衰减,外壳的呼吸强度会越说越弱 —— 与实际情形完全相反。
        try:
            from core.cognitive.cognitive_field_engine import get_cognitive_field_engine

            get_cognitive_field_engine().notify_request(trace_id=self._handle or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("双工 notify_request 跳过(非致命): %s", exc)

    def note_assistant_delta(self, text: str) -> None:
        """累积助手侧的增量文本。同步方法 —— 它在下行热路径上,不该有 await。"""
        if not text:
            return
        if sum(len(s) for s in self._assistant_buffer) < _ASSISTANT_BUFFER_MAX:
            self._assistant_buffer.append(text)

    async def note_assistant_done(self) -> None:
        """一个回复回合结束:把累积的助手文本作为一轮落进记忆。"""
        buffered = "".join(self._assistant_buffer).strip()
        self._assistant_buffer = []
        if not buffered:
            return
        await self._record_turn("assistant", buffered)

    async def _record_turn(self, role: str, content: str) -> None:
        """经仓库唯一的轮次写入口落盘。失败只记日志 —— 记忆写失败不该中断对话。"""
        try:
            from core.session_memory_facade import record_session_turn

            await record_session_turn(
                conversation_session_id=self._conversation_session_id,
                role=role,
                content=content,
                user_id=self._user_id,
                device_id=self._device_id,
                trace_id=self._handle or "",
                metadata={"channel": "realtime_duplex", "source": self._source},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("双工轮次写入记忆失败(对话继续) role=%s: %s", role, exc)
