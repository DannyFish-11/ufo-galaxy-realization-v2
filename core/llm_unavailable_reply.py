"""core/llm_unavailable_reply.py — 一个模型都调不通时，回给用户的那句话。

``MultiLLMRouter.chat`` 在所有候选都失败后不抛异常，而是回一条说明（优雅降级）。
那句话原来只有一种写法：「所有 AI 服务暂时不可用（已尝试: …）」。可是有两种完全不同的情况：

* **试过、都失败了**：有配置好的提供商，但调用出错、被断路器拦下。这时列出试过哪些是有用的。
* **一个都没试**：没有任何可用的提供商 —— 没填 API Key，也没有本地模型。这时原来那句话会变成
  「（已尝试: ）」，括号里什么都没有，用户看不出到底缺什么。干净环境第一次启动就是这种情况。

两种情况分开说，第二种直接告诉用户该补什么。

「一个都没配」是一种**状态**，不是每次调用都出了错：真跑里一条对话消息要路由七八次（意图、正文、
记忆摘要……），原先每次都记一条 ERROR「没有可用的 LLM 提供商」+「所有提供商调用失败: []」，两分钟
几十条，还会上控制台。现在这件事每 10 分钟说一次（WARNING，``note_nothing_configured``），中间只记 debug。
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

logger = logging.getLogger(__name__)

#: 「一个都没配」多久提醒一次。
NOTHING_CONFIGURED_REMIND_S = 600.0
_last_noted = [0.0]


def note_nothing_configured() -> None:
    """没有任何可用的提供商 —— 每 ``NOTHING_CONFIGURED_REMIND_S`` 秒说一次，其余记 debug。"""
    now = time.monotonic()
    if _last_noted[0] and now - _last_noted[0] < NOTHING_CONFIGURED_REMIND_S:
        logger.debug("没有可用的 LLM 提供商(已提醒过)")
        return
    _last_noted[0] = now
    logger.warning("没有可用的 LLM 提供商:没填任何 API Key,也没有本地模型(面板「全部设置」里填一个 Key 或启动 Ollama)")


NOTHING_CONFIGURED_REPLY = (
    "还没有可用的 AI 服务：没有配置任何 API Key，也没有检测到本地模型。"
    "请在面板「全部设置」里填一个 API Key，或者启动 Ollama 并拉取模型，然后再试。"
)


def unavailable_reply(tried_providers: Sequence[str]) -> str:
    """给用户看的降级说明；试过却都失败时记一条错误日志（原先由调用方记）。"""
    if not tried_providers:
        note_nothing_configured()
        return NOTHING_CONFIGURED_REPLY
    logger.error("所有提供商调用失败: %s", list(tried_providers))
    return f"所有 AI 服务暂时不可用（已尝试: {', '.join(tried_providers)}），请检查 API Key 配置后重试。"


__all__ = ["NOTHING_CONFIGURED_REPLY", "note_nothing_configured", "unavailable_reply"]
