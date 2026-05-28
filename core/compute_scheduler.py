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
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ComputeScheduler")


# PR-D8: GPU temperature protection helper
async def _check_gpu_temperature() -> bool:
    """Check GPU temperature. Returns False if overheated (>85C)."""
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        if temp > 85:  # 85C threshold
            logger.warning("GPU temperature %dC > 85C, pausing inference", temp)
            return False  # Pause
        return True
    except Exception:
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
    """

    model_id: str
    backend: str
    device: str
    quantization: str
    n_gpu_layers: int
    reason: str
    timestamp: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    @property
    def is_gpu(self) -> bool:
        return self.device.startswith("cuda")

    @property
    def is_offloaded(self) -> bool:
        return 0 < self.n_gpu_layers < 999


@dataclass
class SchedulerConfig:
    """Configurable thresholds for the compute scheduler."""

    # VRAM thresholds (ratio of total VRAM used)
    vram_critical: float = 0.92     # Critical -- must release immediately
    vram_warning: float = 0.85      # Warning -- suggest degradation
    vram_optimal: float = 0.70      # Optimal -- can load new models

    # Safety margins (multiply required size by this factor)
    margin_full: float = 1.3        # Full precision margin
    margin_quantized: float = 0.8   # Quantized margin
    margin_hybrid: float = 0.5      # Hybrid offload margin

    # Default layer count estimate
    default_layer_count: int = 32

    # Quantization size reduction factors
    q4_factor: float = 0.25         # Q4 is ~1/4 of fp16
    q5_factor: float = 0.3125       # Q5 is ~5/16 of fp16
    q8_factor: float = 0.5          # Q8 is ~1/2 of fp16

    # Monitoring interval
    monitor_interval_sec: float = 30.0

    # Maximum number of concurrently loaded GPU models
    max_gpu_models: int = 3


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
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(interval), name="ComputeSchedulerMonitor"
        )
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
    ) -> ModelAllocation:
        """Decide how to load a model.

        This is the main entry point -- given a model's size and
        requirements, produce an optimal allocation plan.

        Parameters:
            model_id:             Model identifier (e.g. "llama3-8b")
            model_size_mb:        Estimated model size in megabytes
            requires_multimodal:  If True, requires vision capability
            preferred_backend:    User-preferred backend (optional)

        Returns:
            ModelAllocation with the decision
        """
        async with self._lock:
            return await self._schedule_model_locked(
                model_id, model_size_mb, requires_multimodal, preferred_backend
            )

    async def _schedule_model_locked(
        self,
        model_id: str,
        model_size_mb: int,
        requires_multimodal: bool,
        preferred_backend: Optional[str],
    ) -> ModelAllocation:
        from core.hardware_compute_profiler import get_hardware_profiler

        profiler = get_hardware_profiler()
        profile = profiler.profile_sync()
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
        gpu_models = [
            (mid, alloc)
            for mid, alloc in self._models.items()
            if alloc.is_gpu
        ]

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
