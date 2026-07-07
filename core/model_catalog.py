"""core/model_catalog.py — 模型目录单一真相源（SSOT）+ 能力模型 + AB 档位
================================================================================

系统性一体化的地基。此前"可选模型清单"在仓库里硬编码了 **三份**且必须手动
同步：

  1. core/model_selection.py    的 ``_CHOICE_ORDER`` / ``_LABELS``
  2. electron/.../ModelsTab.tsx  的 ``LOCAL_BRAINS``
  3. core/routes/config.py       的 ``OLLAMA_MODEL.options``

漏改一处就漂移（"面板能选后端不认"）。本模块把它们收敛成**唯一**来源：模型
规格、能力、尺寸、以及 A/B 两档的构成都在这里定义，其余全部**派生**。

能力驱动（capability-driven）
-----------------------------
每个模型显式声明 4 项能力：

  vision     看  —— 原生图像理解
  audio_in   听  —— 原生音频理解（不经 ASR 转文字）
  audio_out  说  —— 原生语音合成（不经外挂 TTS）
  tools      工具调用

对一个"档位"（可能同时跑多个模型）求**有效 IO**：某能力只要档内任一模型原生
支持即为 native；否则回退到桥接——听回退 ``asr_bridge``（faster-whisper 转文字），
说回退 ``tts_bridge``（edge-tts）。上层（ambient/voice loop）据此决定"直接用原生"
还是"接上 ASR/TTS"，无需在业务代码里写死某个模型能不能听/说。

档位（tiers）
-------------
  A 档  Gemma 4 系（单选）        —— 看 + 听(原生) + 工具；说走 TTS 桥
  B 档  MiniCPM-o 4.5（单选）     —— 看 + 听 + 说 全原生（需显卡）

云端不单列为一档：多模态云端 API（Gemini/GPT-4o/Claude…）由 core.multi_llm_router
作为**始终在线的高端兜底**（见其 PROPRIETARY 提供商），任何档位在本地不可用/能力
不足时自动降级到云端。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.ModelCatalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TIER_FILE = PROJECT_ROOT / ".galaxy_tier"


# ---------------------------------------------------------------------------
# 能力与模型规格
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelCapability:
    vision: bool = False      # 看
    audio_in: bool = False    # 听（原生音频理解）
    audio_out: bool = False   # 说（原生语音合成）
    tools: bool = False       # 工具调用

    def to_dict(self) -> Dict[str, bool]:
        return {"vision": self.vision, "audio_in": self.audio_in,
                "audio_out": self.audio_out, "tools": self.tools}


@dataclass(frozen=True)
class ModelSpec:
    tag: str                  # Ollama tag 或容器模型标识
    name: str                 # 人类可读名
    desc: str                 # 模态/能力说明
    caps: ModelCapability
    source: str = "local"     # local(Ollama) | container(vLLM 容器) | cloud
    requires_gpu: bool = False

    def size_mb(self) -> int:
        """尺寸(MB)取自 LocalBrainManager（单一真相源）；未知返回 0。"""
        try:
            from core.local_brain_manager import LocalBrainManager
            return int(LocalBrainManager.MODEL_SIZE_ESTIMATE_MB.get(self.tag, 0))
        except Exception:  # noqa: BLE001
            return 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "tag": self.tag, "name": self.name, "desc": self.desc,
            "source": self.source, "requires_gpu": self.requires_gpu,
            "size_mb": self.size_mb(), "caps": self.caps.to_dict(),
        }


# ── 模型规格表（唯一定义处）───────────────────────────────────────────────────
# Gemma 4 系：原生看 + 原生听，但不原生说（说走 TTS 桥）。
# MiniCPM-o 4.5：看/听/说全原生（全模态，需显卡）。
_MODELS: Dict[str, ModelSpec] = {
    "gemma4:e2b": ModelSpec(
        "gemma4:e2b", "Gemma 4 · E2B", "看 · 听(原生) · 轻量",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local", requires_gpu=False,
    ),
    "gemma4:e4b": ModelSpec(
        "gemma4:e4b", "Gemma 4 · E4B", "看 · 听(原生) · 中等显存",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local", requires_gpu=False,
    ),
    "gemma4:12b": ModelSpec(
        "gemma4:12b", "Gemma 4 · 12B", "看 · 听(原生) · 工具 · 128K",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local", requires_gpu=True,
    ),
    "openbmb/minicpm-o4.5": ModelSpec(
        "openbmb/minicpm-o4.5", "MiniCPM-o 4.5", "全模态 看/听/说 全原生(需显卡)",
        ModelCapability(vision=True, audio_in=True, audio_out=True, tools=True),
        source="local", requires_gpu=True,
    ),
}


# ---------------------------------------------------------------------------
# 档位
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    key: str                  # "A" | "B"
    label: str
    desc: str
    kind: str                 # "single" | "composite"
    model_tags: List[str] = field(default_factory=list)
    # single 档内可在多个候选里选一个作主脑（如 A 档 Gemma 三选一）；
    # composite 档全部同时运行（保留字段以便将来扩展，当前无复合档）。


_TIERS: Dict[str, Tier] = {
    "A": Tier(
        "A", "A 档 · 轻量本地", "Gemma 4 系：看 + 听(原生)，说走 TTS 桥；无独显也能跑",
        "single", ["gemma4:e2b", "gemma4:e4b", "gemma4:12b"],
    ),
    "B": Tier(
        "B", "B 档 · 全模态单模型", "MiniCPM-o 4.5：看/听/说 全原生(需显卡)",
        "single", ["openbmb/minicpm-o4.5"],
    ),
}

_DEFAULT_TIER = "A"
_TIER_KEYS = ("A", "B")


# ---------------------------------------------------------------------------
# 查询 API（其余模块全部从这里派生，不再自带清单）
# ---------------------------------------------------------------------------
def all_models() -> List[ModelSpec]:
    return list(_MODELS.values())


def get_model(tag: str) -> Optional[ModelSpec]:
    if tag in _MODELS:
        return _MODELS[tag]
    root = tag.split(":")[0]
    for t, spec in _MODELS.items():
        if t.split(":")[0] == root:
            return spec
    return None


def all_tiers() -> List[Tier]:
    return [_TIERS[k] for k in _TIER_KEYS]


def get_tier(key: str) -> Optional[Tier]:
    return _TIERS.get((key or "").strip().upper())


def tier_models(key: str) -> List[ModelSpec]:
    tier = get_tier(key)
    if not tier:
        return []
    return [_MODELS[t] for t in tier.model_tags if t in _MODELS]


# ── 兼容旧接口：扁平候选清单（model_selection 派生用）──────────────────────────
def choice_order() -> List[str]:
    """所有本地可选主脑 tag，按档位 A→B、档内顺序展开、去重。

    取代 model_selection._CHOICE_ORDER 的硬编码。只含 source=local（Ollama 能
    直接 pull 的）；container 源(若将来再引入)不进"主脑单选"清单。
    """
    seen: set = set()
    out: List[str] = []
    for key in _TIER_KEYS:
        for spec in tier_models(key):
            if spec.source == "local" and spec.tag not in seen:
                seen.add(spec.tag)
                out.append(spec.tag)
    return out


def local_choice_options() -> List[str]:
    """config.py OLLAMA_MODEL.options 派生用（等同 choice_order）。"""
    return choice_order()


# ---------------------------------------------------------------------------
# 能力驱动：档位有效 IO
# ---------------------------------------------------------------------------
@dataclass
class EffectiveIO:
    """一个档位（含其全部活跃模型）对外呈现的有效多模态 IO 通路。"""

    vision: str      # "native" | "none"
    audio_in: str    # "native" | "asr_bridge"
    audio_out: str   # "native" | "tts_bridge"
    tools: bool

    def to_dict(self) -> Dict[str, object]:
        return {"vision": self.vision, "audio_in": self.audio_in,
                "audio_out": self.audio_out, "tools": self.tools}


def effective_io(model_tags: List[str]) -> EffectiveIO:
    """对给定活跃模型集合求有效 IO：某能力档内任一模型原生支持即 native，否则桥接。"""
    specs = [get_model(t) for t in model_tags]
    specs = [s for s in specs if s is not None]
    any_vision = any(s.caps.vision for s in specs)
    any_audio_in = any(s.caps.audio_in for s in specs)
    any_audio_out = any(s.caps.audio_out for s in specs)
    any_tools = any(s.caps.tools for s in specs)
    return EffectiveIO(
        vision="native" if any_vision else "none",
        audio_in="native" if any_audio_in else "asr_bridge",
        audio_out="native" if any_audio_out else "tts_bridge",
        tools=any_tools,
    )


def tier_effective_io(key: str) -> EffectiveIO:
    return effective_io([s.tag for s in tier_models(key)])


def active_effective_io() -> EffectiveIO:
    """当前已选档位的有效 IO —— ambient/voice loop 决定 native vs 桥接的入口。"""
    return tier_effective_io(load_tier())


# ---------------------------------------------------------------------------
# 档位持久化 + 与 OLLAMA_MODEL 的联动
# ---------------------------------------------------------------------------
def load_tier() -> str:
    """当前档位：GALAXY_MODEL_TIER 环境变量 > .galaxy_tier 文件 > 默认 A。"""
    env = os.environ.get("GALAXY_MODEL_TIER", "").strip().upper()
    if env in _TIERS:
        return env
    try:
        if _TIER_FILE.exists():
            saved = _TIER_FILE.read_text(encoding="utf-8").strip().upper()
            if saved in _TIERS:
                return saved
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_TIER


def save_tier(key: str, *, main_brain: Optional[str] = None) -> str:
    """持久化档位选择，并联动主脑 OLLAMA_MODEL。

    - single 档：主脑取 main_brain(若属于该档)否则档内第一个本地模型。
    - composite 档(当前无)：主脑取档内第一个【本地对话模型】。
    返回最终生效的主脑 tag。
    """
    key = (key or "").strip().upper()
    if key not in _TIERS:
        key = _DEFAULT_TIER
    try:
        _TIER_FILE.write_text(key, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("保存档位失败(非致命): %s", exc)
    os.environ["GALAXY_MODEL_TIER"] = key

    # 选主脑
    local_in_tier = [s.tag for s in tier_models(key) if s.source == "local"]
    chosen = ""
    if main_brain:
        # 显式指定了主脑 → 一律尊重,即便它不在本档的目录候选里(如用户通过 HF
        # 回退装的自定义 tag)。此前"不在档内候选就替换成档内第一个"会把用户刚在
        # 设置页选定的自定义模型静默改回 gemma4:e2b —— 一条真实的静默数据丢失路径。
        chosen = main_brain
    elif local_in_tier:
        chosen = local_in_tier[0]
    if chosen:
        os.environ["OLLAMA_MODEL"] = chosen
        try:
            from core.model_selection import save_choice
            save_choice(chosen)
        except Exception as exc:  # noqa: BLE001
            logger.debug("联动 save_choice 失败(非致命): %s", exc)
    return chosen


def infer_tier_from_model(tag: str) -> str:
    """由主脑 tag 反推所属档位（面板初始高亮用）。找不到归 A。"""
    spec = get_model(tag)
    real = spec.tag if spec else tag
    for key in _TIER_KEYS:
        if any(s.tag == real for s in tier_models(key)):
            return key
    return _DEFAULT_TIER


def catalog_snapshot() -> Dict[str, object]:
    """完整目录快照（API /catalog 返回体的核心；不含实时拉取状态）。"""
    current = load_tier()
    return {
        "current_tier": current,
        "tiers": [
            {
                "key": t.key, "label": t.label, "desc": t.desc, "kind": t.kind,
                "models": [m.to_dict() for m in tier_models(t.key)],
                "effective_io": tier_effective_io(t.key).to_dict(),
            }
            for t in all_tiers()
        ],
    }
