"""
core.compute_scheduler -- GPU/CPU Compute Maximization Scheduler
================================================================

Inspired by:
- llama.cpp: layer-offloading strategy (--gpu-layers)
- vLLM: PagedAttention memory management
- SGLang: continuous batching + prefix caching

Responsibilities:
- Real-time monitoring of GPU/CPU/Memory
- Automatic model allocation based on hardware state
- Automatic quantization degradation when VRAM is tight
- On-demand model loading / unloading
- GPU handles expensive inference; CPU handles lightweight tasks

Usage::

    from core.compute_scheduler import get_compute_scheduler, ModelAllocation

    scheduler = get_compute_scheduler()
    await scheduler.start_monitoring(interval=30.0)

    # Decide how to load a model
    alloc = await scheduler.schedule_model("llama3-8b", model_size_mb=4800)
    print(alloc.backend, alloc.device, alloc.quantization)

    # Check current allocations
    allocations = scheduler.list_allocations()

    # Release models if VRAM is critical
    await scheduler.release_if_needed()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.ComputeScheduler")


# PR-D8: GPU temperature protection helper
_gpu_temp_probe_warned = False


async def _check_gpu_temperature() -> bool:
    """Check GPU temperature. Returns False if overheated (>85C).

    探测失败时放行(无读数就无法判定过热),但**只**在第一次失败时告警一次:
    否则 NVML 初始化失败会让整套温控在有 GPU 的机器上永久静默失效,
    而调用方看到的仍是一个正常的 True。
    """
    global _gpu_temp_probe_warned
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        if temp > 85:  # 85C threshold
            logger.warning("GPU temperature %dC > 85C, pausing inference", temp)
            return False  # Pause
        return True
    except Exception as exc:
        if not _gpu_temp_probe_warned:
            _gpu_temp_probe_warned = True
            logger.warning(
                "GPU temperature probe unavailable (%s); thermal protection is INACTIVE "
                "for this process (further occurrences suppressed)",
                exc,
            )
        return True


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ModelAllocation:
    """Model allocation decision produced by the scheduler.

    Attributes:
        model_id:       Model identifier string
        backend:        Execution backend ("ollama" / "llama_cpp" / "transformers" / "vllm" / "cpu")
        device:         Target device ("cuda:0" / "cuda:1" / "cpu")
        quantization:   Quantization level ("none" / "q8" / "q5" / "q4")
        n_gpu_layers:   Number of layers on GPU (-1 = all, 0 = CPU, partial = hybrid)
        reason:         Human-readable explanation for the decision
        timestamp:      When the allocation was created
        last_accessed:  Last access timestamp (for LRU eviction)
        is_moe:         该模型是否 MoE 架构（专家 FFN 可与注意力/共享层分开落位）
        n_cpu_moe:      专家权重留在 CPU 的层数（对齐 llama.cpp ``--n-cpu-moe`` 语义）
                        0 = 不卸载（专家跟随 n_gpu_layers）；N>0 = 顶部 N 层专家留 CPU；
                        -1 = 全部 MoE 层的专家留 CPU（极端省显存）
    """

    model_id: str
    backend: str
    device: str
    quantization: str
    n_gpu_layers: int
    reason: str
    timestamp: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    # MoE 专家卸载:与 n_gpu_layers 是【正交两轴】—— n_gpu_layers 决定"哪些层的
    # 注意力/共享部分上 GPU",n_cpu_moe 决定"其中哪些层的专家 FFN 留在内存"。
    # 这正是 MoE 能在小显存跑大模型的机制:专家占权重的绝大头但每 token 只激活少数。
    # 默认值保证既有分配路径逐字节不变。
    is_moe: bool = False
    n_cpu_moe: int = 0

    @property
    def is_gpu(self) -> bool:
        return self.device.startswith("cuda")

    @property
    def is_offloaded(self) -> bool:
        return 0 < self.n_gpu_layers < 999

    @property
    def is_expert_offloaded(self) -> bool:
        return self.is_moe and self.n_cpu_moe != 0


@dataclass
class SchedulerConfig:
    """Configurable thresholds for the compute scheduler."""

    # VRAM thresholds (ratio of total VRAM used)
    vram_critical: float = 0.92  # Critical -- must release immediately
    vram_warning: float = 0.85  # Warning -- suggest degradation
    vram_optimal: float = 0.70  # Optimal -- can load new models

    # Safety margins (multiply required size by this factor)
    margin_full: float = 1.3  # Full precision margin
    margin_quantized: float = 0.8  # Quantized margin
    margin_hybrid: float = 0.5  # Hybrid offload margin

    # Default layer count estimate
    default_layer_count: int = 32

    # Quantization size reduction factors
    q4_factor: float = 0.25  # Q4 is ~1/4 of fp16
    q5_factor: float = 0.3125  # Q5 is ~5/16 of fp16
    q8_factor: float = 0.5  # Q8 is ~1/2 of fp16

    # Monitoring interval
    monitor_interval_sec: float = 30.0

    # Maximum number of concurrently loaded GPU models
    max_gpu_models: int = 3

    # ── MoE 专家卸载 ────────────────────────────────────────────────────────
    # 专家 FFN 占整模型权重的比例。MoE 模型典型 85–95%（共享专家多的偏低）。
    # 保守取 0.90:估高了会少卸（欠用显存，安全）；估低了才会 OOM。
    moe_expert_fraction: float = 0.90
    # 显存/内存的实测可用量上再打的安全系数（与 _estimate_gpu_layers 的 0.8 同源）。
    moe_vram_safety: float = 0.8
    # 被卸到 CPU 的专家最多占用可用内存的比例（其余留给 KV cache 与系统）。
    moe_ram_budget: float = 0.7


# ---------------------------------------------------------------------------
# ComputeScheduler -- singleton
# ---------------------------------------------------------------------------


class ComputeScheduler:
    """GPU/CPU compute scheduler -- singleton.

    Decision flow for ``schedule_model``::

        1. Get hardware profile from HardwareComputeProfiler
        2. If no GPU -> pure CPU fallback
        3. Check VRAM availability against thresholds
        4. Sufficient -> full GPU (no quantization)
        5. Moderate  -> Q8 GPU
        6. Tight     -> Q4 + partial GPU layers
        7. Insufficient -> CPU fallback (Ollama)

    All methods are async-safe (uses internal lock).
    """

    _instance: Optional[ComputeScheduler] = None

    def __new__(cls) -> ComputeScheduler:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[SchedulerConfig] = None) -> None:
        if self._initialized:
            return
        self._initialized = True

        self.config = config or SchedulerConfig()
        self._models: Dict[str, ModelAllocation] = {}  # loaded model_id -> allocation
        self._lock = asyncio.Lock()
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task[None]] = None

    # ── Properties ──

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring

    @property
    def loaded_model_count(self) -> int:
        return len(self._models)

    @property
    def gpu_model_count(self) -> int:
        return sum(1 for m in self._models.values() if m.is_gpu)

    # ── Monitoring lifecycle ──

    async def start_monitoring(self, interval: Optional[float] = None) -> None:
        """Start background hardware monitoring.

        Delegates to HardwareComputeProfiler for the actual
        hardware sampling; the scheduler just consumes the
        profile data.
        """
        if self._monitoring:
            logger.debug("Monitoring already running")
            return

        interval = interval or self.config.monitor_interval_sec

        # Delegate to hardware profiler
        from core.hardware_compute_profiler import get_hardware_profiler

        profiler = get_hardware_profiler()
        await profiler.start_monitoring(interval_sec=interval)

        # Start our own periodic check for release-if-needed
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval), name="ComputeSchedulerMonitor")
        logger.info("Compute scheduler monitoring started (interval=%.0fs)", interval)

    async def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._monitoring = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("Compute scheduler monitoring stopped")

    async def _monitor_loop(self, interval: float) -> None:
        """Periodic background task: release models if VRAM critical."""
        while self._monitoring:
            try:
                await self.release_if_needed()
            except Exception as exc:
                logger.debug("Monitor loop error: %s", exc)
            await asyncio.sleep(interval)

    # ── Core scheduling ──

    async def schedule_model(
        self,
        model_id: str,
        model_size_mb: int,
        requires_multimodal: bool = False,
        preferred_backend: Optional[str] = None,
        *,
        is_moe: bool = False,
    ) -> ModelAllocation:
        """Decide how to load a model.

        This is the main entry point -- given a model's size and
        requirements, produce an optimal allocation plan.

        Parameters:
            model_id:             Model identifier (e.g. "llama3-8b")
            model_size_mb:        Estimated model size in megabytes
            requires_multimodal:  If True, requires vision capability
            preferred_backend:    User-preferred backend (optional)
            is_moe:               模型是否 MoE 架构。为真时先尝试"注意力+共享层进 GPU、
                                  专家进内存"的拆分（判据全部来自**本机实测**硬件），
                                  拆不动则自然落到既有量化/CPU 分支。

        Returns:
            ModelAllocation with the decision
        """
        async with self._lock:
            return await self._schedule_model_locked(
                model_id, model_size_mb, requires_multimodal, preferred_backend, is_moe=is_moe
            )

    async def _schedule_model_locked(
        self,
        model_id: str,
        model_size_mb: int,
        requires_multimodal: bool,
        preferred_backend: Optional[str],
        *,
        is_moe: bool = False,
    ) -> ModelAllocation:
        from core.hardware_compute_profiler import get_hardware_profiler

        profiler = get_hardware_profiler()
        # 修复:profile_sync 缓存过期(>30s)时会跑 _profile_gpus(nvidia-smi 子进程)
        # + _profile_cpu,在这个 async 方法里同步调会阻塞事件循环。放线程跑。
        import asyncio as _asyncio

        profile = await _asyncio.to_thread(profiler.profile_sync)
        cfg = self.config

        # ── No GPU available -> pure CPU fallback ──
        if not profile.gpus:
            alloc = ModelAllocation(
                model_id=model_id,
                backend=preferred_backend or ("llama_cpp" if model_id.endswith(".gguf") else "ollama"),
                device="cpu",
                quantization="q4",
                n_gpu_layers=0,
                reason="No GPU available; pure CPU fallback",
            )
            self._models[model_id] = alloc
            return alloc

        # ── Select primary GPU (pick one with most free VRAM) ──
        gpu = max(profile.gpus, key=lambda g: g.free_vram_mb)
        device_str = f"cuda:{gpu.index}"
        free_vram = gpu.free_vram_mb
        vram_ratio = gpu.vram_usage_ratio

        logger.debug(
            "schedule_model(%s, %dMB) | GPU%d free=%dMB ratio=%.2f",
            model_id,
            model_size_mb,
            gpu.index,
            free_vram,
            vram_ratio,
        )

        # ── Decision branches ──

        # 0. MoE 专家卸载:显存放不下整模型，但放得下"注意力+共享层"时，把专家
        #    FFN 留在内存 —— 每 token 只激活少数专家，代价可接受，换来"带不动的
        #    模型跑起来"。判据全部来自本机实测（free VRAM / available RAM），
        #    不是外部传入的需求；拆不动返回 None，自然落到下面既有分支。
        if is_moe:
            _avail_ram = int(getattr(getattr(profile, "cpu", None), "available_ram_mb", 0) or 0)
            _n_cpu_moe = self._split_moe(model_size_mb, free_vram, _avail_ram, cfg)
            if _n_cpu_moe is not None:
                alloc = ModelAllocation(
                    model_id=model_id,
                    backend=preferred_backend or "llama_cpp",
                    device=device_str,
                    quantization="none",
                    n_gpu_layers=-1,  # 所有层的注意力/共享部分都上 GPU
                    reason=(
                        f"MoE 拆分:注意力+共享层进 GPU，{_n_cpu_moe}/{cfg.default_layer_count} 层专家进内存"
                        f"(实测 free={free_vram}MB, RAM={_avail_ram}MB)"
                    ),
                    is_moe=True,
                    n_cpu_moe=_n_cpu_moe,
                )
                self._models[model_id] = alloc
                return alloc
            logger.debug(
                "MoE 拆分不可行(free=%dMB, RAM=%dMB)，回落常规分支: %s",
                free_vram,
                int(getattr(getattr(profile, "cpu", None), "available_ram_mb", 0) or 0),
                model_id,
            )

        # 1. VRAM sufficient -> full precision GPU
        if free_vram > model_size_mb * cfg.margin_full and vram_ratio < cfg.vram_optimal:
            alloc = ModelAllocation(
                model_id=model_id,
                backend=preferred_backend or "llama_cpp",
                device=device_str,
                quantization="none",
                n_gpu_layers=-1,
                reason=f"VRAM sufficient ({free_vram}MB free), full GPU acceleration",
            )
            self._models[model_id] = alloc
            return alloc

        # 2. VRAM moderate -> Q8 quantized GPU
        q8_size = int(model_size_mb * cfg.q8_factor)
        if free_vram > q8_size * cfg.margin_quantized and vram_ratio < cfg.vram_warning:
            alloc = ModelAllocation(
                model_id=model_id,
                backend=preferred_backend or "llama_cpp",
                device=device_str,
                quantization="q8",
                n_gpu_layers=-1,
                reason=f"VRAM moderate ({free_vram}MB free), Q8 quantization",
            )
            self._models[model_id] = alloc
            return alloc

        # 3. VRAM tight -> Q4 quantized + partial layer offloading
        q4_size = int(model_size_mb * cfg.q4_factor)
        if free_vram > q4_size * cfg.margin_hybrid:
            n_layers = self._estimate_gpu_layers(model_size_mb, free_vram, cfg)
            alloc = ModelAllocation(
                model_id=model_id,
                backend=preferred_backend or "llama_cpp",
                device=device_str,
                quantization="q4",
                n_gpu_layers=n_layers,
                reason=f"VRAM tight ({free_vram}MB free), Q4 + {n_layers} GPU layers",
            )
            self._models[model_id] = alloc
            return alloc

        # 4. VRAM insufficient -> CPU fallback (Ollama)
        alloc = ModelAllocation(
            model_id=model_id,
            backend="ollama",
            device="cpu",
            quantization="q4",
            n_gpu_layers=0,
            reason=f"VRAM insufficient ({free_vram}MB free), CPU fallback via Ollama",
        )
        self._models[model_id] = alloc
        return alloc

    def _split_moe(
        self,
        model_size_mb: int,
        free_vram_mb: int,
        available_ram_mb: int,
        cfg: Optional[SchedulerConfig] = None,
    ) -> Optional[int]:
        """按**本机实测**显存/内存算 MoE 拆分：返回专家留 CPU 的层数，拆不动返回 None。

        MoE 的权重结构是"注意力/共享层小头 + 专家 FFN 大头"，而每 token 只激活
        少数专家。因此把专家放内存、注意力留显存，就能在显存装不下整模型时仍然
        以可接受的速度跑起来 —— 这正是"有能力的模型带不动"的解法。

        三道实测判据（任何一道不过就返回 None，交给既有量化/CPU 分支）：
        1. **共享层必须进得了显存**：连注意力都放不下，卸专家也无意义；
        2. **剩余显存能吃多少层专家**：吃不下的层数即 ``n_cpu_moe``；
        3. **内存兜得住被卸的专家**：否则换来的是疯狂换页，不如老实降级。

        Args:
            model_size_mb:     整模型大小（MB）
            free_vram_mb:      实测可用显存（来自 hardware_compute_profiler）
            available_ram_mb:  实测可用内存（同上；为 0 表示探测不到）
            cfg:               调度配置（默认取 self.config）

        Returns:
            专家留 CPU 的层数（1..layers_total），或 None 表示拆分不可行。
        """
        cfg = cfg or self.config
        layers_total = max(1, cfg.default_layer_count)
        if model_size_mb <= 0 or free_vram_mb <= 0:
            return None

        expert_mb = model_size_mb * cfg.moe_expert_fraction
        shared_mb = model_size_mb - expert_mb
        usable_vram = free_vram_mb * cfg.moe_vram_safety

        # 判据 1:共享层放不下 → 拆分无意义
        if shared_mb * cfg.margin_full > usable_vram:
            return None

        # 判据 2:剩余显存能容纳的专家层数
        expert_per_layer = expert_mb / layers_total
        if expert_per_layer <= 0:
            return None
        vram_for_experts = max(0.0, usable_vram - shared_mb * cfg.margin_full)
        gpu_expert_layers = int(vram_for_experts / expert_per_layer)
        gpu_expert_layers = max(0, min(layers_total, gpu_expert_layers))
        n_cpu_moe = layers_total - gpu_expert_layers
        if n_cpu_moe <= 0:
            # 显存足以容纳全部专家 → 不需要 MoE 拆分，走常规全量上 GPU 分支。
            return None

        # 判据 3:内存兜不住被卸的专家 → 老实降级（内存探测不到时同样不冒险）
        cpu_expert_mb = n_cpu_moe * expert_per_layer
        if available_ram_mb <= 0 or cpu_expert_mb > available_ram_mb * cfg.moe_ram_budget:
            return None

        return n_cpu_moe

    def _estimate_gpu_layers(
        self,
        model_size_mb: int,
        free_vram_mb: int,
        cfg: Optional[SchedulerConfig] = None,
    ) -> int:
        """Estimate how many layers can fit on GPU (llama.cpp strategy).

        Rough estimate: each layer ~ model_size / layer_count.
        With Q4 quantization each layer is ~ 1/4 of original.
        We use 80% of free VRAM as safety margin.

        Parameters:
            model_size_mb:  Total model size in MB
            free_vram_mb:   Available VRAM in MB
            cfg:            SchedulerConfig (uses defaults if None)

        Returns:
            Number of layers to offload to GPU (0 = all CPU)
        """
        cfg = cfg or self.config
        layers_total = cfg.default_layer_count

        bytes_per_layer = (model_size_mb * 1024 * 1024) // layers_total
        q4_bytes_per_layer = int(bytes_per_layer * cfg.q4_factor)
        safety_vram = int(free_vram_mb * 1024 * 1024 * 0.8)

        if q4_bytes_per_layer <= 0:
            return 0

        layers_gpu = safety_vram // q4_bytes_per_layer
        return max(0, min(layers_gpu, layers_total))

    # ── Model tracking ──

    def register_loaded(self, allocation: ModelAllocation) -> None:
        """Register that a model has been successfully loaded.

        Call this after the model is actually loaded in memory
        so the scheduler can track it.
        """
        self._models[allocation.model_id] = allocation
        logger.info(
            "Model registered: %s on %s (%s, %d GPU layers) -- %s",
            allocation.model_id,
            allocation.device,
            allocation.quantization,
            allocation.n_gpu_layers,
            allocation.reason,
        )

    def unregister(self, model_id: str) -> Optional[ModelAllocation]:
        """Remove a model from tracking."""
        alloc = self._models.pop(model_id, None)
        if alloc:
            logger.info("Model unregistered: %s", model_id)
        return alloc

    def touch(self, model_id: str) -> None:
        """Update last_accessed timestamp for LRU eviction."""
        if model_id in self._models:
            self._models[model_id].last_accessed = time.time()

    def list_allocations(self) -> List[ModelAllocation]:
        """Return a snapshot of all tracked allocations."""
        return list(self._models.values())

    def get_allocation(self, model_id: str) -> Optional[ModelAllocation]:
        """Get allocation for a specific model."""
        return self._models.get(model_id)

    # ── 换档：算目标档资源 → 驱逐 → 加载（唯一收口）──────────────────────────

    async def reconcile_tier(self, target_tier: str) -> List[ModelAllocation]:
        """把当前已加载模型对齐到目标档位。

        换档此前散在路由层（保存档位 + 逐个后台拉取 + 刷新路由），没有任何一处
        统一负责"目标档要多少资源、当前占着谁、该先卸谁"。资源判断的唯一权威是
        本调度器（账本 + 实测硬件），故换档在这里收口成一个动作：

        1. **算目标**：目标档的模型集合（目录 SSOT）；
        2. **驱逐**：账本里不属于目标档的，真卸载 + 注销记账（best-effort，
           单个失败不阻断整体）；
        3. **加载**：目标档中本地可加载的（source=local/llama_cpp），逐个走
           ``schedule_model``（MoE 型号自动尝试专家卸载拆分）后交后端加载。

        Returns:
            换档后的账本快照。
        """
        from core.model_catalog import resolve_is_moe as _resolve_is_moe  # noqa: PLC0415
        from core.model_catalog import tier_models  # noqa: PLC0415

        specs = list(tier_models(target_tier))
        target_ids = {s.tag for s in specs}

        # 1+2. 驱逐不属于目标档的
        for model_id in list(self._models.keys()):
            if model_id in target_ids:
                continue
            alloc = self._models.get(model_id)
            try:
                backend = self._backend_for(alloc)
                if backend is not None:
                    await backend.unload_model(model_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("换档卸载 %s 失败(继续注销记账): %s", model_id, exc)
            self.unregister(model_id)

        # 3. 加载目标档
        for spec in specs:
            if spec.source not in ("local", "llama_cpp"):
                continue
            try:
                backend_name = "llama_cpp" if spec.source == "llama_cpp" else "ollama"
                await self.schedule_model(
                    spec.tag,
                    int(spec.size_mb()),
                    preferred_backend=backend_name,
                    # 与 llama_cpp 加载路径同一判据（目录填过以目录为准，没填过看
                    # 命名惯例）。原来这里直接读 spec.is_moe，而那是个默认 False 的
                    # bool —— 换档加载的模型**永远**不会被认成 MoE，专家卸载静默失效。
                    is_moe=_resolve_is_moe(spec.tag),
                )
                backend = self._create_backend(backend_name)
                if backend is not None:
                    await backend.load_model(spec.tag)  # 内部会 register_loaded（幂等）
            except Exception as exc:  # noqa: BLE001
                logger.warning("换档加载 %s 失败(其余模型继续): %s", spec.tag, exc)

        return self.list_allocations()

    @staticmethod
    def _create_backend(name: str):
        try:
            from core.local_model_backends import create_backend  # noqa: PLC0415

            return create_backend(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("后端 %s 不可用: %s", name, exc)
            return None

    def _backend_for(self, alloc: Optional[ModelAllocation]):
        if alloc is None:
            return None
        return self._create_backend(alloc.backend)

    # ── VRAM pressure management ──

    async def release_if_needed(self) -> bool:
        """Release the least-recently-used GPU model when VRAM is critical.

        Returns True if a model was released, False otherwise.
        """
        from core.hardware_compute_profiler import get_hardware_profiler

        profiler = get_hardware_profiler()
        profile = profiler.profile_sync()

        if not profile.gpus:
            return False

        gpu = profile.gpus[0]
        if gpu.vram_usage_ratio < self.config.vram_critical:
            return False  # VRAM is fine

        logger.warning(
            "VRAM critical: %.1f%% used (threshold %.0f%%); releasing oldest model",
            gpu.vram_usage_ratio * 100,
            self.config.vram_critical * 100,
        )

        async with self._lock:
            return await self._release_oldest_locked()

    async def _release_oldest_locked(self) -> bool:
        """Release the least-recently-used GPU model.

        Must be called with _lock held.
        """
        # Find GPU models, sorted by last_accessed (oldest first)
        gpu_models = [(mid, alloc) for mid, alloc in self._models.items() if alloc.is_gpu]

        if not gpu_models:
            logger.warning("No GPU models to release; trying cache clear")
            self._clear_gpu_cache()
            return False

        # Sort by last_accessed ascending (oldest first)
        gpu_models.sort(key=lambda x: x[1].last_accessed)
        oldest_id, oldest = gpu_models[0]

        logger.info(
            "Releasing model '%s' (last used %.0fs ago, %s on %s)",
            oldest_id,
            time.time() - oldest.last_accessed,
            oldest.quantization,
            oldest.device,
        )

        # Remove from tracking
        del self._models[oldest_id]

        # Clear GPU cache
        self._clear_gpu_cache()

        return True

    @staticmethod
    def _clear_gpu_cache() -> None:
        """Attempt to clear GPU memory cache via PyTorch."""
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("GPU cache cleared (torch.cuda.empty_cache)")
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("GPU cache clear failed: %s", exc)

    # ── Quantization helpers ──

    @staticmethod
    def estimate_quantized_size(
        model_size_mb: int,
        quantization: str,
        cfg: Optional[SchedulerConfig] = None,
    ) -> int:
        """Estimate model size after quantization.

        Parameters:
            model_size_mb:  Original fp16 model size in MB
            quantization:   "none" / "q8" / "q5" / "q4"
            cfg:            SchedulerConfig

        Returns:
            Estimated size in MB after quantization
        """
        cfg = cfg or SchedulerConfig()
        factors = {
            "none": 1.0,
            "q8": cfg.q8_factor if cfg else 0.5,
            "q5": cfg.q5_factor if cfg else 0.3125,
            "q4": cfg.q4_factor if cfg else 0.25,
        }
        factor = factors.get(quantization, 1.0)
        return int(model_size_mb * factor)

    # ── Health check ──

    async def health_check(self) -> Dict[str, any]:
        """Return scheduler health status."""
        from core.hardware_compute_profiler import get_hardware_profiler

        profiler = get_hardware_profiler()
        profile = profiler.profile_sync()

        return {
            "monitoring": self._monitoring,
            "loaded_models": len(self._models),
            "gpu_models": self.gpu_model_count,
            "gpu_available": bool(profile.gpus),
            "vram_usage_ratio": profile.gpus[0].vram_usage_ratio if profile.gpus else 0.0,
            "recommended_tier": profile.recommended_tier.value if profile.recommended_tier else "unknown",
            "models": [
                {
                    "model_id": m.model_id,
                    "device": m.device,
                    "backend": m.backend,
                    "quantization": m.quantization,
                    "gpu_layers": m.n_gpu_layers,
                }
                for m in self._models.values()
            ],
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_scheduler: Optional[ComputeScheduler] = None
_scheduler_lock = asyncio.Lock()


async def get_compute_scheduler_async() -> ComputeScheduler:
    """Async-safe singleton accessor.

    Guarantees only one scheduler instance is created
    even under concurrent access.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    async with _scheduler_lock:
        if _scheduler is None:
            _scheduler = ComputeScheduler()
    return _scheduler


def get_compute_scheduler() -> ComputeScheduler:
    """Synchronous singleton accessor.

    Safe for single-threaded initialization.
    For async contexts prefer ``get_compute_scheduler_async()``.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = ComputeScheduler()
    return _scheduler


# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

COMPUTE_SCHEDULER_SENTINEL: str = (
    "COMPUTE_SCHEDULER_V1: core/compute_scheduler.py | "
    "GPU/CPU compute maximization scheduler. "
    "Inspired by llama.cpp offload + vLLM memory management + SGLang batching. "
    "Auto-quantization, auto-offload, LRU-based VRAM pressure relief."
)
