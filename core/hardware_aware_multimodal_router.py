"""
core.hardware_aware_multimodal_router — 硬件感知多模态优先路由器
=========================================================================

对 multi_llm_router.py 的全新增强层。不改变现有路由逻辑，而是在其上
叠加硬件感知和多模态优先策略。

核心设计原则（你要求的）：
1. 原生多模态优先 — 有图片/视频/音频输入时优先选多模态模型
2. 本地 + API 混合为主 — 本地可用时优先本地，API兜底
3. 各种大模型 API 为后备
4. 本地大模型连通 HuggingFace — 想要什么直接下

借鉴的 GitHub 项目最佳实践：
- llama.cpp: CPU/GPU 混合推理、层卸载
- vLLM: PagedAttention 显存管理、continuous batching
- SGLang: RadixAttention 前缀缓存、speculative decoding
- Ollama: 本地模型托管体验

路由决策层次：
    Task Type → Multimodal? → Local Available? → GPU Fit? → Provider Select
        ↓              ↓              ↓              ↓              ↓
    classify     check image/    check Ollama/    Hardware      最终选择
    task type    video/audio     HF local        Profiler
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.HAMRouter")


# ---------------------------------------------------------------------------
# Source Type — 模型来源类型
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """模型来源类型 — 决定优先级"""
    LOCAL_MULTIMODAL = "local_multimodal"     # 本地多模态（最高优先级）
    LOCAL_LLM = "local_llm"                    # 本地文本模型
    API_MULTIMODAL = "api_multimodal"          # API 多模态（GPT-4V等）
    API_LLM = "api_llm"                        # API 文本模型
    HF_DOWNLOADABLE = "hf_downloadable"        # HuggingFace 可下载
    ONEAPI_AGGREGATOR = "oneapi_aggregator"    # OneAPI 聚合层


# ---------------------------------------------------------------------------
# Routing Strategy — 路由策略
# ---------------------------------------------------------------------------

class RoutingStrategy(str, Enum):
    """路由策略模式"""
    MULTIMODAL_LOCAL_FIRST = "multimodal_local_first"    # 你要求的主策略
    COST_OPTIMIZED = "cost_optimized"                     # 成本优先
    SPEED_OPTIMIZED = "speed_optimized"                   # 速度优先
    LOCAL_ONLY = "local_only"                             # 纯本地（隐私模式）
    API_ONLY = "api_only"                                 # 纯API（无GPU模式）


# ---------------------------------------------------------------------------
# Hardware-Aware Routing Decision
# ---------------------------------------------------------------------------

@dataclass
class HARoutingDecision:
    """硬件感知路由决策"""
    provider: str
    model: str
    source_type: SourceType
    reason: str
    tier: str  # GPU_FULL / GPU_QUANTIZED / CPU / REMOTE
    quantization: str  # none / q4 / q8
    alternatives: List[str] = field(default_factory=list)
    estimated_vram_mb: int = 0
    estimated_latency_ms: int = 0


# ---------------------------------------------------------------------------
# 新路由偏好表 — 多模态优先、本地优先
# ---------------------------------------------------------------------------

# 任务类型 → 来源优先级（MULTIMODAL_LOCAL_FIRST 策略）
MULTIMODAL_LOCAL_FIRST_PREFERENCES: Dict[str, List[Tuple[SourceType, List[str]]]] = {
    # 视觉任务：本地VLM > API多模态 > 本地LLM > API
    "vision": [
        (SourceType.LOCAL_MULTIMODAL, ["ollama_vlm", "hf_llava", "hf_bakllava"]),
        (SourceType.API_MULTIMODAL, ["openai", "anthropic", "google", "zhipu"]),
        (SourceType.LOCAL_LLM, ["ollama", "hf_qwen2"]),
        (SourceType.API_LLM, ["openai", "anthropic", "google"]),
    ],
    # 语音任务：本地ASR > API
    "asr": [
        (SourceType.LOCAL_MULTIMODAL, ["hf_whisper"]),
        (SourceType.API_MULTIMODAL, ["openai"]),
    ],
    # 编码任务：本地优先（代码敏感）
    "coding": [
        (SourceType.LOCAL_LLM, ["ollama", "hf_qwen2", "hf_codellama"]),
        (SourceType.API_LLM, ["deepseek", "anthropic", "openai", "qwen"]),
        (SourceType.ONEAPI_AGGREGATOR, ["oneapi"]),
    ],
    # 推理任务：API优先（需要强模型）
    "reasoning": [
        (SourceType.API_LLM, ["anthropic", "openai", "google", "deepseek"]),
        (SourceType.LOCAL_LLM, ["ollama", "hf_qwen2"]),
    ],
    # 快速响应：本地优先（低延迟）
    "fast_response": [
        (SourceType.LOCAL_LLM, ["ollama", "hf_qwen2"]),
        (SourceType.API_LLM, ["deepseek", "groq", "google"]),
    ],
    # 通用任务：本地+API混合
    "general": [
        (SourceType.LOCAL_LLM, ["ollama", "hf_qwen2"]),
        (SourceType.API_LLM, ["openai", "anthropic", "deepseek", "google"]),
        (SourceType.ONEAPI_AGGREGATOR, ["oneapi"]),
    ],
    # Agent控制：需要工具调用
    "agent_control": [
        (SourceType.API_LLM, ["anthropic", "openai", "deepseek"]),
        (SourceType.LOCAL_LLM, ["ollama"]),
    ],
}

# ---------------------------------------------------------------------------
# Hardware-Aware Multimodal Router
# ---------------------------------------------------------------------------

class HardwareAwareMultimodalRouter:
    """硬件感知多模态优先路由器

    设计为 MultiLLMRouter 的装饰增强层，不改变原有接口。
    OpenClawd 先调用此路由器获取策略建议，再传给 MultiLLMRouter 执行。

    使用方式:
        ha_router = HardwareAwareMultimodalRouter()
        decision = await ha_router.route(task_type, messages, has_multimodal_input)
        # decision 包含 provider / model / source_type / tier
    """

    def __init__(self):
        self.strategy = RoutingStrategy.MULTIMODAL_LOCAL_FIRST
        self._hf_available = self._check_hf_hub()
        self._ollama_available = self._check_ollama()
        self._local_models: Dict[str, Any] = {}
        self._last_refresh = 0.0

    # ── 可用性检查 ──

    @staticmethod
    def _check_hf_hub() -> bool:
        try:
            import huggingface_hub
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_ollama() -> bool:
        """检查 Ollama 是否可用"""
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ── 核心路由方法 ──

    async def route(self, task_type: str,
                    messages: List[Dict],
                    has_multimodal_input: bool = False,
                    preferred_source: Optional[SourceType] = None,
                    **kwargs) -> HARoutingDecision:
        """
        硬件感知多模态优先路由

        Args:
            task_type: 任务类型 (vision/asr/coding/reasoning/fast_response/general/...)
            messages: 对话消息
            has_multimodal_input: 是否包含图片/视频/音频输入
            preferred_source: 用户指定的来源类型

        Returns:
            HARoutingDecision — 包含 provider/model/source_type/tier 等
        """
        # 1. 获取硬件画像
        try:
            from core.hardware_compute_profiler import get_compute_profile_sync
            profile = get_compute_profile_sync()
        except Exception:
            profile = None

        # 2. 获取本地模型列表
        local_models = await self._scan_local_models()

        # 3. 确定策略偏好顺序
        preferences = MULTIMODAL_LOCAL_FIRST_PREFERENCES.get(
            task_type, MULTIMODAL_LOCAL_FIRST_PREFERENCES["general"]
        )

        # 4. 如果有用户指定来源，提升到最前
        if preferred_source:
            preferences = self._reorder_by_source(preferences, preferred_source)

        # 5. 遍历偏好顺序，找到第一个可用的
        for source_type, providers in preferences:
            decision = await self._try_source(
                source_type, providers, task_type, profile,
                local_models, has_multimodal_input
            )
            if decision:
                return decision

        # 6. 全部失败 — fallback 到 API
        logger.warning("All local sources exhausted, falling back to API")
        return HARoutingDecision(
            provider="openai",
            model="gpt-4o",
            source_type=SourceType.API_LLM,
            reason="All local sources exhausted, API fallback",
            tier="remote_api",
            quantization="none",
        )

    # ── 来源尝试 ──

    async def _try_source(self, source_type: SourceType,
                          providers: List[str],
                          task_type: str,
                          profile: Optional[Any],
                          local_models: Dict[str, Any],
                          has_multimodal: bool) -> Optional[HARoutingDecision]:
        """尝试一个来源类型"""

        if source_type == SourceType.LOCAL_MULTIMODAL:
            # 检查本地多模态模型
            vlm_models = local_models.get("vlm", [])
            if vlm_models:
                model = vlm_models[0]
                return HARoutingDecision(
                    provider="local_vlm",
                    model=model["name"],
                    source_type=SourceType.LOCAL_MULTIMODAL,
                    reason=f"Local multimodal model available: {model['name']}",
                    tier=profile.recommended_tier.value if profile else "gpu_full",
                    quantization=profile.recommended_quantization if profile else "none",
                    estimated_vram_mb=model.get("size_mb", 4000),
                )
            # 检查是否可以下载
            if self._hf_available and profile and profile.can_run_local_multimodal:
                return HARoutingDecision(
                    provider="hf_download",
                    model="llava-v1.5-7b-q4",
                    source_type=SourceType.HF_DOWNLOADABLE,
                    reason="VLM can be downloaded from HuggingFace",
                    tier=profile.recommended_tier.value if profile else "gpu_quantized",
                    quantization="q4",
                    estimated_vram_mb=4000,
                )

        elif source_type == SourceType.LOCAL_LLM:
            # 检查 Ollama
            if self._ollama_available:
                tier = profile.recommended_tier.value if profile else "gpu_full"
                quant = profile.recommended_quantization if profile else "none"
                return HARoutingDecision(
                    provider="ollama",
                    model=self._select_ollama_model(task_type, profile),
                    source_type=SourceType.LOCAL_LLM,
                    reason=f"Ollama local | tier={tier} quant={quant}",
                    tier=tier,
                    quantization=quant,
                )
            # 检查 HF 本地模型
            llm_models = local_models.get("llm", [])
            if llm_models:
                model = llm_models[0]
                return HARoutingDecision(
                    provider="hf_local",
                    model=model["name"],
                    source_type=SourceType.LOCAL_LLM,
                    reason=f"HF local model: {model['name']}",
                    tier=profile.recommended_tier.value if profile else "cpu_avx2",
                    quantization=model.get("quantization", "none"),
                )
            # 可以下载
            if self._hf_available and profile and profile.can_run_local_llm:
                return HARoutingDecision(
                    provider="hf_download",
                    model="qwen2-7b-instruct-q4",
                    source_type=SourceType.HF_DOWNLOADABLE,
                    reason="LLM can be downloaded from HuggingFace",
                    tier=profile.recommended_tier.value if profile else "gpu_quantized",
                    quantization="q4",
                    estimated_vram_mb=4500,
                )

        elif source_type == SourceType.API_MULTIMODAL:
            # 多模态 API — GPT-4V, Claude, Gemini
            return HARoutingDecision(
                provider="openai",
                model="gpt-4o",
                source_type=SourceType.API_MULTIMODAL,
                reason="API multimodal: gpt-4o",
                tier="remote_api",
                quantization="none",
            )

        elif source_type == SourceType.API_LLM:
            # API 文本模型
            return HARoutingDecision(
                provider="openai",
                model="gpt-4o-mini" if task_type == "fast_response" else "gpt-4o",
                source_type=SourceType.API_LLM,
                reason="API LLM fallback",
                tier="remote_api",
                quantization="none",
            )

        return None

    # ── 辅助方法 ──

    async def _scan_local_models(self) -> Dict[str, List[Dict]]:
        """扫描本地可用模型"""
        now = time.time()
        if now - self._last_refresh < 60 and self._local_models:
            return self._local_models

        models: Dict[str, List[Dict]] = {"llm": [], "vlm": [], "asr": [], "embedding": []}

        # 扫描 Ollama 模型
        if self._ollama_available:
            try:
                import httpx
                resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
                if resp.status_code == 200:
                    for m in resp.json().get("models", []):
                        models["llm"].append({
                            "name": m["name"],
                            "source": "ollama",
                            "size_mb": m.get("size", 0) // (1024 * 1024),
                        })
            except Exception:
                pass

        # 扫描 HF 本地模型
        try:
            from core.huggingface_model_manager import get_hf_model_manager
            hf_mgr = get_hf_model_manager()
            for entry in hf_mgr.list_local_models():
                models.setdefault(entry.family.value, []).append({
                    "name": entry.model_id,
                    "source": "huggingface",
                    "size_mb": entry.size_mb,
                    "quantization": entry.quantization,
                })
        except Exception:
            pass

        self._local_models = models
        self._last_refresh = now
        return models

    @staticmethod
    def _select_ollama_model(task_type: str, profile: Optional[Any]) -> str:
        """根据任务类型和硬件选择 Ollama 模型"""
        if profile:
            if profile.max_model_size_mb > 8000:
                # 大显存，可以用大模型
                if task_type in ("coding", "reasoning"):
                    return "qwen2:7b"
                return "qwen2:7b"
            elif profile.max_model_size_mb > 4000:
                # 中等显存
                return "qwen2:7b-q4"
            else:
                # 小显存
                return "qwen2:1.5b"
        return "qwen2:7b"  # 默认

    @staticmethod
    def _reorder_by_source(preferences: List[Tuple[SourceType, List[str]]],
                           target: SourceType) -> List[Tuple[SourceType, List[str]]]:
        """将指定来源提升到最前"""
        result = []
        for st, provs in preferences:
            if st == target:
                result.insert(0, (st, provs))
            else:
                result.append((st, provs))
        return result

    # ── 快捷方法 ──

    async def route_vision(self, messages: List[Dict]) -> HARoutingDecision:
        """视觉任务路由"""
        return await self.route("vision", messages, has_multimodal_input=True)

    async def route_asr(self, audio_path: str) -> HARoutingDecision:
        """语音识别路由"""
        return await self.route("asr", [], has_multimodal_input=True)

    async def route_with_image(self, messages: List[Dict], image_data: Any) -> HARoutingDecision:
        """带图片输入的路由"""
        return await self.route("vision", messages, has_multimodal_input=True)


# ── 全局单例 ──

_ha_router: Optional[HardwareAwareMultimodalRouter] = None

def get_ha_router() -> HardwareAwareMultimodalRouter:
    global _ha_router
    if _ha_router is None:
        _ha_router = HardwareAwareMultimodalRouter()
    return _ha_router


# ── Sentinel ──

HARDWARE_AWARE_MULTIMODAL_ROUTER_SENTINEL: str = (
    "HARDWARE_AWARE_MULTIMODAL_ROUTER_V1: core/hardware_aware_multimodal_router.py | "
    "Multimodal-local-first, hardware-aware, HuggingFace-integrated routing. "
    "Routing priority: local_multimodal > api_multimodal > local_llm > api_llm > hf_downloadable. "
    "Inspired by llama.cpp offload + vLLM memory management + Ollama UX."
)
