"""core/context_runway.py — 还能跑多远：从「现在多满」到「照这个烧法还剩几轮」
================================================================================

修的是什么
==========
油表（:func:`core.context_compaction.fuel_gauge`）解决了"模型看不见自己有多满"。
但"多满"是一个**水位**，而撞墙是一个**速率**问题 —— 两者不是一回事：

    第 9 轮：占用 58%   ← 水位触发器（七成）不响
    第 10 轮：一个工具返回了 30 KB 日志
    第 10 轮末：占用 118%  ← 已经被 llama.cpp 静默截断了

水位触发器**从来没有机会响**：它在 58% 和 118% 之间没有采样点。这不是把阈值从 0.7
调到 0.5 能解决的 —— 调低只是把同一个洞往前挪，遇到更大的单次增量照样跨过去。

缺的是另一个维度：**这一轮烧了多少、照这个烧法还能烧几轮**。水位管"现在"，跑道管
"还剩多远"，两个触发器盯的是不同的失败形态：

* 水位：慢慢涨上去 —— 多轮小增量累积；
* 跑道：一步跨过去 —— 单轮大增量。

烧率必须**量**，不能拍
======================
和这一系列其它几处一样：没人能凭空写出"一轮烧多少 token"。它取决于这个任务调什么
工具、工具返回多大、模型答多长。所以从**真实的消息列表增长**里量。

两条判据上的讲究
================
* **取最近几轮的最大值，不是平均。** 两个理由，第二个更要紧：

  1. 方向性后果不对称 —— 烧率估小 → 跑道估长 → **撞墙被静默截断**；估大 → 提前压
     一次 → 丢一点细节。取最大偏保守。
  2. **压缩会让占用大幅回落**，而均值会被那个负差值拉低 —— 烧率掉到接近 0、跑道
     变成"还能跑很远"，于是**压完一次就再也不压了**。取最大天然免疫：负增量再大也
     压不过正增量。这是个会自己失效的闭环，和 ``context_measurements`` 里那条
     "只记不受 n_ctx 反向约束的量"是同一类陷阱 —— 只是这里靠**选对聚合方式**避开，
     而不是靠一层额外的过滤。

  "最近几轮"则让它在任务节奏变了之后能降下来，不会被早期一个异常值永久钉死。

判不了就说判不了
================
观测点不足（刚开始几轮）、烧率算不出来、窗口未知 —— 一律返回"未知"，让调用方退回
只看水位。**不猜一个跑道出来**：一个编出来的"还能跑 20 轮"比没有更危险，因为模型
会据此决定不整理上下文。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("Galaxy.ContextRunway")

#: 烧率按最近几轮算。
#:
#: 太短会被单次波动带着跳，太长会让任务节奏变化反应不过来（前半程读文件、后半程
#: 纯推理，烧率差一个数量级）。取 5：够抹平一次波动，又能在几轮内跟上节奏变化。
BURN_WINDOW_ROUNDS = 5

#: 至少要有这么多次观测才敢给跑道。
#:
#: 两个观测点只能得到一个差值，那不是"速率"是"一个样本"。开局那几轮本来也离墙很远，
#: 少报一会儿跑道不损失什么；而报早了会拿一个噪声值去影响压缩决策。
MIN_OBSERVATIONS = 3

#: 跑道短到这个程度就该动手了 —— 与"轮"同单位。
#:
#: 取 2 而不是 1：压缩本身要花一次模型调用，而那次调用也要装进窗口。留到只剩 1 轮
#: 才压，压缩这一步自己就可能装不下 —— 这与 ``COMPACT_AT_UTILIZATION`` 取 0.7 而不是
#: 0.9 是同一个理由。
COMPACT_AT_ROUNDS_LEFT = 2


@dataclass(frozen=True)
class Runway:
    """还能跑多远。``rounds_left < 0`` 表示**判不了**（不是"还能跑无限远"）。"""

    rounds_left: int
    tokens_left: int
    burn_per_round: int

    @property
    def known(self) -> bool:
        return self.rounds_left >= 0

    @property
    def is_short(self) -> bool:
        """短到该动手了吗。**判不了时返回 False** —— 判不了不动手。"""
        return self.known and self.rounds_left <= COMPACT_AT_ROUNDS_LEFT

    def render(self) -> str:
        """给模型看的一句话；判不了就返回空串（不报假数）。"""
        if not self.known:
            return ""
        if self.rounds_left <= 0:
            return "，**下一轮就会溢出**，现在必须整理"
        if self.is_short:
            return f"，按每轮约 {self.burn_per_round} token 的烧法**只够再跑 {self.rounds_left} 轮**，该整理了"
        return f"，按每轮约 {self.burn_per_round} token 的烧法还能跑约 {self.rounds_left} 轮"


UNKNOWN = Runway(rounds_left=-1, tokens_left=0, burn_per_round=0)


def burn_per_round(marks: Optional[List[int]]) -> int:
    """从历次占用观测里算出每轮烧多少 token；判不了返回 0。

    *marks* 是每轮结束时的占用量（token），按时间先后排列。

    过滤掉非正增量这一步，在当前实现下**与 ``max`` 冗余**（负数再大也压不过正数），
    所以没有任何输入能把它与"不过滤"区分开 —— 反向验证时把它拆掉，一条测试都不红。
    留着是因为它把**意图**写死在代码里：一旦有人把 ``max`` 换成均值或分位数
    （很自然的一次重构），它立刻从冗余变成承重的，而那时压缩回落会把烧率拉塌。
    真正在挡这件事的是上面那个 ``max``，见模块文档。
    """
    if not marks or len(marks) < MIN_OBSERVATIONS:
        return 0
    recent = marks[-(BURN_WINDOW_ROUNDS + 1) :]
    deltas = [b - a for a, b in zip(recent, recent[1:]) if b > a]
    if not deltas:
        # 全是零增量或负增量(刚压过 / 几轮没调工具)——这不是"烧率为 0"，是**这段时间
        # 没有可用于估计速率的样本**。返回 0 让调用方退回只看水位。
        return 0
    return max(deltas)


def project(used_tokens: int, n_ctx: int, marks: Optional[List[int]] = None) -> Runway:
    """还能跑多远 —— 任何一项算不出来就返回 :data:`UNKNOWN`。

    Args:
        used_tokens: 当前占用（应当已含回复留白，与油表同口径）。
        n_ctx:       窗口大小，取自 ``ComputeScheduler.context_budget_for``。
        marks:       历次占用观测，见 :func:`burn_per_round`。
    """
    if n_ctx <= 0 or used_tokens < 0:
        return UNKNOWN
    burn = burn_per_round(marks)
    if burn <= 0:
        return UNKNOWN
    left = max(0, n_ctx - used_tokens)
    return Runway(rounds_left=left // burn, tokens_left=left, burn_per_round=burn)


def record_mark(marks: List[int], used_tokens: int) -> List[int]:
    """记一次占用观测，返回**原地更新后**的列表（只保留够用的那几个）。

    只留 ``BURN_WINDOW_ROUNDS + 1`` 个：多留没用（算烧率只看最近几轮），而一个会
    随会话无限增长的列表本身就是一处泄漏。
    """
    marks.append(int(used_tokens))
    del marks[: max(0, len(marks) - (BURN_WINDOW_ROUNDS + 1))]
    return marks
