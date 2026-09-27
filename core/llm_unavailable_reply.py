"""core/llm_unavailable_reply.py — 一个模型都调不通时，回给用户的那句话。

``MultiLLMRouter.chat`` 在所有候选都失败后不抛异常，而是回一条说明（优雅降级）。
那句话原来只有一种写法：「所有 AI 服务暂时不可用（已尝试: …）」。可是有两种完全不同的情况：

* **试过、都失败了**：有配置好的提供商，但调用出错、被断路器拦下。这时列出试过哪些是有用的。
* **一个都没试**：没有任何可用的提供商 —— 没填 API Key，也没有本地模型。这时原来那句话会变成
  「（已尝试: ）」，括号里什么都没有，用户看不出到底缺什么。干净环境第一次启动就是这种情况。

两种情况分开说，第二种直接告诉用户该补什么。
"""

from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)

NOTHING_CONFIGURED_REPLY = (
    "还没有可用的 AI 服务：没有配置任何 API Key，也没有检测到本地模型。"
    "请在面板「全部设置」里填一个 API Key，或者启动 Ollama 并拉取模型，然后再试。"
)


def unavailable_reply(tried_providers: Sequence[str]) -> str:
    """给用户看的降级说明；同时记一条错误日志（原先由调用方记）。"""
    logger.error("所有提供商调用失败: %s", list(tried_providers))
    if not tried_providers:
        return NOTHING_CONFIGURED_REPLY
    return f"所有 AI 服务暂时不可用（已尝试: {', '.join(tried_providers)}），请检查 API Key 配置后重试。"


__all__ = ["NOTHING_CONFIGURED_REPLY", "unavailable_reply"]
