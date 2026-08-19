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
from typing import Dict, List, Optional, Tuple

from core.atomic_json import atomic_write_json
from core.speculative_draft import DraftSpec

logger = logging.getLogger("Galaxy.ModelCatalog")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 统一状态记录:档位 + 主脑 合成【一条】记录(此前 .galaxy_tier 与 .galaxy_model
# 分裂两存点 + OLLAMA_MODEL env 三写易漂移)。运行时 env(GALAXY_MODEL_TIER /
# OLLAMA_MODEL)从本记录派生导出。旧的两个文件仅做一次性迁移读入。
_STATE_FILE = PROJECT_ROOT / "runtime" / "model_state.json"
_LEGACY_TIER_FILE = PROJECT_ROOT / ".galaxy_tier"
_LEGACY_MODEL_FILE = PROJECT_ROOT / ".galaxy_model"


#: 没填过 ``max_ctx_val`` 的型号按多长算 —— 就是 ``LlamaCppBackend`` 原来写死的那个值。
#:
#: 定成"沿用旧常数"而不是定成一个更大的数，是为了让这一栏成为**纯加法**:没人填过的
#: 型号，上下文行为与加这一栏之前逐字节一致。要放开哪个型号，就去给它填 ``max_ctx_val``,
#: 而不是把这个默认值调大 —— 调大它等于替所有没量过的型号做主张。
DEFAULT_MAX_CTX = 4096

#: 上下文预算的下限。再挤也不能低于这个数,否则模型连系统提示 + 工具表都装不下,
#: 表现是"它怎么什么都记不住",而不是"显存不够"。
MIN_CTX = 2048


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
    #: 这个型号**最长能吃多少 token 上下文**。
    #:
    #: 原来这个数根本无处可写:加载器里写死 ``self._n_ctx = 4096``,一个常数,
    #: 既不知道模型能吃多长(Qwythos-9B 能吃 1M),也不知道显存够不够。于是
    #: **能力被写死的常数封顶**,而且封在哪儿没有任何一处说得出来。
    #:
    #: ``0`` = 没人填过 → :meth:`max_ctx` 退回 :data:`DEFAULT_MAX_CTX`(即原来那个
    #: 4096)。**没填过的型号行为一个字不变** —— 这一栏是加法,不是改法。
    max_ctx_val: int = 0
    #: 每 1K 上下文的 KV cache 要多少加速器内存(MB)。上下文预算的分母。
    #:
    #: 单列一栏而不是按层数/头数现算,理由与 ``runtime_mb_val`` 同:那几个结构参数
    #: 目录里一个都没有,现算等于在调用点上编。这一栏是**显式声明的假设**,
    #: 量过就填、没量过就是 0,而 0 会让上下文预算退回"只认模型上限、不敢按显存放大"。
    #:
    #: 注意 Qwythos 这类混合架构(3:1 线性注意力 + 全注意力)的 KV 增长远小于同尺寸
    #: 纯注意力模型 —— 更不该用一条通用公式套。
    kv_mb_per_1k_val: int = 0
    #: 这个型号有没有**草稿模型**可挂(投机解码)。见 :class:`core.speculative_draft.DraftSpec`。
    #:
    #: 与 ``source`` 正交:同一套机制只接得上一种后端(DFlash 接 llama.cpp、MTP 接
    #: Ollama),但"有没有草稿"是型号自己的属性,不是后端的。
    #:
    #: 默认 ``unknown`` 而不是 ``none``,与 ``is_moe`` 用 ``Optional[bool]`` 同一条:
    #: "没人查过"该去问,"确认没有"到此为止。**这一栏只回答存不存在,不回答值不值得**
    #: —— 后者只有真机 A/B 有资格回答,而且默认是没测过 → 不开。
    draft: DraftSpec = field(default_factory=DraftSpec.unknown)

    def max_ctx(self) -> int:
        """最长能吃多少 token；没填过退回 :data:`DEFAULT_MAX_CTX`。"""
        return int(self.max_ctx_val or 0) or DEFAULT_MAX_CTX

    def kv_mb_per_1k(self) -> int:
        """每 1K 上下文的 KV cache(MB)；``0`` = 没量过，调用方不得据此放大上下文。"""
        return int(self.kv_mb_per_1k_val or 0)

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
            "draft": self.draft.to_dict(),
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
        # Gemma 4 官方模型卡:E2B/E4B 上下文 128K。
        max_ctx_val=131072,
    ),
    "gemma4:e4b": ModelSpec(
        "gemma4:e4b",
        "Gemma 4 · E4B",
        "看 · 听(原生) · 中等显存",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local",
        requires_gpu=False,
        size_mb_val=3000,
        max_ctx_val=131072,
    ),
    "gemma4:12b": ModelSpec(
        "gemma4:12b",
        "Gemma 4 · 12B",
        "看 · 听(原生) · 工具 · 256K",
        ModelCapability(vision=True, audio_in=True, audio_out=False, tools=True),
        source="local",
        requires_gpu=True,
        size_mb_val=8000,
        # 12B 起是 256K(E2B/E4B 才是 128K)—— desc 里那句"128K"是旧的，一并改掉。
        max_ctx_val=262144,
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
        # 40960 —— 全模态模型里算短的,而且**比本仓库的装配上界还接近**。
        # 它是这一批里唯一真正可能被上下文卡住的型号,不是"没人填过"的 4096。
        max_ctx_val=40960,
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
        # 原生 262144;YaRN 可外推到 ~1M,但外推档要显式开且质量有代价,
        # 这里记**原生**上限 —— 目录填的是"不加特技就能吃多长"。
        max_ctx_val=262144,
    ),
    "qwythos-9b-v2": ModelSpec(
        "qwythos-9b-v2",
        "Qwythos · 9B v2",
        "稠密推理位:长上下文 · 工具编排(不需专家卸载,显存门槛低)",
        ModelCapability(vision=False, audio_in=False, audio_out=False, tools=True),
        source="llama_cpp",
        requires_gpu=True,
        # Q4_K_M 量化下的权重体积。**这个数是按 Q4_K_M 记的**,换量化必须跟着改:
        # Q8_0 约 9.5 GB、bf16 原始权重约 18 GB,拿这一栏去做准入,量化对不上就是
        # 一次"判成放得下、加载到一半 OOM"。
        size_mb_val=5600,
        # 权重 + KV + 运行时开销,按 DEFAULT_MAX_CTX 那档上下文估。
        runtime_mb_val=7000,
        # **明确不是 MoE**(而不是 None"没人填过")。它是 3:1 的线性注意力(SSM)+
        # 全注意力混合架构,稠密 —— 没有专家可卸,``--n-cpu-moe`` 对它没有意义。
        # 这一条正是它与 35B-A3B 的关键差别:35B 的显存账建立在专家卸载生效之上,
        # 而这一位不欠这张空头支票,装了标准 llama-cpp-python 就能跑。
        is_moe=False,
        # 它能吃 1M(YaRN rope-scaling)。填真实上限,能不能开到这么长由
        # ComputeScheduler.context_budget_for 按显存和实际装配量决定,不在这里封顶。
        max_ctx_val=1048576,
        # **没量过**。混合架构的 KV 增长远小于同尺寸纯注意力模型,套通用公式会
        # 高估一大截;而高估的后果是白白把上下文压小。量一次填进来即可,
        # 在此之前上下文预算不会拿显存去放大它(见 ModelSpec.kv_mb_per_1k)。
        kv_mb_per_1k_val=0,
        # 草稿位:**自带 MTP 头**,不外挂 DFlash 检查点。
        #
        # 上游的 DFlash 检查点表里没有这一位(那张表是 Qwen / Gemma 4 / MiniMax /
        # Kimi / GPT-OSS / Llama-3.1 / GLM 这几家),而这个型号的 GGUF 据称把 MTP 头
        # 保留了下来,走 llama.cpp 的 ``--spec-type draft-mtp``。
        #
        # 对 D 档这是**更好的形状**:不用下第二份权重,显存账上没有"多一个模型"
        # 这一项(多出来的只是多验几个 token 的激活,跟着上下文预算走)。
        #
        # **"据称"这两个字是认真的**:这一栏只声明"可能挂得上",真有没有那个头、
        # 开了是快是慢,一律由 ``scripts/probe_models.py --draft`` 在真机上问。
        # 公开实测里同一件事既有 +2.69× 也有净 −44.6%,方向取决于机器不取决于代码。
        draft=DraftSpec(
            mechanism="mtp_self",
            note="GGUF 据称保留 MTP 头(--spec-type draft-mtp);是否真有、开了值不值得,由真机 A/B 判定",
        ),
    ),
}


#: ``source`` → 加载它要用哪个后端。**判据只此一处**。
#:
#: 原来这条散在 ``compute_scheduler.reconcile_tier`` 的调用点上
#: (``"llama_cpp" if spec.source == "llama_cpp" else "ollama"``)。只有一个调用点
#: 时看不出问题;可一旦别处也要问"这个型号归谁加载"(比如状态盘要报"加载它的
#: 运行时装没装"),就会各写各的,然后在某个 source 上分家。
BACKEND_BY_SOURCE: Dict[str, str] = {
    "local": "ollama",
    "llama_cpp": "llama_cpp",
    "container": "vllm",
}


def backend_for_source(source: str) -> str:
    """这个 source 的模型由哪个后端加载;不认识的一律按 ollama。"""
    return BACKEND_BY_SOURCE.get((source or "").strip(), "ollama")


def backend_for_tag(tag: str) -> str:
    """这个 tag **实际**由哪个后端加载(查不到目录时按 ollama)。

    静态部分是 ``source`` 映射。之上有一条**动态修正**:``llama_cpp`` 这条进程内的
    路做不到某些型号需要的东西时,改判 ``llama_server``。

    为什么修正要在这里,而不是在加载处
    ==================================
    因为问这句话的不止加载处。``core.runtime_readiness`` 拿它去判"这一档跑不跑得
    起来" —— 如果它得到的是 ``llama_cpp``,而真正会去干活的是 ``llama_server``,
    那么状态盘检查的就是错的那个后端:llama-server 装好了它仍然报"跑不起来",
    或者反过来,llama-cpp-python 装着就报"没问题"而实际那条路做不到卸载。

    修正只在**确实做不到**时发生 —— 见 :func:`in_process_cannot_serve`。
    """
    spec = get_model(tag)
    static = backend_for_source(spec.source if spec is not None else "")
    if static != "llama_cpp":
        return static
    return "llama_server" if in_process_cannot_serve(tag) else "llama_cpp"


def in_process_cannot_serve(tag: str) -> bool:
    """进程内那条路**做不到**这个型号需要的东西吗。

    两件事只要有一件成立就算做不到,而且都只在 CLI/server 旗标上存在:

    1. **专家卸载**(``--n-cpu-moe``)—— 只有当这个型号的显存账确实建立在卸载上
       (MoE 且 ``runtime_mb < 整权重``)时才算需要。不需要的型号不该被拖去起服务。
    2. **草稿位**(``--spec-type``)—— 目录声明了机制且真机实测为正时才算需要。

    判定要"另一条路做得到"才回 True:两条都做不到时改判 ``llama_server`` 毫无意义,
    只会把一个"装不下"的问题伪装成"后端没装"。
    """
    spec = exact_model(tag)
    if spec is None or spec.source != "llama_cpp":
        return False
    try:
        from core.llama_server import server_draft_supported, server_moe_offload_supported  # noqa: PLC0415
        from core.local_model_backends import binding_moe_offload_supported  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — 问不出来就别改判
        logger.debug("后端能力问不出来,保持进程内: %s", exc)
        return False

    # 每一次探测都各自兜住:它们要起子进程 / 读文件,任何一个抛出来都会顺着
    # backend_for_tag 传到 runtime_readiness 与调度器 —— 把一次能力探测的小毛病
    # 变成状态盘整个崩掉。问不出来的正确处置是**保持现状**(继续走进程内),
    # 而不是让调用方去处理一个它管不了的异常。
    try:
        if resolve_is_moe(tag) and spec.runtime_mb() < effective_weight_mb(tag):
            if not binding_moe_offload_supported() and server_moe_offload_supported():
                return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("专家卸载能力问不出来,保持进程内: %s", exc)
    try:
        from core.speculative_draft import is_enabled  # noqa: PLC0415

        if is_enabled(tag) and server_draft_supported():
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("草稿位判据不可用,不据此改判后端: %s", exc)
    return False


def runtime_footprint_mb(tag: str) -> int:
    """这个型号跑起来占多少加速器内存(MB);目录里没有这一条就返回 0。

    目录外的型号(qwen2/llama3/… 这类只登记在 ``LocalBrainManager`` 兜底表里的)
    返回 0,由调用方自行退回它那张表。

    **这里必须精确查表,不能走** :func:`get_model` **的同家族兜底。** 那条兜底
    对"这个家族由哪个后端加载"是对的(见 :func:`backend_for_tag`),对显存却是错的:
    ``get_model("gemma4:31b")`` 查不到就退回同家族的第一条 ``gemma4:e2b``,于是
    一个 31B 型号会被答成 1800 MB —— 拿这个数去做准入,等于把放不下的模型判成
    放得下,加载到一半必 OOM。**猜错的数字比没有数字更危险**,所以查不到就说查不到。
    """
    spec = exact_model(tag)
    return spec.runtime_mb() if spec is not None else 0


def exact_model(tag: str) -> Optional[ModelSpec]:
    """**精确**查目录,查不到返回 None —— 显存口径一律走这里,不走 :func:`get_model`。

    与 :func:`get_model` 的差别只有一条:那个查不到会退回**同家族的第一条**。
    家族兜底对"由哪个后端加载"是对的(同家族同后端),对显存是错的(同家族的
    2B 和 31B 差一个数量级)。凡是拿去和显存比大小的数,都必须从这里取。
    """
    return _MODELS.get(tag) or _EPHEMERAL.get(tag)


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
    """档内一个模型槽位:它干哪只手的活、**有哪些型号可选**、落在哪、许不许被踢。

    槽位持有的是**候选表**而不是单个型号 —— 这就是"可插拔"的落点:换型号是在
    同一个槽位里换一个候选,角色、落位、常驻策略、以及上层怎么问它,全都不变。
    """

    role: str  # SLOT_PERCEPTION | SLOT_REASONING | SLOT_BOTH
    #: 本位可选的型号,**第一个是默认**。单元素即"这一位没得挑"。
    candidates: List[str] = field(default_factory=list)
    #: 落位提示:"auto" 交给调度器按硬件判;"cuda"/"intel_igpu" 是显式指定。
    #: 双模型同时跑时靠它把两个模型分到两块加速器上,避免互相抢同一块的显存。
    placement: str = "auto"
    #: 常驻:显存告急时最后才考虑淘汰它。
    #:
    #: **常驻的是推理位,不是感知位** —— 判据是"重载代价",不是"谁更重要":
    #:
    #: * 推理位 35B-A3B:18 GB 权重走 mmap,还要重算专家卸载拆分(``_split_moe``),
    #:   重载一次几十秒起。踢掉它等于把最贵的那步重做一遍。
    #: * 感知位:最小的 Gemma 4 E2B 只有 1.8 GB,而且
    #:   ``core/ambient_attention_loop.py`` 的心跳每 tick 都会再要它一次
    #:   (Ollama 的 /api/chat 按需加载)。踢掉它的代价只是下一拍重载。
    #:
    #: 早先这一栏是反的,理由写的是"感知位被踢了就再也醒不来"。那句话说重了:
    #: 常驻心跳就是把它拉回来的人,它并不需要靠钉住来保命。
    resident: bool = False

    @property
    def tag(self) -> str:
        """本位的默认型号(候选表第一个)。没选过时用它。"""
        return self.candidates[0] if self.candidates else ""

    def accepts(self, tag: str) -> bool:
        """这个型号能不能插进本位。"""
        return bool(tag) and tag in self.candidates


@dataclass(frozen=True)
class Tier:
    key: str  # "A" | "B" | "C"
    label: str
    desc: str
    kind: str  # "single" | "composite"
    #: 档内槽位——**档位构成的唯一定义处**。
    #: single 档只有一个 ``both`` 位(候选里选一个当主脑);
    #: composite 档每个角色一位,各自可在自己的候选里换。
    slots: List[BrainSlot] = field(default_factory=list)

    @property
    def model_tags(self) -> List[str]:
        """档内**全部候选** tag(派生自 slots,顺序保持、去重)。

        注意这是"可选清单",不是"正在跑的清单" —— 后者见
        :func:`active_tags`。能力聚合、换档加载、常驻判定一律要用后者,
        否则 C 档会把没选中的候选也算进能力里(比如选了 Gemma 却报"说=原生")。
        """
        seen: set = set()
        out: List[str] = []
        for s in self.slots:
            for t in s.candidates:
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        return out

    def slot_for(self, role: str) -> Optional[BrainSlot]:
        """取某个角色的槽位;单模型档一律返回那个唯一的 ``both`` 位。

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


def _single(*candidates: str, placement: str = "auto") -> BrainSlot:
    """单模型档的那一位:一个模型两只手都干,候选里选一个。"""
    return BrainSlot(SLOT_BOTH, list(candidates), placement=placement, resident=True)


#: C 档感知位的候选。**这就是"上面那位随便换"的清单**。
#: 换谁都跟推理位一块儿跑,上层不用改一行 —— ``effective_io`` 按 ``any(...)``
#: 聚合能力,选了 Gemma 就自动判"说=tts_bridge"(桥接回来),选了 MiniCPM-o
#: 就自动判"说=native"(桥退场)。差别只在核显/内存那一侧吃多少:
#: e2b 1.8G / e4b 3G / 12b 8G / MiniCPM-o 11G —— 独显那 7.3G 一动不动。
_PERCEPTION_CANDIDATES: List[str] = [
    "openbmb/minicpm-o4.5",  # 默认:唯一能原生"说"的
    "gemma4:12b",
    "gemma4:e4b",
    "gemma4:e2b",
]

#: C 档推理位的候选（MoE·要专家卸载）。
#:
#: 为什么两个推理位是**两个档**而不是同一个槽位的两个候选:档才是推荐器
#: (:func:`~core.model_selection.recommend_tier`)和可跑性探针
#: (:func:`~core.runtime_readiness.tier_is_runnable`)工作的单位 —— 它们只能回答
#: "这个档跑不跑得起来",没法回答"这个档配这个候选跑不跑得起来"。而这两位的硬件
#: 门槛差着一整个级别:35B 的显存账建立在专家卸载之上,9B 稠密不欠这张票。
#: 塞进同一个槽位,推荐器就永远说不出"这台机器能跑 9B 那版、跑不了 35B 那版"。
#:
#: 加候选时注意:不同型号的专家卸载拆分结果不一样,换完必须重走 ``_split_moe``,
#: 不能沿用上一位的分配 —— ``reconcile_tier`` 已经是每位单独算,天然满足。
_REASONING_CANDIDATES: List[str] = [
    "qwen3.6:35b-a3b",
]

#: D 档推理位的候选（稠密·不需要专家卸载）。
_REASONING_CANDIDATES_DENSE: List[str] = [
    "qwythos-9b-v2",
]


_TIERS: Dict[str, Tier] = {
    "A": Tier(
        "A",
        "A 档 · 轻量本地",
        "Gemma 4 系：看 + 听(原生)，说走 TTS 桥；无独显也能跑",
        "single",
        [_single("gemma4:e2b", "gemma4:e4b", "gemma4:12b")],
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
        "C 档 · 双模型 · 35B 推理位",
        "推理位 Qwen3.6-35B-A3B(MoE，要专家卸载)常驻独显；感知位四选一(Gemma 4 系 / MiniCPM-o)走核显，可随时换",
        "composite",
        [
            # 感知位落核显:与推理位的独显互不抢显存,这正是双模型能同时在岗的前提。
            # 可换 —— 重载便宜,且常驻心跳每拍都会再要它一次。
            BrainSlot(SLOT_PERCEPTION, _PERCEPTION_CANDIDATES, placement="intel_igpu", resident=False),
            # 推理位常驻:18 GB 权重 + 专家卸载拆分,重载一次几十秒起。
            BrainSlot(SLOT_REASONING, _REASONING_CANDIDATES, placement="cuda", resident=True),
        ],
    ),
    "D": Tier(
        "D",
        "D 档 · 双模型 · 9B 推理位",
        "推理位 Qwythos-9B v2(稠密，不需专家卸载)常驻独显；感知位与 C 档同一份四选一，可随时换",
        "composite",
        [
            BrainSlot(SLOT_PERCEPTION, _PERCEPTION_CANDIDATES, placement="intel_igpu", resident=False),
            BrainSlot(SLOT_REASONING, _REASONING_CANDIDATES_DENSE, placement="cuda", resident=True),
        ],
    ),
}

#: 全部档位键，**由低到高**——低/高指的是**硬件门槛**，不是字母序，也不是模型强弱。
#:
#: 这个顺序是有语义的:``recommend_tier`` 从高往低找第一个"带余量装得下且跑得起来"
#: 的档,``effective_tier`` 跑不起来时只往**下**降。所以排在哪里 = 这个档的门槛多高。
#:
#: D 档排在 C 档**之前**(即门槛更低),因为:
#:
#: * D 的推理位是稠密 9B,装了标准 ``llama-cpp-python`` 就能跑;
#: * C 的推理位是 35B-A3B,显存账整个建立在**专家卸载生效**上,而 PyPI 上的
#:   ``llama-cpp-python`` 至今不透出 ``n_cpu_moe``——多数机器上 C 档直接判不可跑。
#:
#: 于是行为是:有卸载能力的机器推 C(更强的那位);没有的机器 C 判不可跑、自动落到 D,
#: 仍然拿得到双模型形态,而不是一路跌回 B 档单模型。这正是 ``effective_tier``
#: 那条降级路径想要的形状。
#:
#: **面板上会看到 A、B、D、C 这个顺序**——字母不连续是刻意的,改成字母序就会让
#: 推荐器优先推 D、C 档永远推不出去。要调整优先级请改这里的顺序,不要改字母。
_TIER_KEYS = ("A", "B", "D", "C")

#: 默认仍是 A 档单模型 —— 加 C/D 档不改变任何既有安装的行为。
_DEFAULT_TIER = "A"


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
    """当前档里担任 *role* 的模型 tag —— **"现在是谁在这一位上"的唯一答案**。

    槽位持有的是候选表,这里回答的是**选中的那一个**:

    * ``both`` 位(单模型档)看 :func:`main_brain`;
    * ``reasoning`` 位同样看 :func:`main_brain` —— 它就是"文本主脑"那个派生量;
    * ``perception`` 位看 :func:`perception_brain`(独立记一栏,见 ``_STATE_FILE``)。

    选中的那个若不在本位候选里(改过目录、或状态是旧版留下的),退回候选表第一个。
    """
    key = tier_key or load_tier()
    tier = get_tier(key)
    if not tier:
        return ""
    slot = tier.slot_for(role)
    if slot is None:
        return ""
    chosen = perception_brain() if slot.role == SLOT_PERCEPTION else main_brain()
    if chosen:
        spec = get_model(chosen)
        real = spec.tag if spec is not None else chosen
        if slot.accepts(real):
            return real
    return slot.tag


def active_tags(tier_key: str = "") -> List[str]:
    """本档**正在跑的**型号(每位一个),而不是全部候选。

    能力聚合、换档加载、常驻判定一律要用这一份。用 ``model_tags``(全部候选)会出
    这种错:C 档感知位明明选了 Gemma(不会原生说话),却因为候选表里还挂着
    MiniCPM-o 而被聚合成"说=原生",于是协商层不挂 TTS 桥 —— 结果是哑的。
    """
    key = tier_key or load_tier()
    tier = get_tier(key)
    if not tier:
        return []
    out: List[str] = []
    for slot in tier.slots:
        tag = model_for_role(slot.role, key)
        if tag and tag not in out:
            out.append(tag)
    return out


def tier_keys() -> List[str]:
    """全部档位键，由低到高。"""
    return list(_TIER_KEYS)


#: 目录声明与磁盘实际差多少才算"对不上"。
#:
#: GGUF 的头部元数据、对齐填充之类会带来百分之几的出入,那不值得报;而换一档量化
#: 是**几十个百分点**(Q4_K_M → Q8_0 差七成上下)。15% 落在这两者之间,报出来的
#: 一定是后者。
_WEIGHT_DIVERGENCE_TOLERANCE = 0.15

#: 已经就哪些 tag 报过量化对不上 —— 这条判据在准入路径上，每次刷新都会走一遍，
#: 不去重就会把日志刷满，而刷满的日志和没有日志是一回事。
_warned_weight_divergence: set = set()


def effective_weight_mb(tag: str) -> int:
    """这份权重到底多大(MB) —— **磁盘上的真文件优先，目录声明其次**。

    为什么目录那一栏靠不住
    ======================
    ``size_mb_val`` 记的是**某一档量化下**的体积,而目录里没有地方写"哪一档"——
    只有注释里一句"按 Q4_K_M 记"。用户换成 Q8_0(约 +70%)或直接用 bf16 原始权重
    (约 3 倍),目录一个字都不会变。于是准入判"放得下"、加载到一半 OOM,而报错在
    加载**途中**不在准入处 —— 现场看到的是"模型带不动",看不出是量化对不上。

    而这件事**根本不需要猜**:权重文件就在磁盘上,``stat`` 一下就是真值,不需要
    联网、不需要加载。目录那一栏只在"还没下载"时才该说话 —— 那正好是它唯一
    有用的场景(该不该下这一档)。

    与 :mod:`core.context_measurements` 同一个立场:**声明的假设 vs 实际的事实,
    事实优先**;差得远时**说出来**,而不是默默换掉 —— 差值本身就是"你换过量化"
    这条信息。
    """
    spec = exact_model(tag)
    declared = spec.size_mb() if spec is not None else 0
    try:
        from core.local_model_backends import on_disk_weight_mb  # noqa: PLC0415

        real = on_disk_weight_mb(tag)
    except Exception as exc:  # noqa: BLE001 — 查不到就按目录声明，不是错误
        logger.debug("磁盘权重体积不可查(按目录声明): %s", exc)
        return declared

    if real <= 0:
        return declared
    if (
        declared > 0
        and abs(real - declared) > declared * _WEIGHT_DIVERGENCE_TOLERANCE
        and tag not in _warned_weight_divergence
    ):
        _warned_weight_divergence.add(tag)
        logger.warning(
            "%s 的权重实际 %s MB，目录记的是 %s MB —— 多半是换了量化档。"
            "准入按实际的 %s MB 算；目录那一栏(size_mb_val)该跟着改，否则下一个读它的人还会被误导。",
            tag,
            real,
            declared,
            real,
        )
    return real


def tier_runtime_footprint_range_mb(tier_key: str = "") -> Tuple[int, int]:
    """这一档同时在岗的几位加起来占多少加速器内存 —— **(乐观, 悲观) 一对数**。

    为什么是一对而不是一个
    ======================
    目录里的 ``runtime_mb`` 不是量出来的,是**假设某件事成立**算出来的:
    ``qwen3.6:35b-a3b`` 权重 18 GB、记着驻留 7.3 GB,差的 10.7 GB 全靠专家卸载
    生效。把它报成一个数,读的人没法知道这个数底下压着一个假设;报成一对,
    ``悲观 - 乐观`` 这个差值本身就是"这一档有多少预算是张空头支票"的度量。

    - **乐观** = Σ ``runtime_mb`` —— 该成立的都成立时的驻留量;
    - **悲观** = Σ ``max(runtime_mb, size_mb)`` —— 卸载之类的假设全不成立、
      按整权重要显存时的驻留量。非 MoE 两者相等(驻留本就大于权重)。

    三点容易写错的：

    - 按 :func:`active_tags` 算，不是 ``model_tags`` —— 候选表里没被选中的那几个
      根本不会加载，把它们计进来会把 C 档的门槛虚高一大截；
    - 按 :meth:`ModelSpec.runtime_mb` 算，不是 ``size_mb`` —— 权重和驻留量差得远
      (MiniCPM-o 4.5 权重 6 GB、跑起来 11 GB)；
    - **求和**，因为复合档的几位是同时在岗的，不是二选一。

    档里有任何一位查不到精确的目录条目 → 返回 ``(0, 0)``,即"这一档判不了"。
    不能跳过查不到的那位接着求和 —— 那样得到的是一个**偏小**的门槛,准入会把
    装不下的档放行。判不了要显式地判不了,见 :func:`exact_model`。
    """
    from core.speculative_draft import draft_footprint_mb  # noqa: PLC0415

    lo = 0
    hi = 0
    for tag in active_tags(tier_key):
        spec = exact_model(tag)
        if spec is None:
            return (0, 0)
        resident = spec.runtime_mb()
        # 草稿位开着就是**多一份权重在卡上**,不算它就是又一次"判成放得下、
        # 加载到一半 OOM"。-1 表示判不了(开着但没人量过占多少)—— 那必须整档
        # 判不了,不能当 0 吸收:吸收掉得到的是一个偏小的门槛,而偏小的门槛会放行。
        draft_mb, _why = draft_footprint_mb(tag)
        if draft_mb < 0:
            return (0, 0)
        resident += draft_mb
        lo += resident
        # 悲观那一头问 effective_weight_mb 而不是 spec.size_mb():权重文件已经在
        # 磁盘上时,它比目录里那条"按 Q4_K_M 记"的声明更可信 —— 而这一头正是
        # "假设全不成立、按整权重要显存"的估计,拿一个量化对不上的数去估没有意义。
        hi += max(resident, effective_weight_mb(spec.tag) + draft_mb)
    return (lo, hi)


def tier_runtime_footprint_mb(tier_key: str = "") -> int:
    """这一档同时在岗的几位加起来占多少加速器内存(MB) —— 取**乐观**那一头。

    判据全在 :func:`tier_runtime_footprint_range_mb`,这里只是取值方便。要拿这个
    数去做准入的，请连**悲观**那一头一起看：单看这一个数会以为门槛是确定的。
    """
    return tier_runtime_footprint_range_mb(tier_key)[0]


def resident_tags(tier_key: str = "") -> List[str]:
    """当前(或指定)档里**不许被淘汰**的模型 tag —— 调度器的钉住名单只问这一处。

    返回的是常驻位上**选中的**那个,不是它的全部候选 —— 没加载的候选谈不上淘汰。
    """
    key = tier_key or load_tier()
    tier = get_tier(key)
    if not tier:
        return []
    out: List[str] = []
    for slot in tier.slots:
        if not slot.resident:
            continue
        tag = model_for_role(slot.role, key)
        if tag and tag not in out:
            out.append(tag)
    return out


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
    """本档**正在跑的**那几个模型合起来的有效 IO。

    用 :func:`active_tags` 而不是全部候选 —— C 档感知位选了 Gemma(不会原生说话)
    时,若把候选表里的 MiniCPM-o 也算进来,会得出"说=原生"、于是不挂 TTS 桥,
    结果是哑的。这正是"能力表与实际在跑的东西分家"的形状。
    """
    return effective_io(active_tags(key))


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
                    # 旧记录没有这一栏 → 空,消费方自然退回槽位默认。不需要迁移动作,
                    # 因为在加这一栏之前感知位与主脑本来就是同一个模型。
                    "perception_brain": str(data.get("perception_brain", "")).strip(),
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
    return {"tier": tier, "main_brain": brain, "perception_brain": ""}


def _write_state(tier: str, main_brain: str, perception_brain: Optional[str] = None) -> None:
    """写【一条】统一记录,并派生导出运行时 env。

    ``perception_brain`` 为 ``None`` 表示"这次不动它" —— 保留记录里的现值。
    换主脑不该顺手把感知位的选择抹掉,那是两个独立的位。
    """
    keep = _read_state().get("perception_brain", "") if perception_brain is None else perception_brain
    rec = {
        "tier": (tier or "").strip().upper(),
        "main_brain": (main_brain or "").strip(),
        "perception_brain": (keep or "").strip(),
    }
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_STATE_FILE, rec, indent=None, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("保存模型状态失败(非致命): %s", exc)
    if rec["tier"]:
        os.environ["GALAXY_MODEL_TIER"] = rec["tier"]
    if rec["main_brain"]:
        os.environ["OLLAMA_MODEL"] = rec["main_brain"]  # 运行时主脑:派生导出
    if rec["perception_brain"]:
        os.environ["GALAXY_PERCEPTION_MODEL"] = rec["perception_brain"]


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


def perception_brain() -> str:
    """当前**感知位**选中的 tag：GALAXY_PERCEPTION_MODEL 环境变量 > 统一记录 > ""。

    与 :func:`main_brain` 是两个独立的位:主脑那一栏代表"文本主脑"(推理位/单模型
    档的那一个),感知位是另一栏。合成一栏的话,C 档下换感知位就会把推理位一起改掉。
    """
    env = os.environ.get("GALAXY_PERCEPTION_MODEL", "").strip()
    if env:
        return env
    return _read_state().get("perception_brain", "")


def save_perception_brain(tag: str, *, tier_key: str = "") -> str:
    """把感知位换成 *tag*(必须是本档感知位的候选之一),返回最终生效的 tag。

    **这就是"上面那位随便换"的入口。** 不在候选里一律拒绝并保持原样 ——
    静默改成别的等于"换了个我没选的模型",而用户看不出来。
    """
    key = (tier_key or load_tier()).strip().upper()
    slot = slot_for_role(SLOT_PERCEPTION, key)
    if slot is None:
        return ""
    spec = get_model(tag) if tag else None
    real = spec.tag if spec is not None else (tag or "")
    if not slot.accepts(real):
        logger.warning(
            "感知位不接受 %r —— 本位候选只有 %s;保持现选 %s 不变",
            tag,
            ", ".join(slot.candidates),
            model_for_role(SLOT_PERCEPTION, key),
        )
        return model_for_role(SLOT_PERCEPTION, key)
    _write_state(key, main_brain(), real)
    # 换感知位可能改变"能不能原生说话" → 原生后端要跟着开/关。
    try:
        from core.native_modal import on_tier_changed

        on_tier_changed(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("换感知位的原生后端联动跳过(不影响换人): %s", exc)
    return real


def save_main_brain(tag: str) -> None:
    """持久化主脑到统一记录(档位保持现值,并派生 OLLAMA_MODEL)。是主脑写入的唯一门。"""
    if not tag:
        return
    _write_state(load_tier(), tag)


def default_main_brain_for_tier(tier_key: str = "") -> str:
    """没有显式指定时,这一档的**文本主脑**(``OLLAMA_MODEL`` 这个派生量)默认是谁。

    这条规则原来只长在 :func:`save_tier` 里,于是运行时降档那条路只能自己再写一遍
    "复合档取哪一位" —— 而这正是上一轮出过事的地方:两处各写一遍,错的那处赢了,
    C 档的 ``OLLAMA_MODEL`` 指到了感知位。规则只留这一处,两边都问它。

    - **复合档** → 推理位。复合档没有"选一个"这回事,整档一起跑,但这个派生量只能
      指一个,它代表的是"文本主脑"。按"档内第一个 source=local"取会指到感知位
      (C 档感知位是 local、推理位是 llama_cpp),所有文本请求就都落到感知位上;
    - **其余** → 档内第一个 ``source=local``;
    - 档不存在、或档内没有本地模型 → ``""``,由调用方决定退回什么。
    """
    key = (tier_key or load_tier()).strip().upper()
    tier = _TIERS.get(key)
    if tier is None:
        return ""
    if tier.kind == "composite":
        reasoning = tier.slot_for(SLOT_REASONING)
        # 空 tag 要**继续往下找**，不能返回空串:那样调用方会误以为"这一档没有主脑"，
        # 而它其实只是没配推理位。与重构前 `if main_brain: … elif local_in_tier: …`
        # 的落法一致。
        if reasoning and reasoning.tag:
            return reasoning.tag
    for spec in tier_models(key):
        if spec.source == "local":
            return spec.tag
    return ""


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
    if main_brain:
        # 显式指定 → 一律尊重(此前"不在档内候选就替换成档内第一个"会把用户刚选定的
        # 自定义模型静默改回 gemma4:e2b —— 真实的静默数据丢失路径)。
        chosen = main_brain
    else:
        chosen = default_main_brain_for_tier(key) or _read_state().get("main_brain", "")
    # 感知位:换档时若现选不属于新档的候选,落回新档默认。不这么做的话,从 C 档
    # (感知位可能选了 Gemma)切到 B 档,那个选择会**留在记录里**,下次切回 C 档
    # 时冒出来 —— 用户不记得自己选过。
    perception = _read_state().get("perception_brain", "")
    pslot = tier.slot_for(SLOT_PERCEPTION)
    if pslot is None or not pslot.accepts(perception):
        perception = pslot.tag if pslot is not None else ""
    _write_state(key, chosen, perception)
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
                    {
                        "role": s.role,
                        "candidates": list(s.candidates),
                        # 面板据此高亮"这一位现在是谁",以及这一位换不换得动。
                        "selected": model_for_role(s.role, t.key),
                        "swappable": len(s.candidates) > 1,
                        "placement": s.placement,
                        "resident": s.resident,
                    }
                    for s in t.slots
                ],
                "active_tags": active_tags(t.key),
                "effective_io": tier_effective_io(t.key).to_dict(),
            }
            for t in all_tiers()
        ],
    }


# ---------------------------------------------------------------------------
# 本地这一侧的"能力档" —— 按实际装的东西算，不写死
# ---------------------------------------------------------------------------
#: 推理位规模(权重 MB) → 能力档。阈值**按本目录里真实存在的型号定**，不是凭空取整：
#:
#:     ≥ 15000   qwen3.6:35b-a3b(18 GB) —— 35B MoE，与前沿云端同档
#:     ≥  5000   qwythos-9b-v2(5.6 GB) / gemma4:12b(8 GB) —— 强
#:     <  5000   gemma4:e2b(1.8 GB) / e4b(3 GB) —— 轻量
#:
#: 为什么用**推理位**而不是"这个 provider 装了什么"
#: ------------------------------------------------
#: 质量档要回答的是"把一件需要脑子的活派给它靠不靠谱"。感知位管的是听/说通路
#: （见 :data:`SLOT_PERCEPTION`），它的规模跟这件事无关 —— MiniCPM-o 权重 6 GB
#: 里有一大半是视觉/音频编码器，拿它当推理能力的度量会高估。
#:
#: 为什么用权重而不是运行时显存
#: ----------------------------
#: ``runtime_mb`` 两个方向都会偏离能力：全模态模型因为驮着编码器而**大于**权重，
#: MoE 走专家卸载后又**小于**权重（35B-A3B 权重 18 GB、显存只 7.3 GB）。
#: 拿它排能力会把最强的那个排到最低。权重是这几个量里与"模型多大"最接近的一个。
_LOCAL_TIER_BY_REASONING_SIZE_MB: Tuple[Tuple[int, int], ...] = (
    (15000, 3),
    (5000, 2),
    (0, 1),
)


def local_reasoning_quality_tier(tier_key: str = "") -> int:
    """本地这一侧当前的能力档(1/2/3) —— **由推理位上真正选中的型号决定**。

    这一栏原来是写死的::

        # tier 1 —— 本地轻量（无 GPU 笔电主脑）
        "ollama": 1, "hf_local": 1, "local_openai": 1,

    那是装 Gemma-e2b 时代的假设。C 档推理位是 35B-A3B、D 档是 9B 稠密，一律判成
    "轻量"的后果是：**一旦走质量优先路径，本地必输给任何云端**，无论机器上装的是什么。
    于是"写代码/写东西优先用强模型"这句话，在本地放着 35B 时也只会把活派到云端去。

    Returns:
        1(轻量) / 2(强) / 3(前沿)。取不到档位或型号时返回 1 —— 不知道就别高估，
        高估会把活派给一个可能带不动的本地模型。
    """
    try:
        key = (tier_key or load_tier()).strip().upper()
        tier = get_tier(key)
        if tier is None:
            return 1
        # 单模型档没有独立推理位，那一个模型两只手都干 —— 它就是推理位。
        role = SLOT_REASONING if tier.slot_for(SLOT_REASONING) is not None else SLOT_BOTH
        tag = model_for_role(role, key)
        spec = get_model(tag) if tag else None
        if spec is None:
            return 1
        size = int(spec.size_mb_val or 0)
        for floor, level in _LOCAL_TIER_BY_REASONING_SIZE_MB:
            if size >= floor:
                return level
        return 1
    except Exception as exc:  # noqa: BLE001 —— 路由取不到档位绝不能崩，保守回落
        logger.debug("local_reasoning_quality_tier 解析失败，按轻量处理: %s", exc)
        return 1
