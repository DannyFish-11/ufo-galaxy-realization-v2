"""core.conversation_mainline —— 面板上那条上下文，是哪一条会话

声字同文
--------
它说出口的每一句话，同时就在那份上下文里：面板开着，字跟着声音出来；面板关了，
字也一句不少 —— 再打开时，从后端把**同一条会话**读回来，前后都齐。

面板只是这份上下文的一个视图，不是它的存储。所以「说话的地方」和「面板显示的
地方」必须是同一条会话。此前不是：

* 语音回合固定记进 ``session_id="voice"``（``launcher/services.py`` 的适配器）；
* 双工每开一次就自建一条 ``duplex-<时间戳>``（``DuplexPresenceBridge`` 的缺省）；
* 自发开口（自发注意力的 SPEAK）一句都不进会话历史，只进工作记忆的滚动日志；
* 面板只读它自己本地记着的那一条。

四处各记各的 —— 每一处都「记下了」，合起来却不是一份上下文：面板重开之后，
用嘴说过的、它自己开口说过的，都不在那里；而文字对话时模型拿到的上下文里，
也没有刚才语音里说过的话。

判据只有一份
------------
当前对话主线 = 最近活跃的那条**真实对话**，即
:meth:`core.session_manager.SessionManager.get_primary_session_id` 的定义
（排除 ambient/control/worker 等系统桶）。自发委托早就按它续主线
（``core.ambient_attention_loop._delegate``）；这里把同一条判据交给其余几处，
而不是各写一份「我觉得该记到哪儿」。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("Galaxy.ConversationMainline")

#: 还没有任何真实对话时，新开的主线挂在谁名下。
#:
#: 与面板发起对话时的身份**同源**：``/api/v1/chat/stream`` 不带 user_id，
#: ``core.session_identity`` 把 owner 推成 ``device::<device_id or 'default'>``。
#: 两处取同一个 owner，才落在同一套记忆里（见 core/memory_thread.py 的「按人划根」）。
DEFAULT_MAINLINE_OWNER = "device::default"


def mainline_session_id(*, create: bool = False) -> str:
    """当前对话主线的会话 id。

    Args:
        create: 还没有任何真实对话时，是否就地开一条。自发开口这类「它先说话」的
            场合要传 ``True`` —— 否则它说的第一句话无处可记，面板重开就没了。

    Returns:
        会话 id；拿不到（会话管理器不可用、或没有且不创建）时返回空串 —— 调用方
        据此退回自己原来的行为，而不是凭空编一个。
    """
    try:
        from core.session_manager import get_session_manager

        sm = get_session_manager()
        sid = sm.get_primary_session_id() or ""
        if sid or not create:
            return sid
        return sm.get_or_create_session_sync(DEFAULT_MAINLINE_OWNER, "").id
    except Exception as exc:  # noqa: BLE001 — 找不到主线不该拖垮说话
        logger.debug("对话主线解析失败(调用方退回原行为): %s", exc)
        return ""
