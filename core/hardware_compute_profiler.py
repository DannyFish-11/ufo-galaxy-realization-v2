"""
core.hardware_compute_profiler — GPU/CPU/Memory 实时硬件画像
================================================================

借鉴 llama.cpp 的 CPU/GPU 混合推理策略、vLLM 的显存管理、SGLang 的
调度器设计，为 Galaxy 提供细粒度的硬件感知能力。

核心能力：
- 实时检测 GPU (NVIDIA/AMD/Intel) 的显存、利用率、温度
- 实时检测 CPU 核心数、频率、AVX 指令集支持
- 实时检测系统内存使用
- 提供 ComputeProfile 画像供路由器动态决策
- GPU 满载时自动建议降级策略（量化层卸载 → CPU 回退 → API 兜底）

设计原则（来自 llama.cpp/vLLM/SGLang 的最佳实践）：
- GPU 只做昂贵且有价值的认知推理
- CPU 负责持续存在的轻量任务
- 内存负责 KV cache 和会话状态缓存
- 显存 > 85% 时触发 graceful degradation
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.HardwareProfiler")


# ---------------------------------------------------------------------------
# Compute Tier — 计算层级（借鉴 llama.cpp 的 offload 策略）
# ---------------------------------------------------------------------------

class ComputeTier(str, Enum):
    """硬件计算层级，从高到低排列。

    llama.cpp 策略参考：
    - GPU_FULL: 所有层放 GPU，最快
    - GPU_QUANTIZED: 量化后放 GPU，节省 VRAM
    - GPU_CPU_HYBRID: 部分层 GPU，部分 CPU offload
    - CPU_AVX512: CPU AVX512 加速（如 Intel Xeon）
    - CPU_AVX2: CPU AVX2 加速（主流消费级）
    - REMOTE_API: 远程 API，不消耗本地资源
    """
    GPU_FULL = "gpu_full"                  # 全精度 GPU
    GPU_QUANTIZED = "gpu_quantized"        # 量化 GPU（Q4/Q5/Q8）
    GPU_CPU_HYBRID = "gpu_cpu_hybrid"      # 层卸载混合
    CPU_AVX512 = "cpu_avx512"              # AVX512 CPU
    CPU_AVX2 = "cpu_avx2"                  # AVX2 CPU
    CPU_BASELINE = "cpu_baseline"          # 基础 CPU
    REMOTE_API = "remote_api"              # 远程 API


class GPUVendor(str, Enum):
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GPUProfile:
    """单个 GPU 的画像"""
    index: int
    vendor: GPUVendor
    name: str
    total_vram_mb: int
    free_vram_mb: int
    used_vram_mb: int
    utilization_percent: float
    temperature_c: float
    compute_capability: str = ""  # e.g. "8.6" for CUDA
    supports_fp16: bool = True
    supports_int8: bool = True

    @property
    def vram_usage_ratio(self) -> float:
        if self.total_vram_mb == 0:
            return 0.0
        return self.used_vram_mb / self.total_vram_mb

    @property
    def can_fit_model(self, model_size_mb: int = 4000) -> bool:
        """检查是否能容纳指定大小的模型（默认 4GB）"""
        return self.free_vram_mb > model_size_mb * 1.2  # 20% 余量


@dataclass
class CPUProfile:
    """CPU 画像"""
    brand: str
    physical_cores: int
    logical_cores: int
    frequency_mhz: float
    avx_support: str  # "avx512", "avx2", "avx", "none"
    usage_percent: float
    available_ram_mb: int
    total_ram_mb: int

    @property
    def tier(self) -> ComputeTier:
        if self.avx_support == "avx512":
            return ComputeTier.CPU_AVX512
        elif self.avx_support in ("avx2", "avx"):
            return ComputeTier.CPU_AVX2
        return ComputeTier.CPU_BASELINE


@dataclass
class ComputeProfile:
    """全局计算画像 — 路由器用此做动态决策"""
    timestamp: float
    gpus: List[GPUProfile]
    cpu: CPUProfile
    # 策略建议
    recommended_tier: ComputeTier
    recommended_quantization: str  # "none", "q4", "q5", "q8"
    can_run_local_multimodal: bool
    can_run_local_llm: bool
    # 降级建议（显存紧张时）
    degradation_needed: bool
    degradation_steps: List[str]  # e.g. ["quantize_to_q4", "offload_layers_to_cpu", "fallback_to_api"]
    # 模型大小建议
    max_model_size_mb: int  # 建议加载的最大模型大小


# ---------------------------------------------------------------------------
# Hardware Compute Profiler
# ---------------------------------------------------------------------------

class HardwareComputeProfiler:
    """硬件计算画像器 — 单例模式

    借鉴：
    - llama.cpp 的 --gpu-layers / --main-gpu 参数策略
    - vLLM 的 GPU memory profiling
    - SGLang 的 Scheduler resource awareness
    """
    _instance: Optional[HardwareComputeProfiler] = None
    _lock = threading.Lock()

    # 显存阈值策略（借鉴 vLLM 内存管理）
    VRAM_CRITICAL_THRESHOLD = 0.90  # >90% 严重，必须释放
    VRAM_WARNING_THRESHOLD = 0.85   # >85% 警告，建议降级
    VRAM_OPTIMAL_THRESHOLD = 0.70   # <70% 最优，可加载新模型

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._latest_profile: Optional[ComputeProfile] = None
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._profile_lock = asyncio.Lock()

        # 初始化时做一次完整检测
        self._detect_avx()
        logger.info(
            "HardwareComputeProfiler initialized | AVX=%s | CUDA available=%s",
            self._avx_support,
            self._cuda_available(),
        )

    # ── AVX 检测（借鉴 llama.cpp CPU 优化） ──

    _avx_support: str = "none"

    def _detect_avx(self) -> None:
        """检测 CPU AVX 指令集支持"""
        try:
            import cpuinfo
            info = cpuinfo.get_cpu_info()
            flags = info.get("flags", [])
            if "avx512f" in flags or "avx512" in str(flags):
                self._avx_support = "avx512"
            elif "avx2" in flags:
                self._avx_support = "avx2"
            elif "avx" in flags:
                self._avx_support = "avx"
            else:
                self._avx_support = "none"
        except ImportError:
            # fallback: 尝试通过 /proc/cpuinfo
            try:
                with open("/proc/cpuinfo") as f:
                    flags = f.read()
                if "avx512" in flags:
                    self._avx_support = "avx512"
                elif "avx2" in flags:
                    self._avx_support = "avx2"
                elif "avx" in flags:
                    self._avx_support = "avx"
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                self._avx_support = "none"

    # ── CUDA 检测 ──

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    # ── GPU 画像（NVIDIA 优先，借鉴 vLLM） ──

    def _profile_gpus(self) -> List[GPUProfile]:
        """检测所有可用 GPU"""
        gpus: List[GPUProfile] = []

        # NVIDIA via PyTorch
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    total = props.total_memory // (1024 * 1024)  # MB
                    allocated = torch.cuda.memory_allocated(i) // (1024 * 1024)
                    reserved = torch.cuda.memory_reserved(i) // (1024 * 1024)
                    used = max(allocated, reserved)

                    gpus.append(GPUProfile(
                        index=i,
                        vendor=GPUVendor.NVIDIA,
                        name=torch.cuda.get_device_name(i),
                        total_vram_mb=total,
                        free_vram_mb=total - used,
                        used_vram_mb=used,
                        utilization_percent=0.0,  # 需要 nvidia-ml-py
                        temperature_c=0.0,
                        compute_capability=f"{props.major}.{props.minor}",
                    ))
        except ImportError:
            pass

        # NVIDIA via nvidia-ml-py (更详细的监控)
        if not gpus:
            try:
                import pynvml
                pynvml.nvmlInit()
                for i in range(pynvml.nvmlDeviceGetCount()):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    try:
                        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    except Exception as exc:
                        logger.debug("Fallback triggered: %s", exc)
                        temp = 0

                    gpus.append(GPUProfile(
                        index=i,
                        vendor=GPUVendor.NVIDIA,
                        name=pynvml.nvmlDeviceGetName(handle).decode("utf-8"),
                        total_vram_mb=mem.total // (1024 * 1024),
                        free_vram_mb=mem.free // (1024 * 1024),
                        used_vram_mb=mem.used // (1024 * 1024),
                        utilization_percent=util.gpu,
                        temperature_c=temp,
                    ))
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # AMD GPU (rocm)
        if not gpus:
            try:
                result = subprocess.run(
                    ["rocm-smi", "--showmeminfo", "VRAM", "--json"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    # 简化处理
                    gpus.append(GPUProfile(
                        index=0,
                        vendor=GPUVendor.AMD,
                        name="AMD GPU (rocm)",
                        total_vram_mb=0, free_vram_mb=0, used_vram_mb=0,
                        utilization_percent=0.0, temperature_c=0.0,
                    ))
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # Intel GPU
        if not gpus:
            try:
                import intel_extension_for_pytorch as ipex
                if hasattr(ipex, "xpu") and ipex.xpu.is_available():
                    gpus.append(GPUProfile(
                        index=0,
                        vendor=GPUVendor.INTEL,
                        name="Intel XPU",
                        total_vram_mb=0, free_vram_mb=0, used_vram_mb=0,
                        utilization_percent=0.0, temperature_c=0.0,
                    ))
            except ImportError:
                pass

        return gpus

    # ── CPU 画像 ──

    def _profile_cpu(self) -> CPUProfile:
        """检测 CPU 状态"""
        try:
            import psutil
            cpu_freq = psutil.cpu_freq()
            mem = psutil.virtual_memory()
            return CPUProfile(
                brand=self._get_cpu_brand(),
                physical_cores=psutil.cpu_count(logical=False) or 1,
                logical_cores=psutil.cpu_count(logical=True) or 1,
                frequency_mhz=cpu_freq.current if cpu_freq else 0.0,
                avx_support=self._avx_support,
                usage_percent=psutil.cpu_percent(interval=0.1),
                available_ram_mb=mem.available // (1024 * 1024),
                total_ram_mb=mem.total // (1024 * 1024),
            )
        except ImportError:
            return CPUProfile(
                brand="unknown", physical_cores=1, logical_cores=1,
                frequency_mhz=0.0, avx_support=self._avx_support,
                usage_percent=0.0, available_ram_mb=0, total_ram_mb=0,
            )

    @staticmethod
    def _get_cpu_brand() -> str:
        try:
            import cpuinfo
            return cpuinfo.get_cpu_info().get("brand_raw", "unknown")
        except Exception as exc:
            return "unknown"

    # ── 策略决策（核心） ──

    def _decide_strategy(self, gpus: List[GPUProfile], cpu: CPUProfile) -> Tuple[ComputeTier, str, bool, bool, bool, List[str], int]:
        """根据硬件状态决定计算策略

        返回: (tier, quantization, can_multimodal, can_llm, degrade, steps, max_model_mb)
        """
        if not gpus:
            # 无 GPU，纯 CPU
            tier = cpu.tier
            return tier, "none", False, tier != ComputeTier.CPU_BASELINE, False, [], 2000

        primary_gpu = gpus[0]
        vram_ratio = primary_gpu.vram_usage_ratio
        free_vram = primary_gpu.free_vram_mb

        # 策略决策（借鉴 llama.cpp + vLLM）
        if vram_ratio < self.VRAM_OPTIMAL_THRESHOLD:
            # 显存充裕
            if free_vram > 12000:
                return ComputeTier.GPU_FULL, "none", True, True, False, [], 10000
            elif free_vram > 6000:
                return ComputeTier.GPU_FULL, "none", True, True, False, [], 5000
            elif free_vram > 4000:
                return ComputeTier.GPU_QUANTIZED, "q8", True, True, False, [], 3500
            else:
                return ComputeTier.GPU_QUANTIZED, "q4", False, True, False, [], 2500

        elif vram_ratio < self.VRAM_WARNING_THRESHOLD:
            # 显存适中，建议量化
            degradation_steps = []
            if free_vram < 4000:
                degradation_steps.append("quantize_to_q4")
            return ComputeTier.GPU_QUANTIZED, "q4", False, True, False, degradation_steps, 2000

        elif vram_ratio < self.VRAM_CRITICAL_THRESHOLD:
            # 显存紧张，需要层卸载
            return (
                ComputeTier.GPU_CPU_HYBRID, "q4", False, True, True,
                ["offload_layers_to_cpu", "reduce_batch_size"], 1500
            )

        else:
            # 显存临界，必须降级到 CPU 或 API
            return (
                cpu.tier, "q4", False, cpu.tier != ComputeTier.CPU_BASELINE, True,
                ["offload_all_to_cpu", "fallback_to_api_if_too_slow"], 1000
            )

    # ── 公共 API ──

    async def profile(self) -> ComputeProfile:
        """获取当前硬件画像"""
        async with self._profile_lock:
            gpus = self._profile_gpus()
            cpu = self._profile_cpu()
            tier, quant, can_mm, can_llm, degrade, steps, max_model = self._decide_strategy(gpus, cpu)

            self._latest_profile = ComputeProfile(
                timestamp=time.time(),
                gpus=gpus,
                cpu=cpu,
                recommended_tier=tier,
                recommended_quantization=quant,
                can_run_local_multimodal=can_mm,
                can_run_local_llm=can_llm,
                degradation_needed=degrade,
                degradation_steps=steps,
                max_model_size_mb=max_model,
            )
            return self._latest_profile

    def profile_sync(self) -> ComputeProfile:
        """同步获取画像（用于非 async 上下文）"""
        if self._latest_profile and time.time() - self._latest_profile.timestamp < 30:
            return self._latest_profile
        # 做一次简单检测
        gpus = self._profile_gpus()
        cpu = self._profile_cpu()
        tier, quant, can_mm, can_llm, degrade, steps, max_model = self._decide_strategy(gpus, cpu)
        self._latest_profile = ComputeProfile(
            timestamp=time.time(), gpus=gpus, cpu=cpu,
            recommended_tier=tier, recommended_quantization=quant,
            can_run_local_multimodal=can_mm, can_run_local_llm=can_llm,
            degradation_needed=degrade, degradation_steps=steps,
            max_model_size_mb=max_model,
        )
        return self._latest_profile

    @property
    def latest(self) -> Optional[ComputeProfile]:
        return self._latest_profile

    # ── 持续监控 ──

    async def start_monitoring(self, interval_sec: float = 30.0):
        """启动后台硬件监控"""
        if self._monitoring:
            return
        self._monitoring = True

        async def _loop():
            while self._monitoring:
                try:
                    await self.profile()
                    prof = self._latest_profile
                    if prof and prof.degradation_needed:
                        logger.warning(
                            "Hardware degradation detected | tier=%s steps=%s",
                            prof.recommended_tier.value, prof.degradation_steps
                        )
                except Exception as exc:
                    logger.debug("Hardware monitoring tick failed: %s", exc)
                await asyncio.sleep(interval_sec)

        self._monitor_task = asyncio.create_task(_loop())
        logger.info("Hardware monitoring started (interval=%.0fs)", interval_sec)

    def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()


# ── 全局单例 ──

_profiler: Optional[HardwareComputeProfiler] = None

def get_hardware_profiler() -> HardwareComputeProfiler:
    global _profiler
    if _profiler is None:
        _profiler = HardwareComputeProfiler()
    return _profiler


def get_compute_profile_sync() -> ComputeProfile:
    """快速获取当前计算画像（供路由器等非 async 代码使用）"""
    return get_hardware_profiler().profile_sync()


# ── Sentinel ──

HARDWARE_COMPUTE_PROFILER_SENTINEL: str = (
    "HARDWARE_COMPUTE_PROFILER_V1: core/hardware_compute_profiler.py | "
    "GPU-aware, CPU-AVX-aware, memory-aware compute profiling. "
    "Inspired by llama.cpp offload strategy + vLLM memory management. "
    "Provides ComputeProfile for dynamic routing decisions."
)
