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
  C 档  双模型（复合，全部同时跑） —— 感知位 MiniCPM-o 4.5 + 推理位 Qwen3.6-35B-A3B

槽位（slots）
-------------
C 档把"一个本地主脑"拆成两只手：**感知位**看/听/说、常驻，决定「有没有事发生」；
**推理位**做长上下文与工具编排，按需唤起。两者都不是决策者——决策权威只有
``core/model_role_policy`` 里的 openclawd 一个（``assert_primary_authority()``
会对越权抛异常），模型是它调用的资源。

单模型档的那一个槽位角色是 ``both``，于是上层一律按角色问
（:func:`model_for_role`），**不必分"配了一个还是两个"两套写法**。

云端不在本目录里
----------------
云端 API 由 ``core.multi_llm_router`` 按**角色常驻归属**派发：``ROLE_BRAIN_HINTS``
里 critic / reviewer / reasoner / coordinator / planner / analyst 是
``prefer_local: False``——审核、推理、协调本来就派给云端，与本地装不装得下无关
（该模块原话：「本地做，云端审；不让云端强模型抢走 executor」）。所以它不是
"本地不够用才降级"的兜底档，本目录也就不给它排档位。
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
    #: 加载后实际占用的**加速器内存**(显存 / 核显共享内存),MB。
    #:
    #: 与 ``size_mb_val`` 是两码事,而且**两个方向都会差很远**:
    #:
    #: * 全模态模型 **大于**权重:MiniCPM-o 4.5 的 4bit 权重 6 GB,但跑起来还要
    #:   驮上视觉编码器、音频编码器与语音解码器,实测约 11 GB。
    #: * MoE 走专家卸载后 **小于**权重:35B-A3B 的 INT4 权重 18 GB,专家留内存、
    #:   只有激活的 3 B 上卡,显存实测约 7.3 GB。
    #:
    #: 所以显存准入必须问这一栏,不能问 ``size_mb``。原来只有一栏,MiniCPM-o
    #: 记 6000 → 8 GB 卡上准入判"放得下",加载到 11 GB 时 OOM,而且报错在加载
    #: **途中**不在准入处,现场看到的是"模型带不动"。
    #:
    #: ``0`` = 没人量过 → :meth:`runtime_mb` 退回权重大小(即历史行为,不臆造数字)。
    runtime_mb_val: int = 0

    def size_mb(self) -> int:
        """权重大小(MB)——下载量 / 磁盘占用 / mmap 量。未定义返回 0。"""
        return int(self.size_mb_val or 0)

    def runtime_mb(self) -> int:
        """跑起来占多少加速器内存(MB)——**显存准入只问这一处**。

        没量过(``runtime_mb_val`` 为 0)就退回权重大小:那是历史行为,保守但至少
        不是编出来的。量过的条目以量到的为准。
        """
        return int(self.runtime_mb_val or 0) or self.size_mb()

    def to_dict(self) -> Dict[str, object]:
        return {
            "tag": self.tag,
            "name": self.name,
            "desc": self.desc,
            "source": self.source,
            "requires_gpu": self.requires_gpu,
            "size_mb": self.size_mb(),
            "runtime_mb": self.runtime_mb(),
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
        # 权重 6 GB,但视觉/音频编码器与语音解码器都要一起驻留 → 实测约 11 GB。
        runtime_mb_val=11000,
    ),
    "qwen3.6:35b-a3b": ModelSpec(
        "qwen3.6:35b-a3b",
        "Qwen3.6 · 35B-A3B",
        "MoE 推理位:长上下文 · 工具编排(专家卸载,小显存可跑)",
        ModelCapability(vision=False, audio_in=False, audio_out=False, tools=True),
        # llama_cpp:专家卸载(--n-cpu-moe)只在这条加载路上可用,走 Ollama 拿不到。
        source="llama_cpp",
        requires_gpu=True,
        # INT4 权重 18 GB 走 mmap;专家留内存后显存驻留约 7.3 GB。
        size_mb_val=18000,
        runtime_mb_val=7300,
        is_moe=True,
    ),
}


def runtime_footprint_mb(tag: str) -> int:
    """这个型号跑起来占多少加速器内存(MB)——**准入判据的唯一入口**。

    目录外的型号(qwen2/llama3/… 这类只登记在 ``LocalBrainManager`` 兜底表里的)
    返回 0,由调用方自行退回它那张表。
    """
    spec = get_model(tag)
    return spec.runtime_mb() if spec is not None else 0


def default_model() -> str:
    """默认主脑 tag(标了 is_default 的那个)——LocalBrainManager 的默认从此派生。"""
    for s in _MODELS.values():
        if s.is_default:
            return s.tag
    return "gemma4:12b"


# ---------------------------------------------------------------------------
# 档位
# ---------------------------------------------------------------------------
#: 主脑槽位的角色。**决策权威不在这里** —— openclawd 才是唯一的 PRIMARY
#: (见 ``core/model_role_policy.py``)。槽位说的是"这个模型充当哪只手"。
SLOT_PERCEPTION = "perception"  # 感知位:看/听/说,常驻,决定"有没有事发生"
SLOT_REASONING = "reasoning"  # 推理位:长上下文/工具编排,按需唤起
SLOT_BOTH = "both"  # 单模型档:一个模型两只手都干


@dataclass(frozen=True)
class BrainSlot:
    """档内一个模型槽位:它是谁、干哪只手的活、落在哪块加速器、许不许被踢。"""

    role: str  # SLOT_PERCEPTION | SLOT_REASONING | SLOT_BOTH
    tag: str
    #: 落位提示:"auto" 交给调度器按硬件判;"cuda"/"intel_igpu" 是显式指定。
    #: 双模型同时跑时靠它把两个模型分到两块加速器上,避免互相抢同一块的显存。
    placement: str = "auto"
    #: 常驻:不许被显存压力下的 LRU 淘汰踢掉。
    #:
    #: 感知位必须常驻,理由不是"它重要",是**它被踢了就再也醒不来**:三态里
    #: silent→liminal 这一跳由它触发,而唤醒它的信号又只能由它自己看到/听到。
    #: 推理位没有这个问题 —— 它由 OpenClawd 显式唤起,踢掉了下次再加载即可。
    resident: bool = False


@dataclass(frozen=True)
class Tier:
    key: str  # "A" | "B" | "C"
    label: str
    desc: str
    kind: str  # "single" | "composite"
    #: 档内槽位——**档位构成的唯一定义处**。``model_tags`` 由它派生。
    #: single 档内可在多个候选里选一个作主脑(如 A 档 Gemma 三选一);
    #: composite 档全部同时运行,各据一个槽位。
    slots: List[BrainSlot] = field(default_factory=list)

    @property
    def model_tags(self) -> List[str]:
        """档内模型 tag(派生自 slots,顺序保持)。"""
        return [s.tag for s in self.slots]

    def slot_for(self, role: str) -> Optional[BrainSlot]:
        """取某个角色的槽位;单模型档一律返回那个唯一的槽位。

        「只选一个模型时两个角色指向同一个」这条就落在这里 —— 于是上层
        (路由/协商)可以一律按角色问,不必分「配了几个模型」两套写法。
        """
        for s in self.slots:
            if s.role == role:
                return s
        for s in self.slots:
            if s.role == SLOT_BOTH:
                return s
        return None

    def resident_tags(self) -> List[str]:
        """本档中不许被淘汰的模型 tag。

        single 档会把**全部候选**都列进来 —— 读作"这几个里哪个当了主脑,哪个就
        常驻",因为单模型档同时只会加载其中一个。调度器只对**已加载**的模型
        做淘汰,故这份宽列表不会误钉住没加载的候选。
        """
        return [s.tag for s in self.slots if s.resident]


def _single(tag: str, *, placement: str = "auto") -> BrainSlot:
    """单模型档的槽位:一个模型两只手都干,且它就是全部,自然常驻。"""
    return BrainSlot(SLOT_BOTH, tag, placement=placement, resident=True)


_TIERS: Dict[str, Tier] = {
    "A": Tier(
        "A",
        "A 档 · 轻量本地",
        "Gemma 4 系：看 + 听(原生)，说走 TTS 桥；无独显也能跑",
        "single",
        [_single("gemma4:e2b"), _single("gemma4:e4b"), _single("gemma4:12b")],
    ),
    "B": Tier(
        "B",
        "B 档 · 全模态单模型",
        "MiniCPM-o 4.5：看/听/说 全原生(需显卡)",
        "single",
        [_single("openbmb/minicpm-o4.5")],
    ),
    "C": Tier(
        "C",
        "C 档 · 双模型本地主脑",
        "感知位 MiniCPM-o 4.5(核显) + 推理位 Qwen3.6-35B-A3B(独显)，两块加速器分开吃",
        "composite",
        [
            # 感知位落核显:与推理位的独显互不抢显存,这正是双模型能同时在岗的前提。
            BrainSlot(SLOT_PERCEPTION, "openbmb/minicpm-o4.5", placement="intel_igpu", resident=True),
            BrainSlot(SLOT_REASONING, "qwen3.6:35b-a3b", placement="cuda", resident=False),
        ],
    ),
}

_DEFAULT_TIER = "A"
#: 默认仍是 A 档单模型 —— 加了 C 档不改变任何既有安装的行为。
_TIER_KEYS = ("A", "B", "C")


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


# ── 槽位查询：上层一律「按角色问」，不必分「配了几个模型」两套写法 ──────────────
def slot_for_role(role: str, tier_key: str = "") -> Optional[BrainSlot]:
    """当前(或指定)档里担任 *role* 的槽位;查不到返回 None。

    单模型档返回那个唯一槽位 —— 所以问"感知位是谁"和问"推理位是谁"得到同一个
    答案,与只配一个模型时的现有行为完全一致。
    """
    tier = get_tier(tier_key or load_tier())
    return tier.slot_for(role) if tier else None


def model_for_role(role: str, tier_key: str = "") -> str:
    """当前档里担任 *role* 的模型 tag;查不到返回 ""。

    single 档特殊:它的槽位是**候选**(A 档 Gemma 三选一),真正在跑的是用户选定的
    那一个。所以这里以 :func:`main_brain` 为准 —— 否则 A 档永远答成候选里的第一个
    (e2b),而用户可能选的是 12b,于是"按角色问"得到的答案和实际加载的模型不是同
    一个。只有 main_brain 落在本档之外(或没设)时才退回槽位。
    """
    key = tier_key or load_tier()
    tier = get_tier(key)
    if not tier:
        return ""
    if tier.kind == "single":
        current = main_brain()
        spec = get_model(current) if current else None
        if spec is not None and spec.tag in tier.model_tags:
            return spec.tag
    slot = tier.slot_for(role)
    return slot.tag if slot else ""


def resident_tags(tier_key: str = "") -> List[str]:
    """当前(或指定)档里**不许被淘汰**的模型 tag —— 调度器的钉住名单只问这一处。"""
    tier = get_tier(tier_key or load_tier())
    return tier.resident_tags() if tier else []


def is_resident(tag: str, tier_key: str = "") -> bool:
    """这个 tag 在当前档里是不是常驻(不许踢)。"""
    if not tag:
        return False
    spec = get_model(tag)
    real = spec.tag if spec else tag
    return real in resident_tags(tier_key)


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
    tier = _TIERS[key]
    local_in_tier = [s.tag for s in tier_models(key) if s.source == "local"]
    if tier.kind == "composite" and not main_brain:
        # 复合档没有"选一个"这回事,整档一起跑。但 OLLAMA_MODEL 这个派生量只能
        # 指一个 —— 它代表"文本主脑",即推理位。若按 local_in_tier 取第一个,
        # C 档会指到感知位(MiniCPM 是 source=local、推理位是 llama_cpp),于是
        # 所有走 OLLAMA_MODEL 的文本请求都落到感知位上。
        reasoning = tier.slot_for(SLOT_REASONING)
        if reasoning:
            main_brain = reasoning.tag
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
                "slots": [
                    {"role": s.role, "tag": s.tag, "placement": s.placement, "resident": s.resident} for s in t.slots
                ],
                "effective_io": tier_effective_io(t.key).to_dict(),
            }
            for t in all_tiers()
        ],
    }
