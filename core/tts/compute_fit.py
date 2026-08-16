#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/tts/compute_fit.py — TTS 引擎与本机算力的匹配预检
=======================================================

**要解决的问题:** 引擎选择目前只读一个环境变量,合不合得上本机算力**要等到合成
那一刻才知道**。对 ``indextts`` 尤其难受——它自己的文档就写着"自回归大模型,
纯 CPU 合成一句要数秒到数十秒"。用户选了它、按下说话、然后等十几秒,才发现这台
机器跑不动。本模块把这个判断提到**选择时**,并且**说出来**。

范围要说清楚,免得读的人以为这里有比实际更多的东西
--------------------------------------------------
这个仓库的 TTS 引擎**绝大多数本来就是为 CPU 设计的**,这是它们自己文档里的话:

    kokoro   82M 参数,"纯 CPU 快于实时"
    melo     VITS 系,"CPU 秒级合成"
    piper    "纯 CPU、实时","树莓派都能跑"
    edge     云端合成,不消耗本地算力
    sapi     Windows 系统自带,零依赖

**唯一真正吃算力的是 indextts。** 所以本模块不是"在一堆引擎之间做智能调度"——
那是引擎重量各异时才有的问题。它做的是一件更小、也更实在的事:
**在选择时判断这个引擎在这台机器上是否跑得动,跑不动就明确讲出来。**

不覆盖显式选择
--------------
用户显式设了 ``GALAXY_TTS_ENGINE=indextts``,即使算力不足也**照样先试它**——
显式意图高于推断信号,这与 ``_pick_strategy`` 里经验制导不覆盖显式关键词是同一条
原则。本模块只在两处生效:

1. **告知**:选择时给出明确、可操作的诊断(缺多少显存、慢到什么量级、可以改用谁),
   而不是让用户在合成时自己体会。
2. **回退链**:当引擎需要回退时,跳过那些**已探明**跑不动的候选。

探测不到就当没探测过
--------------------
硬件画像拿不到(无 GPU 库/探测失败/非本机执行)时,本模块一律返回"不设限",
行为与改造前完全一致。**宁可不判断,也不能因为探测不到就拦下一个本来能用的引擎。**
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TTS.ComputeFit")

__all__ = [
    "TTS_COMPUTE_FIT_IS_ADVISORY_POLICY",
    "TTS_COMPUTE_FIT_NEVER_OVERRIDES_EXPLICIT_CHOICE_POLICY",
    "TTS_COMPUTE_FIT_UNKNOWN_MEANS_UNRESTRICTED_POLICY",
    "MODE_STATIC",
    "MODE_COMPUTE_AWARE",
    "get_tts_routing_mode",
    "EngineComputeNeed",
    "ENGINE_COMPUTE_NEEDS",
    "FitVerdict",
    "assess_engine_fit",
    "filter_fallback_chain",
]


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

TTS_COMPUTE_FIT_IS_ADVISORY_POLICY: str = (
    "TTS_COMPUTE_FIT::POLICY_1: "
    "This module reports whether an engine fits the local machine.  It does not "
    "select engines, load models, or synthesise anything; speech_output remains "
    "the sole engine-selection authority."
)

TTS_COMPUTE_FIT_NEVER_OVERRIDES_EXPLICIT_CHOICE_POLICY: str = (
    "TTS_COMPUTE_FIT::POLICY_2: "
    "An explicitly requested engine (GALAXY_TTS_ENGINE=<name>) is ALWAYS attempted, "
    "however poor the fit.  Stated intent outranks an inferred signal — the same "
    "rule that keeps experience statistics from overriding an explicit keyword in "
    "ExecutionPlanner._pick_strategy.  A poor fit produces a loud diagnostic, "
    "never a silent substitution."
)

TTS_COMPUTE_FIT_UNKNOWN_MEANS_UNRESTRICTED_POLICY: str = (
    "TTS_COMPUTE_FIT::POLICY_3: "
    "When the hardware profile is unavailable or unreadable, every engine is "
    "reported as fitting.  Refusing an engine because the probe failed would turn "
    "a missing measurement into a capability regression."
)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

MODE_STATIC: str = "static"
"""Pre-existing behaviour: engine chain decided purely by GALAXY_TTS_ENGINE."""

MODE_COMPUTE_AWARE: str = "compute_aware"
"""Also assess fit, warn on a poor one, and skip unfit engines in fallback chains."""

_VALID_MODES = (MODE_STATIC, MODE_COMPUTE_AWARE)
_ENV_MODE = "GALAXY_TTS_ROUTING"


def get_tts_routing_mode() -> str:
    """Resolve routing mode; unknown values degrade to compute-aware.

    Degrading to ``compute_aware`` rather than ``static`` is safe because the
    compute-aware path only ever *adds* diagnostics and skips engines it has
    positively determined cannot run — see POLICY_2 and POLICY_3.
    """
    raw = os.getenv(_ENV_MODE, MODE_COMPUTE_AWARE).strip().lower()
    if raw in _VALID_MODES:
        return raw
    logger.warning("%s=%r is not one of %s — using %r", _ENV_MODE, raw, _VALID_MODES, MODE_COMPUTE_AWARE)
    return MODE_COMPUTE_AWARE


# ---------------------------------------------------------------------------
# Engine requirements — every figure below comes from the engine's own module
# docstring, not from an estimate invented here.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineComputeNeed:
    """What one engine needs from the local machine.

    Attributes
    ----------
    name:
        Engine key as used by ``GALAXY_TTS_ENGINE``.
    needs_local_compute:
        False for engines that synthesise off-box (edge) or via the OS (sapi).
    gpu_vram_mb:
        VRAM that makes this engine comfortable.  0 means it never needs a GPU.
    cpu_viable:
        Whether running without a GPU is a reasonable experience.
    cpu_note:
        What CPU-only actually feels like, in the engine's own words.
    source:
        Where the claim comes from, so a reader can verify rather than trust.
    """

    name: str
    needs_local_compute: bool
    gpu_vram_mb: int
    cpu_viable: bool
    cpu_note: str
    source: str


ENGINE_COMPUTE_NEEDS: Dict[str, EngineComputeNeed] = {
    "edge": EngineComputeNeed(
        name="edge",
        needs_local_compute=False,
        gpu_vram_mb=0,
        cpu_viable=True,
        cpu_note="云端合成,不消耗本地算力(但要能连上微软服务)",
        source="core/tts/edge_tts_engine.py",
    ),
    "sapi": EngineComputeNeed(
        name="sapi",
        needs_local_compute=False,
        gpu_vram_mb=0,
        cpu_viable=True,
        cpu_note="Windows 系统自带,零 pip 依赖、完全离线",
        source="core/tts/sapi_engine.py 模块文档",
    ),
    "piper": EngineComputeNeed(
        name="piper",
        needs_local_compute=True,
        gpu_vram_mb=0,
        cpu_viable=True,
        cpu_note="纯 CPU、实时、离线,树莓派都能跑",
        source="core/tts/piper_engine.py 模块文档",
    ),
    "kokoro": EngineComputeNeed(
        name="kokoro",
        needs_local_compute=True,
        gpu_vram_mb=0,
        cpu_viable=True,
        cpu_note="82M 参数,纯 CPU 快于实时",
        source="core/tts/kokoro_engine.py 模块文档",
    ),
    "melo": EngineComputeNeed(
        name="melo",
        needs_local_compute=True,
        gpu_vram_mb=0,
        cpu_viable=True,
        cpu_note="VITS 系,CPU 秒级合成",
        source="core/tts/melo_engine.py 模块文档",
    ),
    "indextts": EngineComputeNeed(
        name="indextts",
        needs_local_compute=True,
        gpu_vram_mb=6000,
        cpu_viable=False,
        cpu_note="自回归大模型,纯 CPU 合成一句要数秒到数十秒",
        source="core/tts/indextts_engine.py 模块文档",
    ),
}
"""Per-engine compute needs.

Note what this table says: **only indextts is GPU-sensitive.** Every other engine
in this repository is CPU-designed by intent.  A reader expecting a rich routing
matrix should read that as the answer, not as a gap."""


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass
class FitVerdict:
    """Whether an engine fits this machine, and what to tell the user."""

    engine: str = ""
    fits: bool = True
    probed: bool = False
    reason: str = ""
    free_vram_mb: int = 0
    suggested_alternatives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "fits": self.fits,
            "probed": self.probed,
            "reason": self.reason,
            "free_vram_mb": self.free_vram_mb,
            "suggested_alternatives": self.suggested_alternatives,
        }


def _best_free_vram_mb() -> Optional[int]:
    """Largest free VRAM across local GPUs, or ``None`` when unknown.

    ``None`` is a distinct answer from ``0``: "we could not measure" must not be
    confused with "there is no GPU", or a probe failure silently becomes a
    capability regression (POLICY_3).
    """
    try:
        from core.hardware_compute_profiler import get_compute_profile_sync

        profile = get_compute_profile_sync()
    except Exception as exc:  # noqa: BLE001 — probing must never break speech
        logger.debug("compute profile unavailable: %s", exc)
        return None
    gpus = list(getattr(profile, "gpus", None) or [])
    if not gpus:
        return 0  # measured, and there genuinely is no usable GPU
    try:
        return int(max(int(getattr(g, "free_vram_mb", 0) or 0) for g in gpus))
    except Exception as exc:  # noqa: BLE001
        logger.debug("free VRAM unreadable: %s", exc)
        return None


def assess_engine_fit(engine: str, *, free_vram_mb: Optional[int] = None) -> FitVerdict:
    """Judge whether *engine* can run acceptably on this machine.

    Never raises.  An unknown engine, an unavailable probe, or any internal error
    all yield ``fits=True`` — this module may inform a choice, never block one it
    cannot justify blocking.
    """
    name = (engine or "").strip().lower()
    need = ENGINE_COMPUTE_NEEDS.get(name)
    if need is None:
        return FitVerdict(engine=name, fits=True, reason="engine not in the requirements table")

    if not need.needs_local_compute:
        return FitVerdict(engine=name, fits=True, reason=need.cpu_note)

    if need.cpu_viable:
        return FitVerdict(engine=name, fits=True, reason=need.cpu_note)

    # Only engines that are *not* CPU-viable need a measurement at all.
    measured = _best_free_vram_mb() if free_vram_mb is None else free_vram_mb
    if measured is None:
        return FitVerdict(
            engine=name,
            fits=True,
            probed=False,
            reason="硬件画像不可用,不设限(探测不到不等于跑不动)",
        )

    if measured >= need.gpu_vram_mb:
        return FitVerdict(
            engine=name,
            fits=True,
            probed=True,
            free_vram_mb=measured,
            reason=f"可用显存 {measured}MB ≥ 需要的 {need.gpu_vram_mb}MB",
        )

    alternatives = [n for n, e in ENGINE_COMPUTE_NEEDS.items() if e.cpu_viable and n != name]
    return FitVerdict(
        engine=name,
        fits=False,
        probed=True,
        free_vram_mb=measured,
        reason=(
            f"可用显存 {measured}MB < 需要的 {need.gpu_vram_mb}MB;"
            f"该引擎在 CPU 上的实际表现是「{need.cpu_note}」({need.source})"
        ),
        suggested_alternatives=sorted(alternatives),
    )


def filter_fallback_chain(chain: List[str], *, explicit_choice: str = "") -> List[str]:
    """Drop engines from a *fallback* chain that were measured as unfit.

    ``explicit_choice`` is preserved unconditionally even when it does not fit —
    stated intent outranks an inferred signal (POLICY_2).  The caller is expected
    to have already surfaced the diagnostic from :func:`assess_engine_fit`.

    In :data:`MODE_STATIC` the chain is returned untouched.
    """
    if get_tts_routing_mode() == MODE_STATIC:
        return list(chain)
    explicit = (explicit_choice or "").strip().lower()
    kept: List[str] = []
    for name in chain:
        if name == explicit:
            kept.append(name)
            continue
        verdict = assess_engine_fit(name)
        if verdict.fits:
            kept.append(name)
        else:
            logger.info("TTS 回退链跳过 %s: %s", name, verdict.reason)
    # Never hand back an empty chain: an over-eager filter must not be the reason
    # the system goes mute. Falling back to the unfiltered chain is strictly
    # better than silence.
    return kept or list(chain)
