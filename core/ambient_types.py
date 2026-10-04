"""core/ambient_types.py — 常驻注意力循环的数据类型（叶子模块）
=================================================================

三选一决策（``AmbientDecision``）、一拍观察的输入快照（``AmbientObservation``）与决策脑的
协议（``AmbientDecider``）。

为什么单独成模块
----------------
这几个类型原先和循环、决策脑写在 ``core/ambient_attention_loop.py`` 一个文件里。治理层
（:mod:`core.ambient_governance`）要构造「降级后的沉默决策」，决策脑
（:mod:`core.ambient_decider`）要读观察、产出决策 —— 三方都依赖这几个类型，却谁也不该反过来依赖
循环本体，否则就是循环 import。放成叶子模块，三方各自单向依赖它。

``core.ambient_attention_loop`` 仍然把这些名字再导出，仓内与测试里既有的
``from core.ambient_attention_loop import AmbientAction`` 一行都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

#: 每次决策带上的最近记忆条数
RECENT_MEMORY_N = 5


# ---------------------------------------------------------------------------
# 三选一决策
# ---------------------------------------------------------------------------
class AmbientAction(str, Enum):
    """注意力头的三选一——即"这一拍主体该处于哪个存在状态"的具象化。"""

    SPEAK = "speak"  # 值得主动开口 → MANIFEST
    SILENT = "silent"  # 看到了但不打扰 → 留在 SILENT（应是绝大多数情况）
    DELEGATE = "delegate"  # 该派活儿而非嘴上说 → LIMINAL 执行分支


@dataclass
class AmbientDecision:
    """一次注意力决策的结构化结果。"""

    action: AmbientAction
    rationale: str = ""  # 为什么这么决定（记录 + 面板显示）
    utterance: str = ""  # SPEAK 时要说的话
    task: str = ""  # DELEGATE 时要委托的任务
    salient: bool = False  # 是否值得写入终身记忆

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "rationale": self.rationale,
            "utterance": self.utterance,
            "task": self.task,
            "salient": self.salient,
        }


@dataclass
class AmbientObservation:
    """一拍观察的输入快照。

    frame_b64 是【主帧】(屏幕优先、否则摄像头)——供门控/记忆/路由沿用,保持兼容。
    screen_b64 / camera_b64 是【分路】原始帧:决策脑同时把两路都发给模型(融合看),
    修复"在场循环每拍只看一路视觉"的缺陷。两者可同时存在(屏幕+摄像头都在采)。
    """

    frame_b64: Optional[str] = None
    frame_mime: str = "image/jpeg"
    frame_source: str = ""
    screen_b64: Optional[str] = None
    screen_mime: str = "image/jpeg"
    camera_b64: Optional[str] = None
    camera_mime: str = "image/jpeg"
    audio_b64: Optional[str] = None
    audio_mime: str = "audio/webm"
    audio_transcript: Optional[str] = None  # 听:能力驱动桥接转写(asr_bridge)后的文字
    screen_meta: Optional[Dict[str, Any]] = None
    recent_memory: List[str] = field(default_factory=list)
    #: 手表报上来的「现在能不能打扰他」(见 core/interruptibility_registry)。
    #: 空串 = 没有可用证据 —— 注意「没有证据」既不构成放行、也不构成阻拦,
    #: 此时循环的行为与接手表之前完全一致。
    interruptibility_note: str = ""


# ---------------------------------------------------------------------------
# 决策脑接口（可插拔：档位 A 用 Gemma 系主脑；档位 B 换 MiniCPM-o 全模态，循环不改）
# ---------------------------------------------------------------------------
class AmbientDecider(Protocol):
    async def decide(self, obs: AmbientObservation) -> AmbientDecision:  # pragma: no cover - 协议
        ...
