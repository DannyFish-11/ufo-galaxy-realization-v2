"""
本地主脑管理器 (Local Brain Manager)
====================================

负责管理本地 LLM 主脑（Ollama），确保其常驻运行，
管理本地模型（下载/切换/卸载），健康检查，
并向路由器报告可用性。

架构定位：
- 本地主脑优先策略的执行层
- MultiLLMRouter 的辅助组件
- 在 unified_launcher 启动序列中优先启动

LOCAL-BRAIN-FIRST:
- Ollama 作为默认主脑处理所有请求
- 超出本地能力时才调用云端 API
- 云端结果回流本地主脑整合
"""

import os
import sys
import json
import time
import asyncio
import logging
import subprocess
import shutil
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.LocalBrain")


class LocalBrainStatus(Enum):
    """本地主脑状态"""
    HEALTHY = "healthy"       # 正常运行
    DEGRADED = "degraded"     # 降级运行（模型少/VRAM紧张）
    STARTING = "starting"     # 正在启动
    STOPPED = "stopped"       # 已停止
    UNAVAILABLE = "unavailable"  # 不可用（Ollama未安装）


@dataclass
class HardwareProfile:
    """硬件画像 — 用于评估本地主脑能力"""
    vram_mb: int = 0              # 显存大小（MB）
    vram_used_mb: int = 0         # 已用显存（MB）
    system_ram_mb: int = 0        # 系统内存（MB）
    has_gpu: bool = False         # 是否有 GPU
    gpu_name: str = ""            # GPU 型号
    gpu_compute: str = ""         # 计算能力（如 8.6）
    cpu_cores: int = 0            # CPU 核心数
    quantization: str = "none"    # 当前量化方式

    def can_fit_model(self, model_size_mb: int) -> bool:
        """判断 VRAM 是否足够加载模型"""
        available_vram = self.vram_mb - self.vram_used_mb
        # 预留 10% 缓冲
        return available_vram * 0.9 >= model_size_mb


class LocalBrainManager:
    """本地主脑管理器

    职责：
    - 确保 Ollama 常驻运行
    - 管理本地模型（下载/切换/卸载）
    - 健康检查
    - 向路由器报告可用性
    - 硬件画像评估

    启动顺序（unified_launcher 中）：
    1. start_core() — 核心服务启动
    2. start_local_brain() — 本地主脑启动（本管理器）
    3. start_nodes() — 节点系统启动
    """

    # Ollama 默认地址
    OLLAMA_DEFAULT_URL = "http://localhost:11434"

    # 推荐的主脑模型（按任务类型）
    RECOMMENDED_MODELS = {
        "default": "gemma4:12b",          # Google Gemma 4 12B — 文本+视觉+工具调用
        "coding": "gemma4:12b",           # 代码生成
        "fast": "gemma4:e4b",             # 4B 快速响应
        "creative": "gemma4:12b",         # 创意任务
        "reasoning": "gemma4:12b",        # 推理任务
        "multimodal": "minicpm-o4.5:9b",  # MiniCPM-o 4.5 全模态(看+听+说)
    }

    # 模型大小估算（MB，用于 VRAM 评估）
    MODEL_SIZE_ESTIMATE_MB = {
        # Gemma 4 系列
        "gemma4:12b": 8000,
        "gemma4:26b": 16000,
        "gemma4:31b": 20000,
        "gemma4:e2b": 1800,
        "gemma4:e4b": 3000,
        "gemma4:27b": 18000,
        # MiniCPM-o 4.5 全模态
        "minicpm-o4.5:9b": 6000,
        "minicpm-o4.5:3.5b": 2500,
        "minicpm-o4.5:2.5b": 1800,
        "minicpm-o4.5:8b": 5500,
        "minicpm-o4.5:7.6b": 5000,
        # 旧模型（兼容保留）
        "qwen2:7b": 4500,
        "qwen2:1.5b": 1000,
        "llama3:8b": 5000,
        "llama3:70b": 40000,
        "codellama:7b": 4500,
        "codellama:13b": 8000,
        "phi3:mini": 1800,
        "phi3:medium": 3500,
        "mistral:7b": 4500,
        "mixtral:8x7b": 28000,
        "deepseek-coder:6.7b": 4000,
        "gemma:7b": 4500,
        "vicuna:7b": 4500,
    }

    def __init__(self, backend: str = "auto", ollama_url: Optional[str] = None):
        """
        Args:
            backend: Inference backend ("auto" / "ollama" / "llama_cpp" / "transformers" / "vllm")
            ollama_url: Ollama service URL (only used when backend is "ollama" or "auto")
        """
        self.backend_name = backend
        self._backend = None  # LocalModelBackend instance
        self.ollama_url = ollama_url or os.environ.get("OLLAMA_URL", self.OLLAMA_DEFAULT_URL)
        self.available_models: List[str] = []
        self.brain_model: str = "gemma4:12b"  # 默认主脑 (Gemma 4 12B)
        self._healthy = False
        self._status = LocalBrainStatus.STOPPED
        self._hardware_profile: Optional[HardwareProfile] = None
        self._last_health_check = 0.0
        self._health_check_interval = 30.0  # 健康检查间隔（秒）
        self._lock = asyncio.Lock()

    # ───────── 生命周期管理 ─────────

    async def ensure_running(self) -> bool:
        """确保本地主脑就绪（自动选择最佳后端）

        Returns:
            bool: True 表示本地主脑可用，False 表示不可用
        """
        async with self._lock:
            # --- Multi-backend initialization ---
            if self.backend_name == "auto":
                # Auto-select the best backend based on hardware
                self.backend_name = await self._auto_select_backend()
                logger.info(
                    "自动选择推理后端: %s", self.backend_name
                )

            from core.local_model_backends import create_backend, detect_best_backend

            # Create backend instance if not already created
            if self._backend is None:
                try:
                    if self.backend_name == "ollama":
                        self._backend = create_backend(
                            "ollama", base_url=self.ollama_url
                        )
                    elif self.backend_name == "llama_cpp":
                        self._backend = create_backend("llama_cpp")
                    elif self.backend_name == "transformers":
                        self._backend = create_backend("transformers")
                    elif self.backend_name == "vllm":
                        self._backend = create_backend("vllm")
                    else:
                        # Fallback: try auto-detection
                        best = detect_best_backend(
                            has_gpu=self._hardware_profile.has_gpu
                            if self._hardware_profile
                            else None
                        )
                        self._backend = create_backend(best)
                        self.backend_name = best
                except Exception as exc:
                    logger.error(
                        "创建推理后端失败 [%s]: %s", self.backend_name, exc
                    )
                    self._status = LocalBrainStatus.UNAVAILABLE
                    self._healthy = False
                    return False

            # --- Ollama-specific path (legacy, most common) ---
            if self.backend_name == "ollama":
                return await self._ensure_ollama_running()

            # --- Generic backend path (llama_cpp / transformers / vllm) ---
            # Load the default brain model
            try:
                loaded = await self._backend.load_model(self.brain_model)
                if loaded:
                    self._healthy = await self._backend.health_check()
                    self.available_models = self._backend.list_models()
                    self._status = (
                        LocalBrainStatus.HEALTHY
                        if self._healthy
                        else LocalBrainStatus.DEGRADED
                    )
                    logger.info(
                        "本地主脑已就绪 [%s]: 模型=%s, 状态=%s",
                        self.backend_name,
                        self.available_models,
                        self._status.value,
                    )
                    return self._healthy
                else:
                    # Model load failed -- try fallback
                    logger.warning(
                        "模型加载失败 [%s]: %s, 尝试 Ollama 回退",
                        self.backend_name,
                        self.brain_model,
                    )
                    return await self._ensure_ollama_running()
            except Exception as exc:
                logger.error(
                    "本地主脑启动失败 [%s]: %s", self.backend_name, exc
                )
                # Fallback to Ollama
                return await self._ensure_ollama_running()

    async def _auto_select_backend(self) -> str:
        """Auto-select the best available backend

        Priority:
        1. llama_cpp (if llama-cpp-python installed + GPU available)
        2. ollama (if Ollama is installed/running)
        3. transformers (if transformers installed)
        4. vllm (for high-concurrency scenarios)

        Returns:
            Backend name string
        """
        from core.local_model_backends import list_available_backends

        available = list_available_backends()
        logger.debug("可用的推理后端: %s", available)

        # Detect GPU
        has_gpu = False
        try:
            import torch

            has_gpu = torch.cuda.is_available()
        except ImportError:
            pass

        # Priority 1: llama_cpp with GPU (fastest direct inference)
        if has_gpu and "llama_cpp" in available:
            # Check if we have any GGUF models in registry
            try:
                from core.huggingface_model_manager import (
                    get_hf_model_manager,
                    ModelFamily,
                )

                hf_mgr = get_hf_model_manager()
                local_llms = hf_mgr.list_local_models(family=ModelFamily.LLM)
                if any(m.is_gguf for m in local_llms):
                    logger.info(
                        "自动选择 llama_cpp 后端 (GPU + GGUF 模型可用)"
                    )
                    return "llama_cpp"
            except Exception as exc:
                logger.debug("llama_cpp GPU check failed: %s", exc)

        # Priority 2: Ollama (most stable, easiest setup)
        if "ollama" in available:
            # Check if Ollama is actually running
            try:
                import httpx

                resp = httpx.get(
                    f"{self.ollama_url}/api/tags", timeout=3.0
                )
                if resp.status_code == 200:
                    logger.info(
                        "自动选择 ollama 后端 (Ollama 正在运行)"
                    )
                    return "ollama"
            except Exception as exc:
                logger.debug("Ollama availability check failed: %s", exc)

        # Priority 3: llama_cpp without GPU (still works on CPU)
        if "llama_cpp" in available:
            logger.info("自动选择 llama_cpp 后端 (CPU 模式)")
            return "llama_cpp"

        # Priority 4: transformers
        if "transformers" in available:
            logger.info("自动选择 transformers 后端")
            return "transformers"

        # Priority 5: vllm (for high-concurrency)
        if "vllm" in available:
            logger.info("自动选择 vllm 后端")
            return "vllm"

        # Ultimate fallback
        logger.info("自动选择 ollama 后端 (默认)")
        return "ollama"

    async def _ensure_ollama_running(self) -> bool:
        """Legacy Ollama-specific startup path"""
        # 1. Check if Ollama is already running
        if await self._ping_ollama():
            self._status = LocalBrainStatus.HEALTHY
            self._healthy = True
            await self._refresh_model_list()
            logger.info(
                "本地主脑已就绪 [ollama]: %s (模型: %s)",
                self.ollama_url,
                self.available_models,
            )
            return True

        # 2. Ollama not running, try to start
        self._status = LocalBrainStatus.STARTING
        logger.info("Ollama 未运行，尝试启动...")

        if await self._start_ollama():
            # Wait for Ollama to fully start
            for attempt in range(10):
                await asyncio.sleep(1)
                if await self._ping_ollama():
                    self._status = LocalBrainStatus.HEALTHY
                    self._healthy = True
                    await self._refresh_model_list()
                    logger.info(
                        "本地主脑已启动 [ollama]: %s (模型: %s)",
                        self.ollama_url,
                        self.available_models,
                    )
                    return True

        # PR-I1: Auto-install Ollama if not found
        logger.info("Ollama not found, attempting auto-install...")
        installed = await self._auto_install_ollama()
        if installed:
            # Retry connection
            from core.local_model_backends import create_backend

            self.backend_name = "ollama"
            self._backend = create_backend("ollama", base_url=self.ollama_url)
            await self._backend.load_model(self.brain_model)
            for attempt in range(10):
                await asyncio.sleep(1)
                if await self._ping_ollama():
                    self._status = LocalBrainStatus.HEALTHY
                    self._healthy = True
                    await self._refresh_model_list()
                    logger.info(
                        "本地主脑已启动 [ollama-auto-install]: %s (模型: %s)",
                        self.ollama_url,
                        self.available_models,
                    )
                    return True

        # 3. Start failed
        self._status = LocalBrainStatus.UNAVAILABLE
        self._healthy = False
        logger.warning(
            "Ollama 不可用（未安装或未运行）。"
            "请安装: https://ollama.com/download"
        )
        return False

    async def stop(self):
        """停止本地主脑服务（优雅关闭）"""
        # Stop the active backend
        if self._backend is not None:
            try:
                for model_id in self._backend.list_models():
                    await self._backend.unload_model(model_id)
                logger.info("推理后端已卸载: %s", self.backend_name)
            except Exception as exc:
                logger.debug("卸载后端时出错: %s", exc)
            self._backend = None

        # Also stop Ollama if it was running
        if self.backend_name in ("ollama", "auto"):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.delete(f"{self.ollama_url}/api/delete", json={"name": ""}, timeout=5.0)
            except Exception as exc:
                logger.debug("Ollama cleanup delete failed: %s", exc)

            # 查找并终止 ollama 进程
            try:
                if sys.platform.startswith("win"):
                    subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], capture_output=True, timeout=10, encoding="utf-8", errors="replace")
                else:
                    subprocess.run(["pkill", "-f", "ollama"], capture_output=True, timeout=10, encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug(f"停止 Ollama 进程时出错: {e}")

        self._status = LocalBrainStatus.STOPPED
        self._healthy = False
        logger.info("本地主脑已停止")

    # ───────── 健康检查 ─────────

    async def health_check(self) -> Dict[str, Any]:
        """健康检查，更新 available_models 和硬件画像

        Returns:
            Dict: 健康状态报告
        """
        now = time.time()
        if now - self._last_health_check < self._health_check_interval:
            return self._get_status_dict()

        self._last_health_check = now

        # 更新硬件画像
        self._hardware_profile = await self._detect_hardware()

        # --- Multi-backend health check ---
        if self._backend is not None:
            try:
                self._healthy = await self._backend.health_check()
                self.available_models = self._backend.list_models()
                if self.available_models:
                    if (
                        self._hardware_profile
                        and self._hardware_profile.vram_used_mb
                        > self._hardware_profile.vram_mb * 0.9
                    ):
                        self._status = LocalBrainStatus.DEGRADED
                    else:
                        self._status = (
                            LocalBrainStatus.HEALTHY
                            if self._healthy
                            else LocalBrainStatus.DEGRADED
                        )
                else:
                    self._status = LocalBrainStatus.DEGRADED
            except Exception as exc:
                logger.warning("后端健康检查失败 [%s]: %s", self.backend_name, exc)
                self._healthy = False
                self._status = LocalBrainStatus.STOPPED
            return self._get_status_dict()

        # --- Legacy Ollama-only health check ---
        if not await self._ping_ollama():
            self._healthy = False
            self._status = LocalBrainStatus.STOPPED
            return self._get_status_dict()

        # 刷新模型列表
        await self._refresh_model_list()

        # 评估状态
        if self.available_models:
            self._healthy = True
            if (
                self._hardware_profile
                and self._hardware_profile.vram_used_mb
                > self._hardware_profile.vram_mb * 0.9
            ):
                self._status = LocalBrainStatus.DEGRADED
            else:
                self._status = LocalBrainStatus.HEALTHY
        else:
            self._status = LocalBrainStatus.DEGRADED

        return self._get_status_dict()

    # ───────── 模型管理 ─────────

    async def switch_brain(self, model_name: str) -> bool:
        """切换主脑模型

        Args:
            model_name: Ollama 模型名称（如 "qwen2:7b"）

        Returns:
            bool: 切换是否成功
        """
        # 检查模型是否已安装
        if model_name not in self.available_models:
            logger.info(f"模型 {model_name} 未安装，尝试拉取...")
            if not await self._pull_model(model_name):
                return False

        self.brain_model = model_name
        logger.info(f"主脑已切换为: {model_name}")
        return True

    async def pull_model(self, model_name: str) -> bool:
        """拉取（下载）Ollama 模型

        Args:
            model_name: 模型名称（如 "qwen2:7b"）

        Returns:
            bool: 下载是否成功
        """
        return await self._pull_model(model_name)

    async def remove_model(self, model_name: str) -> bool:
        """删除 Ollama 模型

        Args:
            model_name: 模型名称

        Returns:
            bool: 删除是否成功
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.delete(
                    f"{self.ollama_url}/api/delete",
                    json={"name": model_name},
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    logger.info(f"模型已删除: {model_name}")
                    await self._refresh_model_list()
                    return True
        except Exception as e:
            logger.warning(f"删除模型失败: {e}")
        return False

    def is_available(self) -> bool:
        """本地主脑是否可用

        Returns:
            bool: True 表示本地主脑可用
        """
        return self._healthy and self.available_models

    def get_status(self) -> Dict[str, Any]:
        """获取本地主脑状态

        Returns:
            Dict: 状态字典
        """
        return self._get_status_dict()

    def get_recommended_model(self, task_type: str = "default") -> str:
        """根据任务类型获取推荐的主脑模型

        Args:
            task_type: 任务类型（如 "coding", "fast", "creative", "reasoning"）

        Returns:
            str: 推荐的模型名称
        """
        recommended = self.RECOMMENDED_MODELS.get(task_type, self.RECOMMENDED_MODELS["default"])

        # 如果推荐模型已安装，直接使用
        if recommended in self.available_models:
            return recommended

        # 否则找第一个可用的类似模型
        for model in self.available_models:
            if task_type == "coding" and "code" in model.lower():
                return model
            if task_type == "fast" and any(x in model.lower() for x in ["phi", "mini"]):
                return model

        # 兜底：返回第一个可用模型或默认
        return self.available_models[0] if self.available_models else self.brain_model

    # ───────── 内部方法 ─────────

    async def _ping_ollama(self) -> bool:
        """Ping Ollama 服务"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                return resp.status_code == 200
        except Exception as exc:
            logger.debug("Ollama health check failed: %s", exc)
            return False

    async def _start_ollama(self) -> bool:
        """尝试启动 Ollama 服务"""
        try:
            # 检查 ollama 命令是否存在
            ollama_cmd = shutil.which("ollama")
            if not ollama_cmd:
                logger.warning("ollama 命令未找到，请安装 Ollama")
                return False

            # 后台启动 ollama serve
            subprocess.Popen(
                [ollama_cmd, "serve"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            logger.info("Ollama 服务已启动")
            return True

        except Exception as e:
            logger.warning(f"启动 Ollama 失败: {e}")
            return False

    async def _auto_install_ollama(self) -> bool:
        """Auto-download and install Ollama

        Supported platforms:
        - Windows: Download ollama-windows-amd64.exe
        - Linux: curl -fsSL https://ollama.com/install.sh | sh
        - macOS: brew install ollama or download pkg
        """
        import platform
        import subprocess

        system = platform.system()
        logger.info("Auto-installing Ollama for %s...", system)

        try:
            if system == "Windows":
                # Windows: Download installer
                ollama_dir = Path.home() / ".ollama"
                ollama_dir.mkdir(exist_ok=True)
                ollama_exe = ollama_dir / "ollama.exe"

                if not ollama_exe.exists():
                    import urllib.request

                    url = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.exe"
                    logger.info("Downloading Ollama from %s...", url)
                    urllib.request.urlretrieve(url, str(ollama_exe))
                    logger.info("Ollama downloaded to %s", ollama_exe)

                # Start Ollama
                subprocess.Popen(
                    [str(ollama_exe), "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                await asyncio.sleep(5)  # Wait for startup
                return True

            elif system == "Linux":
                result = subprocess.run(
                    ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                return result.returncode == 0

            elif system == "Darwin":  # macOS
                result = subprocess.run(
                    ["brew", "install", "ollama"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                return result.returncode == 0

        except Exception as exc:
            logger.error("Auto-install Ollama failed: %s", exc)

        return False

    async def _refresh_model_list(self):
        """刷新可用模型列表"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    self.available_models = [
                        m["name"] for m in data.get("models", [])
                    ]
        except Exception as e:
            logger.debug(f"刷新模型列表失败: {e}")
            self.available_models = []

    async def _pull_model(self, model_name: str) -> bool:
        """拉取 Ollama 模型"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/pull",
                    json={"name": model_name, "stream": False},
                )
                if resp.status_code == 200:
                    logger.info(f"模型拉取成功: {model_name}")
                    await self._refresh_model_list()
                    return True
        except Exception as e:
            logger.warning(f"拉取模型失败: {e}")
        return False

    async def _detect_hardware(self) -> HardwareProfile:
        """检测硬件画像"""
        profile = HardwareProfile()

        # 检测 GPU
        try:
            if shutil.which("nvidia-smi"):
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,compute_cap", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10.0
                )
                if result.returncode == 0:
                    line = result.stdout.strip().split("\n")[0]
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        profile.gpu_name = parts[0]
                        profile.vram_mb = int(float(parts[1]))
                        profile.vram_used_mb = int(float(parts[2]))
                        profile.has_gpu = True
                        if len(parts) >= 5:
                            profile.gpu_compute = parts[4]
        except Exception as e:
            logger.debug(f"GPU 检测失败: {e}")

        # 检测 CPU
        try:
            import multiprocessing
            profile.cpu_cores = multiprocessing.cpu_count()
        except Exception as exc:
            logger.debug("CPU count detection failed: %s", exc)

        # 检测系统内存
        try:
            import psutil
            mem = psutil.virtual_memory()
            profile.system_ram_mb = mem.total // (1024 * 1024)
        except Exception as exc:
            logger.debug("psutil memory detection failed: %s", exc)
            # fallback: 读取 /proc/meminfo
            try:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            profile.system_ram_mb = int(line.split()[1]) // 1024
                            break
            except Exception as exc:
                logger.debug("/proc/meminfo fallback failed: %s", exc)

        return profile

    def _get_status_dict(self) -> Dict[str, Any]:
        """生成状态字典"""
        return {
            "status": self._status.value,
            "healthy": self._healthy,
            "backend": self.backend_name,
            "backend_type": self._backend.name if self._backend else "ollama_legacy",
            "ollama_url": self.ollama_url,
            "brain_model": self.brain_model,
            "available_models": self.available_models,
            "model_count": len(self.available_models),
            "hardware": {
                "has_gpu": self._hardware_profile.has_gpu if self._hardware_profile else False,
                "gpu_name": self._hardware_profile.gpu_name if self._hardware_profile else "",
                "vram_mb": self._hardware_profile.vram_mb if self._hardware_profile else 0,
                "vram_used_mb": self._hardware_profile.vram_used_mb if self._hardware_profile else 0,
                "system_ram_mb": self._hardware_profile.system_ram_mb if self._hardware_profile else 0,
                "cpu_cores": self._hardware_profile.cpu_cores if self._hardware_profile else 0,
            } if self._hardware_profile else None,
        }


# ───────────────────── 便捷函数 ─────────────────────

_brain_manager_instance: Optional[LocalBrainManager] = None


def get_local_brain_manager(backend: str = "auto") -> LocalBrainManager:
    """获取本地主脑管理器单例

    Args:
        backend: 推理后端 ("auto" / "ollama" / "llama_cpp" / "transformers" / "vllm")
    """
    global _brain_manager_instance
    if _brain_manager_instance is None:
        _brain_manager_instance = LocalBrainManager(backend=backend)
    return _brain_manager_instance


async def start_local_brain(backend: str = "auto") -> bool:
    """启动本地主脑的便捷函数

    在 unified_launcher 的启动序列中调用。

    Args:
        backend: 推理后端 ("auto" / "ollama" / "llama_cpp" / "transformers" / "vllm")

    Returns:
        bool: True 表示本地主脑已就绪
    """
    brain = get_local_brain_manager(backend=backend)
    result = await brain.ensure_running()
    if result:
        # 执行一次健康检查获取完整状态
        status = await brain.health_check()
        hw = status.get("hardware", {})
        backend_name = status.get("backend", "unknown")
        if hw and hw.get("has_gpu"):
            logger.info(
                "本地主脑 [%s] GPU: %s | VRAM: %dMB/%dMB | 模型: %d个",
                backend_name,
                hw.get("gpu_name", "Unknown"),
                hw.get("vram_used_mb", 0),
                hw.get("vram_mb", 0),
                status.get("model_count", 0),
            )
        else:
            logger.info(
                "本地主脑 [%s] CPU 模式 | 模型: %d个",
                backend_name,
                status.get("model_count", 0),
            )
    return result


async def check_local_brain() -> Dict[str, Any]:
    """检查本地主脑状态的便捷函数

    Returns:
        Dict: 本地主脑状态
    """
    brain = get_local_brain_manager()
    return await brain.health_check()