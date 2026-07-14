import os
import sys
import time
import asyncio
import logging
import subprocess
import shutil
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
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
        # MiniCPM-o 4.5 全模态(看+听+说) — Ollama 真实 tag 带 openbmb/ 命名空间，
        # 此前误写为 "minicpm-o4.5:9b" 会 pull 失败 → 本地多模态静默不可用。
        "multimodal": "openbmb/minicpm-o4.5",
    }

    # 模型大小估算（MB，用于 VRAM 评估）
    MODEL_SIZE_ESTIMATE_MB = {
        # Gemma 4 系列（Ollama 官方 library 真实 tag）
        "gemma4:12b": 8000,
        "gemma4:26b": 16000,
        "gemma4:31b": 20000,
        "gemma4:e2b": 1800,
        "gemma4:e4b": 3000,
        # MiniCPM-o 4.5 全模态（9B）
        "openbmb/minicpm-o4.5": 6000,
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

    @staticmethod
    def _normalize_ollama_url(raw: str) -> str:
        """确保 URL 非空且带 http(s):// 协议头。

        两类真机故障都在这里兜底:
        1) 用户在面板「模型」tab 只填 host:port(如 "localhost:11434")无协议头。
        2) **空值**:面板保存配置会把 OLLAMA_URL="" 同步进【运行进程的 os.environ】,
           于是 ``os.environ.get("OLLAMA_URL", DEFAULT)`` 返回的是 ""(键存在)、
           不是默认值。此前本函数对空值【原样返回 ""】→ self.ollama_url="" →
           每个 ``f"{self.ollama_url}/api/tags"`` 都炸 "Request URL is missing an
           'http://'..."(克隆界面探测 Ollama 时那个 HTTP 报错、Ollama 明明在跑却
           判"未响应")。故空值一律回落默认地址,不再放空 URL 出门。
        """
        # 收口到 core.ollama_endpoint 唯一属主(本方法保留为薄封装:测试与旧调用点仍引用它)。
        from core.ollama_endpoint import normalize_ollama_url
        return normalize_ollama_url(raw)

    # ollama_url 做成【读时永远归一】的属性:防御性收口——无论 __init__ 之后有没有别的
    # 路径把它置空/塞进无协议头的裸值,每一次 `f"{self.ollama_url}/api/tags"` 取到的都
    # 保证是带协议头的合法 URL,从根上杜绝 "Request URL is missing protocol"。真机哨兵
    # 就是在 _auto_select_backend / _ping_ollama 这两处 `f"{self.ollama_url}/..."` 抓到
    # 空 URL 的(旧代码里 self.ollama_url 被置成了空串),这里让它无从复发。
    @property
    def ollama_url(self) -> str:
        raw = getattr(self, "_ollama_url", "") or ""
        try:
            from core.ollama_endpoint import normalize_ollama_url
            return normalize_ollama_url(raw)
        except Exception:  # noqa: BLE001
            if raw.startswith(("http://", "https://")):
                return raw.rstrip("/")
            return "http://localhost:11434"

    @ollama_url.setter
    def ollama_url(self, value: Optional[str]) -> None:
        self._ollama_url = value or ""

    def __init__(self, backend: str = "auto", ollama_url: Optional[str] = None):
        """
        Args:
            backend: Inference backend ("auto" / "ollama" / "llama_cpp" / "transformers" / "vllm")
            ollama_url: Ollama service URL (only used when backend is "ollama" or "auto")
        """
        self.backend_name = backend
        self._backend = None  # LocalModelBackend instance
        self.ollama_url = self._normalize_ollama_url(
            ollama_url or os.environ.get("OLLAMA_URL", self.OLLAMA_DEFAULT_URL)
        )
        self.available_models: List[str] = []
        # 主脑模型：优先用启动时选定的 OLLAMA_MODEL（见 core.model_selection / Phase 5），
        # 未选时回退 Gemma 4 12B —— 让"第 5 步选的主脑"真正驱动本地大脑加载。
        self.brain_model: str = os.environ.get("OLLAMA_MODEL", "").strip() or "gemma4:12b"
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
            # Check if Ollama is actually running (快速探测)
            try:
                import httpx

                resp = httpx.get(
                    f"{self._hardened_base_url('_auto_select_backend')}/api/tags",
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    logger.info(
                        "自动选择 ollama 后端 (Ollama 正在运行)"
                    )
                    return "ollama"
            except Exception as exc:
                logger.debug("Ollama availability check failed: %s", exc)

            # 快速探测失败 ≠ 没装 Ollama。真机复现:Ollama 首次冷启动、或正在把
            # 大模型(如用户后台 pull 的 12B)载入内存时,/api/tags 可能几秒内不回;
            # 若此时配置的主脑模型是 Ollama 标签(如 "gemma4:latest",带冒号、由
            # ollama pull 管理),绝不能因为探测超时就跌落到 transformers——
            # transformers 会把这个 Ollama 标签当 HuggingFace repo 加载,必然
            # "模型加载失败"。只要 ollama 二进制在,就选 ollama:后续
            # _ensure_ollama_running() 有 ~50s 冷启动等待窗口来正确拉起并就绪。
            if shutil.which("ollama"):
                logger.info(
                    "自动选择 ollama 后端 (Ollama 已安装但快速探测未响应,"
                    "转由冷启动长等待路径处理)"
                )
                return "ollama"

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

    async def _warm_up_ollama_model(self) -> None:
        """把选定的主脑模型【显式加载进 Ollama 内存】(不阻塞启动)。

        真机反馈:serve 起来了、模型也 pull 了,面板却一直「模型未就绪」——因为
        Ollama 是【惰性加载】:serve 启动不预载任何模型,直到第一次推理请求才把权重
        读进内存。所以只 ping 通 serve 不等于「模型可用」。这里在后台发一个最小
        generate 请求(keep_alive=30m 常驻),主动触发加载;加载成功即把状态标为
        真正就绪。纯 CPU 上大模型加载慢,故放后台,完成再更新状态,不卡启动。
        """
        model = (self.brain_model or "").strip()
        if not model:
            return
        try:
            import httpx
            base = (self.ollama_url or "http://localhost:11434").rstrip("/")
            async with httpx.AsyncClient(timeout=600.0) as client:
                # prompt 留空 + keep_alive:Ollama 只加载模型、常驻内存,不真正生成。
                resp = await client.post(
                    f"{base}/api/generate",
                    json={"model": model, "prompt": "", "stream": False, "keep_alive": "30m"},
                )
                if resp.status_code == 200:
                    self._status = LocalBrainStatus.HEALTHY
                    self._healthy = True
                    logger.info("本地主脑模型已加载进内存并常驻 [ollama]: %s", model)
                else:
                    logger.info("主脑模型预载返回 %s(%s);首次对话时会自动加载。",
                                resp.status_code, model)
        except Exception as exc:  # noqa: BLE001
            logger.info("主脑模型后台预载未完成(非致命,首次对话会触发加载): %s", exc)

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
            # 后台显式加载选定模型进内存(Ollama 惰性加载,ping 通≠模型可用)。
            asyncio.create_task(self._warm_up_ollama_model())
            return True

        # 2. Ollama not running, try to start
        self._status = LocalBrainStatus.STARTING
        # 修复:之前这里 shutil.which("ollama") 是否找到命令的结果，只在
        # _start_ollama() 内部用来决定"要不要 Popen 拉起进程"，从来没有被
        # 后续代码读取来区分"命令根本不存在"和"命令存在、服务只是没在
        # 限定时间内响应"这两种完全不同的情况——真机复现过:Phase 0 明确显示
        # "✓ Ollama 已安装"，几分钟后这里却打印"Ollama not found"，纯属误导
        # (真实原因是 Windows 首次冷启动 Ollama 服务较慢——GPU/驱动探测、
        # 杀毒软件扫描 exe 等，原来只给 10 秒重试预算不够)。这里先把
        # "命令是否存在"缓存下来，用来决定后续该走"再等等"还是"真的没装"。
        ollama_cmd_found = shutil.which("ollama") is not None
        logger.info("Ollama 未运行，尝试启动...")

        if await self._start_ollama():
            # 修复:原来只给 10×1 秒(~10s)重试预算，对 Windows 首次冷启动
            # (GPU/驱动探测、杀毒软件扫描 exe)明显偏短，真机复现过刚好在这个
            # 窗口内服务还没绑定好 11434 端口就被判定失败。加长到 30×1 秒并
            # 做简单退避，给服务更充分的启动时间。
            for attempt in range(30):
                await asyncio.sleep(1 if attempt < 10 else 2)
                if await self._ping_ollama():
                    self._status = LocalBrainStatus.HEALTHY
                    self._healthy = True
                    await self._refresh_model_list()
                    logger.info(
                        "本地主脑已启动 [ollama]: %s (模型: %s)",
                        self.ollama_url,
                        self.available_models,
                    )
                    # 后台显式加载模型进内存(serve 刚起,更需要主动预载)。
                    asyncio.create_task(self._warm_up_ollama_model())
                    return True

        # PR-I1: Auto-install Ollama —— 仅当命令确实不存在时才尝试，
        # 修复:之前不管 shutil.which("ollama") 有没有找到命令都无条件走到这里，
        # 对着一台明明已经装了 Ollama、只是服务启动慢的机器打印"not found"
        # 并尝试"自动安装"，白白浪费时间还产生误导性日志。命令已存在时，
        # 真实问题是"服务没起来"，不是"没装"，应该直接进入下面的失败分支，
        # 给出准确、可操作的提示，而不是去下载一个本来就不需要的安装包。
        if not ollama_cmd_found:
            logger.info("未检测到 ollama 命令，尝试自动安装...")
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

        # 3. Start failed —— 区分"确实没装"与"装了但服务没起来"两种措辞，
        # 后者不该再提示"请安装"，而应提示手动启动服务。
        self._status = LocalBrainStatus.UNAVAILABLE
        self._healthy = False
        if ollama_cmd_found:
            logger.warning(
                "Ollama 已安装，但服务在等待窗口内未响应（可能仍在冷启动，或未随系统自启）。"
                "可尝试手动运行: ollama serve，或稍后重启 Galaxy。"
            )
        else:
            logger.warning(
                "Ollama 不可用（未安装）。"
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
                    await client.delete(
                        f"{self._hardened_base_url('_probe_delete')}/api/delete",
                        json={"name": ""}, timeout=5.0,
                    )
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
                    f"{self._hardened_base_url('_delete_model')}/api/delete",
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
            task_type: 任务类型（如 "coding", "fast", "creative", "reasoning", "multimodal"）

        Returns:
            str: 推荐的模型名称
        """
        recommended = self.RECOMMENDED_MODELS.get(task_type, self.RECOMMENDED_MODELS["default"])

        # 如果推荐模型已安装，直接使用
        if recommended in self.available_models:
            return recommended

        # 未安装：按任务类型智能 fallback
        if not self.available_models:
            return recommended  # 无模型时返回推荐值（供下载参考）

        # fast 任务 → 找最小的 gemma 模型（排除多模态模型）
        if task_type == "fast":
            # 优先找 gemma4:e 系列（小模型）
            for candidate in ["gemma4:e2b", "gemma4:e4b"]:
                if candidate in self.available_models:
                    return candidate
            # fallback：找最小的非多模态模型
            non_mm = [m for m in self.available_models
                      if not any(x in m.lower() for x in ["minicpm", "multimodal"])]
            if non_mm:
                return min(non_mm, key=lambda m: self.MODEL_SIZE_ESTIMATE_MB.get(m, float("inf")))
            # 只有多模态模型时，fallback 到默认推荐
            return self.RECOMMENDED_MODELS["default"]

        # multimodal 任务 → 找任何多模态模型
        if task_type == "multimodal":
            for model in self.available_models:
                if any(x in model.lower() for x in ["minicpm", "multimodal"]):
                    return model
            # 无多模态模型时返回推荐值（提示用户下载）
            return recommended

        # coding 任务 → 找代码模型
        if task_type == "coding":
            for model in self.available_models:
                if any(x in model.lower() for x in ["code", "coder"]):
                    return model

        # 其他任务 → 返回已安装的默认推荐或最大模型
        default_rec = self.RECOMMENDED_MODELS["default"]
        if default_rec in self.available_models:
            return default_rec

        # 最终兜底：返回已安装的最大的模型（能力最强）
        return self._largest_available_model()

    def _smallest_available_model(self) -> str:
        """返回已安装的最小模型（VRAM 占用最小）"""
        if not self.available_models:
            return self.brain_model
        return min(
            self.available_models,
            key=lambda m: self.MODEL_SIZE_ESTIMATE_MB.get(m, float("inf"))
        )

    def _largest_available_model(self) -> str:
        """返回已安装的最大模型（VRAM 占用最大，能力最强）"""
        if not self.available_models:
            return self.brain_model
        return max(
            self.available_models,
            key=lambda m: self.MODEL_SIZE_ESTIMATE_MB.get(m, 0)
        )

    # ───────── 内部方法 ─────────

    def _hardened_base_url(self, call_site: str) -> str:
        """调用点级钢板 + 自取证:真机哨兵仍抓到本类发出缺协议头请求(镜像版本
        与主干在兜底层可能不一致/或环境注入怪值),而调用栈照不到 property 内部。
        这里在【消费端】再归一一次;若发现归一前后不一致,把原始值 repr + 环境
        变量 repr 打进日志——下次复现时罪魁真值自己现形,不再靠猜。"""
        raw = ""
        try:
            raw = self.ollama_url  # property(读时归一)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[URL-取证:%s] 读 ollama_url 属性即异常: %r", call_site, exc)
        try:
            from core.ollama_endpoint import normalize_ollama_url
            base = normalize_ollama_url(raw)
        except Exception:  # noqa: BLE001
            base = raw if str(raw).startswith(("http://", "https://")) else "http://localhost:11434"
        if base != raw:
            logger.warning(
                "[URL-取证:%s] ollama_url 读出异常值 raw=%r(归一后=%r);"
                "os.environ['OLLAMA_URL']=%r, _ollama_url=%r —— 请把本行日志发回排查。",
                call_site, raw, base,
                os.environ.get("OLLAMA_URL"), getattr(self, "_ollama_url", None),
            )
        return base

    async def _ping_ollama(self) -> bool:
        """Ping Ollama 服务"""
        try:
            import httpx
            base = self._hardened_base_url("_ping_ollama")
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base}/api/tags")
                return resp.status_code == 200
        except Exception as exc:
            logger.debug("Ollama health check failed: %s", exc)
            return False

    async def _start_ollama(self) -> bool:
        """把 Ollama 作为【常驻服务】拉起(ollama serve 必须一直在,模型才能加载)。

        真机复现的两个坑,这里一并修:
        1) 之前 stdout/stderr=PIPE 且【没有任何人读取】——ollama serve 会持续往
           stderr 写日志,OS 管道缓冲(约 64KB)填满后写操作阻塞,serve 主循环被
           卡住 → 表现为"Ollama 已安装,但服务在等待窗口内未响应"。改为把输出重定向
           到日志文件(logs/ollama.log),彻底避免管道回压。
        2) start_new_session 是 POSIX 专有,Windows 上不生效、进程会绑到当前控制台,
           父进程/控制台一退,serve 跟着被杀,不"常驻"。Windows 改用
           DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP 真正脱离控制台常驻。
        """
        try:
            ollama_cmd = shutil.which("ollama")
            if not ollama_cmd:
                logger.warning("ollama 命令未找到，请安装 Ollama")
                return False

            import os as _os
            from pathlib import Path as _Path
            _log_dir = _Path("logs")
            try:
                _log_dir.mkdir(exist_ok=True)
                _out = open(_log_dir / "ollama.log", "ab")
            except Exception:
                _out = subprocess.DEVNULL  # 连日志都开不了也不能用 PIPE

            _popen_kwargs = dict(stdout=_out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if sys.platform == "win32":
                # 脱离父控制台常驻(避免父进程/终端退出时被连带杀掉)。
                _flags = 0
                _flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                _flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                _popen_kwargs["creationflags"] = _flags
            else:
                _popen_kwargs["start_new_session"] = True

            # 延迟优化默认值(用户显式设过的环境变量绝不覆盖):
            #   KEEP_ALIVE=-1  模型常驻内存不卸载——此前默认几分钟就卸,下次请求
            #                  整个冷加载,正是真机"等待窗口未响应/像在冷启动"的来源;
            #   FLASH_ATTENTION=1 + KV_CACHE_TYPE=q8_0  KV 缓存减半、质量无损
            #                  (收益主要在 GPU,CPU 也无害)。
            _serve_env = {**_os.environ}
            _serve_env.setdefault("OLLAMA_KEEP_ALIVE", "-1")
            _serve_env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
            _serve_env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
            _popen_kwargs["env"] = _serve_env

            subprocess.Popen([ollama_cmd, "serve"], **_popen_kwargs)
            logger.info("Ollama 服务已作为常驻进程启动(日志: logs/ollama.log)")
            return True

        except Exception as e:
            logger.warning(f"启动 Ollama 失败: {e}")
            return False

    async def _auto_install_ollama(self) -> bool:
        """Auto-download and install Ollama

        Supported platforms:
        - Windows: 无法可靠静默安装（见下方说明），直接提示手动安装
        - Linux: curl -fsSL https://ollama.com/install.sh | sh
        - macOS: brew install ollama or download pkg
        """
        import platform
        import subprocess

        system = platform.system()
        logger.info("Auto-installing Ollama for %s...", system)

        try:
            if system == "Windows":
                # 修复:之前这里从 GitHub Releases 下载 "ollama-windows-amd64.exe"，
                # 真机复现直接 404——Ollama 官方 Windows 分发早已经不是这个文件名
                # 的可移植单文件了，而是一个真正的 GUI 安装器(现为 OllamaSetup.exe)，
                # 装完是走系统安装流程(装到 %LOCALAPPDATA%\Programs\Ollama 之类的
                # 位置)，不是"下载一个 exe、直接当命令行工具用 `<exe> serve` 启动"
                # 这种可移植二进制的用法——原实现的假设从一开始就和真实分发方式不
                # 匹配。此沙箱环境无法联网核实当前真实下载直链，与其继续猜一个同样
                # 验证不了、可能一样错的 URL，不如干脆不再尝试这个必然失败的自动
                # 下载,直接给用户一个明确、可操作的提示,省掉这几十秒的无效等待。
                logger.warning(
                    "Windows 上无法可靠自动安装 Ollama（官方分发是图形安装器，"
                    "非可直接调用的独立二进制）。请手动下载安装: "
                    "https://ollama.com/download/windows"
                )
                return False

            elif system == "Linux":
                result = subprocess.run(
                    ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                    capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=300,
                )
                return result.returncode == 0

            elif system == "Darwin":  # macOS
                result = subprocess.run(
                    ["brew", "install", "ollama"],
                    capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
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
                resp = await client.get(f"{self._hardened_base_url('_list_models')}/api/tags")
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
                    f"{self._hardened_base_url('_pull_model')}/api/pull",
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
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10.0
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


# ── 与 model_catalog 收口(尺寸/默认主脑的 SSOT 是目录)────────────────────────────
# 目录内 curated 模型(Gemma 4 系 / MiniCPM-o)的尺寸与"默认主脑"以 core.model_catalog
# 为唯一真相源;此处把它们回填进本类的表,避免两处重复维护(目录赢)。非目录的通用
# 模型(qwen/llama/…)尺寸仍保留本表作 VRAM 评估兜底。catalog 不反向依赖本模块,无环。
try:  # noqa: SIM105
    from core import model_catalog as _mc
    for _spec in _mc.all_models():
        if _spec.size_mb():
            LocalBrainManager.MODEL_SIZE_ESTIMATE_MB[_spec.tag] = _spec.size_mb()
    LocalBrainManager.RECOMMENDED_MODELS["default"] = _mc.default_model()
except Exception:  # noqa: BLE001 — 目录不可用时保留本表原值
    pass
