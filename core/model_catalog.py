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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.ModelCatalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 统一状态记录:档位 + 主脑 合成【一条】记录(此前 .galaxy_tier 与 .galaxy_model
# 分裂两存点 + OLLAMA_MODEL env 三写易漂移)。运行时 env(GALAXY_MODEL_TIER /
# OLLAMA_MODEL)从本记录派生导出。旧的两个文件仅做一次性迁移读入。
_STATE_FILE = PROJECT_ROOT / "runtime" / "model_state.json"
_LEGACY_TIER_FILE = PROJECT_ROOT / ".galaxy_tier"
_LEGACY_MODEL_FILE = PROJECT_ROOT / ".galaxy_model"


# ---------------------------------------------------------------------------
# 能力与模型规格
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelCapability:
    vision: bool = False  # 看（原生图像/静帧理解）
    audio_in: bool = False  # 听（原生音频理解）
    audio_out: bool = False  # 说（原生语音合成）
    tools: bool = False  # 工具调用
    video: bool = False  # 看视频（原生连续帧/视频流理解，区别于单张静帧 vision）

    def to_dict(self) -> Dict[str, bool]:
        return {
            "vision": self.vision,
            "audio_in": self.audio_in,
            "audio_out": self.audio_out,
            "tools": self.tools,
            "video": self.video,
        }


@dataclass(frozen=True)
class ModelSpec:
    tag: str  # Ollama tag 或容器模型标识
    name: str  # 人类可读名
    desc: str  # 模态/能力说明
    caps: ModelCapability
    source: str = "local"  # local(Ollama) | llama_cpp(本地 GGUF 文件) | container(vLLM) | cloud
    requires_gpu: bool = False
    size_mb_val: int = 0  # 尺寸(MB)——**本目录即 SSOT**,不再反向依赖 LocalBrainManager
    is_default: bool = False  # 默认主脑(LocalBrainManager.RECOMMENDED_MODELS['default'] 派生自此)
    #: MoE 架构:调度器据此尝试"注意力进显存、专家进内存"的拆分。
    #: **``None`` = 没人填过这一栏**，不是"确认不是 MoE" —— 两者的处置完全不同:
    #: 前者该退回命名惯例兜底，后者该到此为止。原来这里是 ``bool = False``，
    #: 把这两件事压成了同一个值，于是消费方 ``if flag is not None`` 这一支
    #: 永远走不到（见 :func:`resolve_is_moe`）。填过的条目写 True/False。
    is_moe: Optional[bool] = None

    def size_mb(self) -> int:
        """尺寸(MB)——本目录自己拥有(唯一真相源);未定义返回 0。"""
        return int(self.size_mb_val or 0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "tag": self.tag,
            "name": self.name,
            "desc": self.desc,
            "source": self.source,
            "requires_gpu": self.requires_gpu,
            "size_mb": self.size_mb(),
            "caps": self.caps.to_dict(),
        }


# ── 模型规格表（唯一定义处）───────────────────────────────────────────────────
# Gemma 4 系：原生看 + 原生听，但不原生说（说走 TTS 桥）。
# MiniCPM-o 4.5：看/听/说全原生（全模态，需显卡）。
_MODELS: Dict[str, ModelSpec] = {
    "gemma4:e2b": ModelSpec(
        "gemma4:e2b",
        "Gemma 4 · E2B",
        "看 · 听(原生) · 轻量",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local",
        requires_gpu=False,
        size_mb_val=1800,
    ),
    "gemma4:e4b": ModelSpec(
        "gemma4:e4b",
        "Gemma 4 · E4B",
        "看 · 听(原生) · 中等显存",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local",
        requires_gpu=False,
        size_mb_val=3000,
    ),
    "gemma4:12b": ModelSpec(
        "gemma4:12b",
        "Gemma 4 · 12B",
        "看 · 听(原生) · 工具 · 128K",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local",
        requires_gpu=True,
        size_mb_val=8000,
        is_default=True,
    ),
    "openbmb/minicpm-o4.5": ModelSpec(
        "openbmb/minicpm-o4.5",
        "MiniCPM-o 4.5",
        "全模态 看/听/说 全原生(需显卡)",
        ModelCapability(vision=True, audio_in=True, audio_out=True, tools=True),
        source="local",
        requires_gpu=True,
        size_mb_val=6000,
    ),
}


def default_model() -> str:
    """默认主脑 tag(标了 is_default 的那个)——LocalBrainManager 的默认从此派生。"""
    for s in _MODELS.values():
        if s.is_default:
            return s.tag
    return "gemma4:12b"


# ---------------------------------------------------------------------------
# 档位
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    key: str  # "A" | "B"
    label: str
    desc: str
    kind: str  # "single" | "composite"
    model_tags: List[str] = field(default_factory=list)
    # single 档内可在多个候选里选一个作主脑（如 A 档 Gemma 三选一）；
    # composite 档全部同时运行（保留字段以便将来扩展，当前无复合档）。


_TIERS: Dict[str, Tier] = {
    "A": Tier(
        "A",
        "A 档 · 轻量本地",
        "Gemma 4 系：看 + 听(原生)，说走 TTS 桥；无独显也能跑",
        "single",
        ["gemma4:e2b", "gemma4:e4b", "gemma4:12b"],
    ),
    "B": Tier(
        "B",
        "B 档 · 全模态单模型",
        "MiniCPM-o 4.5：看/听/说 全原生(需显卡)",
        "single",
        ["openbmb/minicpm-o4.5"],
    ),
}

_DEFAULT_TIER = "A"
_TIER_KEYS = ("A", "B")


# ---------------------------------------------------------------------------
# 查询 API（其余模块全部从这里派生，不再自带清单）
# ---------------------------------------------------------------------------
def all_models() -> List[ModelSpec]:
    return list(_MODELS.values())


#: MoE 权重的命名惯例：型号里带 ``moe``/``mixtral``，或用"总参-激活参"标注
#: （``qwen3-30b-a3b``、``mixtral-8x7b``）。
_MOE_ACTIVATED_PARAM_RE = re.compile(r"\d+b[-_]?a\d+b")


def resolve_is_moe(tag: str, model_path: str = "") -> bool:
    """这个型号是不是 MoE —— **判据只此一处**。

    两级，顺序不能反：

    1. **目录填过就以目录为准**（``is_moe`` 不是 ``None``）。人工确认过的
       结论优先于任何猜测，包括"确认它不是 MoE"。
    2. 没填过才看命名惯例。识别错的代价可控：误判为 MoE 只会让调度器多算一次
       拆分，拆不动就自然回落常规分支（见 ``ComputeScheduler._split_moe``）。

    之所以要收成一处：原来 ``local_model_backends`` 和 ``compute_scheduler``
    各判各的，而且 ``is_moe`` 是个默认 False 的 ``bool``，
    "没人填过"和"确认不是"取同一个值 —— 于是只要目录里查得到这个 tag
    （``get_model`` 还带 root 前缀松匹配），第 2 级就永远够不着。实测：
    ``qwen3-30b-a3b`` 单看名字判 True，一旦进了目录就变 False，
    MoE 专家卸载**静默失效**，现场只看到"模型带不动"。
    """
    spec = get_model(tag)
    flag = getattr(spec, "is_moe", None) if spec is not None else None
    if flag is not None:
        return bool(flag)
    blob = f"{tag} {os.path.basename(model_path or '')}".lower()
    if "moe" in blob or "mixtral" in blob:
        return True
    return bool(_MOE_ACTIVATED_PARAM_RE.search(blob))


def get_model(tag: str) -> Optional[ModelSpec]:
    if tag in _MODELS:
        return _MODELS[tag]
    root = tag.split(":")[0]
    for t, spec in _MODELS.items():
        if t.split(":")[0] == root:
            return spec
    # 临时挂载兜底(仅本进程,不进目录/快照/状态文件——见 register_ephemeral_spec)
    if tag in _EPHEMERAL:
        return _EPHEMERAL[tag]
    return None


# ── 临时挂载(验证用,绝不落库)────────────────────────────────────────────────
# 场景:验证一个新架构(如 MoE)能否被调度器正确拆分并加载,需要一个可查询的
# ModelSpec,但**不应**污染目录 SSOT —— 档位清单、面板选项、持久化状态都不该
# 因为一次验证而多出一个型号。故独立存放:只有 get_model 兜底可见,
# all_models/catalog_snapshot/choice_order 一概看不到,进程退出即消失。
_EPHEMERAL: Dict[str, ModelSpec] = {}


def register_ephemeral_spec(spec: ModelSpec) -> None:
    """临时登记一个型号(仅本进程可查,不进目录、不进快照、不写状态)。"""
    _EPHEMERAL[spec.tag] = spec


def clear_ephemeral_specs() -> None:
    """清空临时登记(测试收尾用)。"""
    _EPHEMERAL.clear()


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

    取代 model_selection._CHOICE_ORDER 的硬编码。含 source=local（Ollama 能直接
    pull 的）与 source=llama_cpp（本地 GGUF 文件，由 llama.cpp 后端加载，MoE 专家
    卸载只在这条路上可用）；container 源(若将来再引入)不进"主脑单选"清单。
    """
    seen: set = set()
    out: List[str] = []
    for key in _TIER_KEYS:
        for spec in tier_models(key):
            if spec.source in ("local", "llama_cpp") and spec.tag not in seen:
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

    vision: str  # "native" | "none"
    audio_in: str  # "native" | "asr_bridge"
    audio_out: str  # "native" | "tts_bridge"
    tools: bool
    video: str = "none"  # "native" | "frames_bridge" | "none"（视频：原生 / 抽帧走静帧 / 无）

    def to_dict(self) -> Dict[str, object]:
        return {
            "vision": self.vision,
            "audio_in": self.audio_in,
            "audio_out": self.audio_out,
            "tools": self.tools,
            "video": self.video,
        }


def effective_io(model_tags: List[str]) -> EffectiveIO:
    """对给定活跃模型集合求有效 IO：某能力档内任一模型原生支持即 native，否则桥接。

    video：任一模型原生支持连续帧 → native；否则若有静帧视觉能力 → frames_bridge
    （把视频抽成静帧走 vision 通路）；连静帧都没有 → none。
    """
    specs = [get_model(t) for t in model_tags]
    specs = [s for s in specs if s is not None]
    any_vision = any(s.caps.vision for s in specs)
    any_audio_in = any(s.caps.audio_in for s in specs)
    any_audio_out = any(s.caps.audio_out for s in specs)
    any_tools = any(s.caps.tools for s in specs)
    any_video = any(getattr(s.caps, "video", False) for s in specs)
    return EffectiveIO(
        vision="native" if any_vision else "none",
        audio_in="native" if any_audio_in else "asr_bridge",
        audio_out="native" if any_audio_out else "tts_bridge",
        tools=any_tools,
        video="native" if any_video else ("frames_bridge" if any_vision else "none"),
    )


def tier_effective_io(key: str) -> EffectiveIO:
    return effective_io([s.tag for s in tier_models(key)])


def active_effective_io() -> EffectiveIO:
    """当前已选档位的有效 IO —— ambient/voice loop 决定 native vs 桥接的入口。"""
    return tier_effective_io(load_tier())


# ---------------------------------------------------------------------------
# 档位持久化 + 与 OLLAMA_MODEL 的联动
# ---------------------------------------------------------------------------
def _read_state() -> Dict[str, str]:
    """读【一条】统一记录 {tier, main_brain};无则一次性迁移旧的 .galaxy_tier/.galaxy_model。"""
    import json

    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "tier": str(data.get("tier", "")).strip().upper(),
                    "main_brain": str(data.get("main_brain", "")).strip(),
                }
    except Exception:  # noqa: BLE001
        pass
    # 迁移:旧的两个分裂存点
    tier = ""
    brain = ""
    try:
        if _LEGACY_TIER_FILE.exists():
            tier = _LEGACY_TIER_FILE.read_text(encoding="utf-8").strip().upper()
    except Exception:  # noqa: BLE001
        pass
    try:
        if _LEGACY_MODEL_FILE.exists():
            brain = _LEGACY_MODEL_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        pass
    return {"tier": tier, "main_brain": brain}


def _write_state(tier: str, main_brain: str) -> None:
    """写【一条】统一记录,并派生导出运行时 env(GALAXY_MODEL_TIER / OLLAMA_MODEL)。"""
    rec = {"tier": (tier or "").strip().upper(), "main_brain": (main_brain or "").strip()}
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_STATE_FILE, rec, indent=None, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("保存模型状态失败(非致命): %s", exc)
    if rec["tier"]:
        os.environ["GALAXY_MODEL_TIER"] = rec["tier"]
    if rec["main_brain"]:
        os.environ["OLLAMA_MODEL"] = rec["main_brain"]  # 运行时主脑:派生导出


def load_tier() -> str:
    """当前档位：GALAXY_MODEL_TIER 环境变量 > 统一记录 > 默认 A。"""
    env = os.environ.get("GALAXY_MODEL_TIER", "").strip().upper()
    if env in _TIERS:
        return env
    saved = _read_state().get("tier", "")
    if saved in _TIERS:
        return saved
    return _DEFAULT_TIER


def main_brain() -> str:
    """当前主脑 tag：OLLAMA_MODEL 环境变量 > 统一记录 > ""。"""
    env = os.environ.get("OLLAMA_MODEL", "").strip()
    if env:
        return env
    return _read_state().get("main_brain", "")


def save_main_brain(tag: str) -> None:
    """持久化主脑到统一记录(档位保持现值,并派生 OLLAMA_MODEL)。是主脑写入的唯一门。"""
    if not tag:
        return
    _write_state(load_tier(), tag)


def save_tier(key: str, *, main_brain: Optional[str] = None) -> str:
    """持久化档位 + 主脑到【同一条】记录,返回最终生效的主脑 tag。

    - single 档：主脑取 main_brain(显式一律尊重,即便是 HF 回退装的自定义 tag)
      否则档内第一个本地模型。
    - 不再分别写 .galaxy_tier / .galaxy_model / 联动 save_choice —— 全收敛到一条记录。
    """
    key = (key or "").strip().upper()
    if key not in _TIERS:
        key = _DEFAULT_TIER
    local_in_tier = [s.tag for s in tier_models(key) if s.source == "local"]
    if main_brain:
        # 显式指定 → 一律尊重(此前"不在档内候选就替换成档内第一个"会把用户刚选定的
        # 自定义模型静默改回 gemma4:e2b —— 真实的静默数据丢失路径)。
        chosen = main_brain
    elif local_in_tier:
        chosen = local_in_tier[0]
    else:
        chosen = _read_state().get("main_brain", "")
    _write_state(key, chosen)
    # 档位联动:切 B 档 → 激活 MiniCPM-o 官方 server 原生听/说(依赖后台自动装、
    # server 探测就绪才注册);切 A 档 → 注销回落桥。best-effort,绝不拖垮切档。
    try:
        from core.native_modal import on_tier_changed

        on_tier_changed(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("档位原生后端联动跳过(不影响切档): %s", exc)
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
                "key": t.key,
                "label": t.label,
                "desc": t.desc,
                "kind": t.kind,
                "models": [m.to_dict() for m in tier_models(t.key)],
                "effective_io": tier_effective_io(t.key).to_dict(),
            }
            for t in all_tiers()
        ],
    }
