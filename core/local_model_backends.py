"""
core.local_model_backends -- Multi-Backend Local Model Inference
===============================================================

Unified interface supporting multiple local inference backends:
1. OllamaBackend -- via Ollama API (most stable)
2. LlamaCppBackend -- llama-cpp-python direct GGUF loading
3. TransformersBackend -- transformers direct PyTorch/Safetensors loading
4. VLLMBackend -- vLLM high-throughput service (suitable for high concurrency)
5. HFHubBackend -- HuggingFace Hub cloud inference (fallback)

All backends implement the unified LocalModelBackend interface:
- generate(messages, model, **kwargs) -> response
- load_model(model_id) -> bool
- unload_model(model_id)
- health_check() -> bool
- list_models() -> List[str]
"""

import asyncio
import gc
import logging
import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LocalBackends")


# ---------------------------------------------------------------------------
# LocalModelBackend -- Abstract base class for all backends
# ---------------------------------------------------------------------------


class LocalModelBackend(ABC):
    """Local model inference backend base class"""

    name: str = ""  # Backend name
    supports_streaming: bool = False

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Generate a response from the model"""
        pass

    @abstractmethod
    async def load_model(self, model_id: str) -> bool:
        """Load a model into memory"""
        pass

    @abstractmethod
    async def unload_model(self, model_id: str):
        """Unload a model to free VRAM"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the backend is healthy"""
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        """List available/loaded models"""
        pass


# ---------------------------------------------------------------------------
# OllamaBackend -- Via HTTP API
# ---------------------------------------------------------------------------


class OllamaBackend(LocalModelBackend):
    """Ollama backend -- calls via HTTP API"""

    name = "ollama"
    supports_streaming = True

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = self._normalize_url(base_url)
        self._loaded_models: Dict[str, bool] = {}

    @staticmethod
    def _normalize_url(raw: str) -> str:
        """兜底补协议头。真机复现:用户在面板「模型」tab 只填 host:port
        (如 "localhost:11434")、或上游把裸值透传进来,不补协议头的话,值会
        原样带到 httpx,请求时才炸 `Request URL is missing an 'http://'...`
        (克隆界面/onboarding 探测 Ollama 时最常见的那个 HTTP 报错)。这里在
        最内层消费端统一加固,任何 create_backend('ollama') 路径都不再漏。"""
        s = (raw or "").strip()
        if not s:
            return "http://localhost:11434"
        if not s.startswith(("http://", "https://")):
            s = f"http://{s}"
        return s.rstrip("/")

    async def generate(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=2048,
        **kwargs,
    ):
        import httpx

        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    async def load_model(self, model_id: str) -> bool:
        # Ollama loads on-demand automatically —— 但**记账必须过调度器**。
        # 此前 Ollama 是唯一绕开 ComputeScheduler 的后端，于是账本里看不到它占的
        # 显存：gpu_model_count / max_gpu_models / release_if_needed 全部对 Ollama
        # 失明，换档时也无从判断"该先卸谁"。这里补齐咨询-登记两步，让调度器成为
        # **唯一资源真相源**。Ollama 自管层拆分，故这是记账型分配（见 reason）。
        _alloc = None
        try:
            from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

            _alloc = await get_compute_scheduler().schedule_model(
                model_id, self._estimate_size_mb(model_id), preferred_backend="ollama"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ComputeScheduler 不可用，%s 将不进资源账本 —— 显存计数偏少，" "后续分配可能过量承诺。原因：%s",
                model_id,
                exc,
            )
        self._loaded_models[model_id] = True
        if _alloc is not None:
            try:
                from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

                get_compute_scheduler().register_loaded(_alloc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ComputeScheduler.register_loaded 失败：%s 已加载但未登记。原因：%s", model_id, exc)
        return True

    @staticmethod
    def _estimate_size_mb(model_id: str) -> int:
        """Ollama 标签没有本地文件可 stat，尺寸取自模型目录（SSOT）。"""
        try:
            from core.model_catalog import get_model  # noqa: PLC0415

            spec = get_model(model_id)
            if spec is not None:
                size = int(spec.size_mb())
                if size > 0:
                    return size
        except Exception:  # noqa: BLE001
            pass
        return 4000  # 目录里查不到时的保守默认

    async def unload_model(self, model_id: str):
        # Ollama keeps models in memory; we can only track our reference
        self._loaded_models.pop(model_id, None)
        try:
            from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

            get_compute_scheduler().unregister(model_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ComputeScheduler.unregister(%s) 失败(不影响卸载): %s", model_id, exc)
        # Attempt to free via Ollama API
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model_id, "keep_alive": 0},
                    timeout=10.0,
                )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    async def health_check(self) -> bool:
        try:
            import httpx

            # async 方法里同步 httpx.get 会阻塞事件循环(最长 3s)——用 AsyncClient。
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            import httpx

            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LlamaCppBackend -- Direct GGUF loading via llama-cpp-python
# ---------------------------------------------------------------------------


class LlamaCppBackend(LocalModelBackend):
    """llama-cpp-python backend -- direct GGUF loading

    Suitable for GGUF models downloaded from HuggingFace.
    No Ollama required; uses llama_cpp.Llama directly.
    """

    name = "llama_cpp"
    supports_streaming = True

    def __init__(self):
        self._models: Dict[str, Any] = {}  # model_id -> Llama instance
        self._n_gpu_layers = -1  # auto (all layers on GPU)
        self._n_ctx = 4096

    async def generate(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=2048,
        **kwargs,
    ):
        if model not in self._models:
            loaded = await self.load_model(model)
            if not loaded:
                raise RuntimeError(f"Failed to load model: {model}")

        llm = self._models[model]
        response = llm.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response["choices"][0]["message"]["content"]

    @staticmethod
    def _moe_layers_total() -> int:
        """层数口径必须与调度器拆分时用的同源，否则 override 的块索引会错位。"""
        try:
            from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

            return int(get_compute_scheduler().config.default_layer_count)
        except Exception:  # noqa: BLE001
            return 32

    @staticmethod
    def _looks_like_moe(model_id: str, model_path: str) -> bool:
        """是否 MoE 架构。先问模型目录（权威），目录没有再看命名惯例兜底。

        命名惯例：MoE 权重普遍以 ``A<激活参数>`` 或 ``moe`` 标注型号
        （如 ``qwen3-30b-a3b``、``mixtral-8x7b``）。识别错的代价是可控的：
        误判为 MoE 只会让调度器多算一次拆分，拆不动就自然回落常规分支。
        """
        try:
            from core.model_catalog import get_model  # noqa: PLC0415

            spec = get_model(model_id)
            flag = getattr(spec, "is_moe", None) if spec is not None else None
            if flag is not None:
                return bool(flag)
        except Exception:  # noqa: BLE001
            pass
        blob = f"{model_id} {os.path.basename(model_path or '')}".lower()
        if "moe" in blob or "mixtral" in blob:
            return True
        return bool(re.search(r"\d+b[-_]?a\d+b", blob))  # 30b-a3b 这类"总参-激活参"命名

    @staticmethod
    def _apply_moe_offload(llama_kwargs: Dict[str, Any], n_cpu_moe: int, layers_total: int = 32) -> bool:
        """把专家卸载层数翻译成 llama.cpp 入参。返回是否真的生效。

        两条路，按可用性择一（llama-cpp-python 各版本入参不同，用签名探测而不是
        版本号猜）：
        1. ``n_cpu_moe=N`` —— 新版直接暴露，与 CLI ``--n-cpu-moe`` 同义；
        2. ``override_tensor`` 正则 —— 把专家张量 ``blk.<i>.ffn_*_exps.weight``
           钉到 CPU buffer；``n_cpu_moe=-1`` 表示全部层。
        """
        if not n_cpu_moe:
            return False
        try:
            import inspect  # noqa: PLC0415

            import llama_cpp  # noqa: PLC0415

            params = inspect.signature(llama_cpp.Llama.__init__).parameters
        except Exception:  # noqa: BLE001
            return False

        if "n_cpu_moe" in params:
            llama_kwargs["n_cpu_moe"] = n_cpu_moe
            return True
        if "override_tensor" in params:
            llama_kwargs["override_tensor"] = LlamaCppBackend._moe_cpu_override_pattern(n_cpu_moe, layers_total)
            return True
        return False

    @staticmethod
    def _moe_cpu_override_pattern(n_cpu_moe: int, layers_total: int) -> str:
        """生成把专家张量钉到 CPU 的 override-tensor 匹配式。

        llama.cpp 的 ``--override-tensor`` 语法是 ``<张量名正则>=<buffer 类型>``；
        MoE 的专家张量名形如 ``blk.<i>.ffn_(gate|up|down)_exps.weight``。

        ``n_cpu_moe`` 为 -1 或 ≥ 总层数时匹配全部层；否则按**顶部 N 层**逐个
        列举块索引（顶部 = 索引最大的 N 个，与 ``--n-cpu-moe`` 的语义一致）。
        """
        if n_cpu_moe < 0 or n_cpu_moe >= layers_total:
            return r"\.ffn_(gate|up|down)_exps\.weight=CPU"
        first = max(0, layers_total - n_cpu_moe)
        idx = "|".join(str(i) for i in range(first, layers_total))
        return rf"blk\.({idx})\.ffn_(gate|up|down)_exps\.weight=CPU"

    async def load_model(self, model_id: str) -> bool:
        """Load a HF-downloaded GGUF model

        model_id can be:
        - Local path: /path/to/model.q4.gguf
        - HF model_id: automatically looks up the local path in the registry
        """
        from llama_cpp import Llama

        # Resolve model path
        model_path = self._resolve_model_path(model_id)
        if not model_path or not os.path.exists(model_path):
            logger.error("GGUF model not found: %s", model_id)
            return False

        # 加载前问 ComputeScheduler 要分配决策（层卸载/量化/目标设备）。
        # 此前 n_gpu_layers 写死 -1（全部上 GPU）：显存不够时直接 OOM，没有降级。
        # 调度器按实测文件大小与当前 VRAM 余量决定卸多少层；不可用时按原值降级。
        n_gpu_layers = self._n_gpu_layers
        _alloc = None
        try:
            from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

            _size_mb = max(1, int(os.path.getsize(model_path) / (1024 * 1024)))
            _is_moe = self._looks_like_moe(model_id, model_path)
            _alloc = await get_compute_scheduler().schedule_model(
                model_id, _size_mb, preferred_backend="llama_cpp", is_moe=_is_moe
            )
            n_gpu_layers = _alloc.n_gpu_layers
            logger.info(
                "ComputeScheduler allocation: %s → device=%s n_gpu_layers=%s (%s)",
                model_id,
                _alloc.device,
                _alloc.n_gpu_layers,
                _alloc.reason,
            )
        except Exception as exc:
            # 这里的退化必须**响亮**：兜底值就是 self._n_gpu_layers = -1（全部层上 GPU），
            # 而那正是引入调度器要修的那个行为——显存不够直接 OOM、没有降级。
            # 原先记在 debug 级：调度器一旦出问题，系统会悄悄退回它被引入来修的
            # 那个 bug，生产上只看得到一次莫名其妙的 OOM，看不到原因。
            # 说清后果，而不是只说"unavailable"。
            logger.warning(
                "ComputeScheduler 不可用，已退回 n_gpu_layers=%s（%s）—— "
                "层卸载未生效，显存不足时可能直接 OOM。原因：%s",
                n_gpu_layers,
                "全部层上 GPU" if n_gpu_layers == -1 else "静态配置值",
                exc,
            )

        llama_kwargs: Dict[str, Any] = {
            "model_path": model_path,
            "n_gpu_layers": n_gpu_layers,
            "n_ctx": self._n_ctx,
            "verbose": False,
        }
        if _alloc is not None and getattr(_alloc, "is_expert_offloaded", False):
            # MoE 专家卸载:n_gpu_layers 管"注意力/共享层上不上 GPU",这里管
            # "其中哪些层的专家 FFN 留在内存"——两轴正交,缺了这一步分配就白算。
            # 三级降级(新版入参 → 张量正则 override → 都没有则只保留层数),任何
            # 一级不可用都不影响加载,但必须响亮记录"专家卸载没生效"。
            _applied = self._apply_moe_offload(llama_kwargs, _alloc.n_cpu_moe, self._moe_layers_total())
            if not _applied:
                logger.warning(
                    "MoE 专家卸载未生效(llama-cpp-python 既不支持 n_cpu_moe 也不支持 "
                    "override_tensor):%s 将按 n_gpu_layers=%s 加载,显存不足时可能 OOM。",
                    model_id,
                    n_gpu_layers,
                )

        try:
            llm = Llama(**llama_kwargs)
            self._models[model_id] = llm
            if _alloc is not None:
                try:
                    from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

                    get_compute_scheduler().register_loaded(_alloc)
                except Exception as exc:  # noqa: BLE001
                    # 原先是 `except Exception: pass` —— 一个字都不留。
                    # 但这一步不是可有可无的记账：register_loaded 把本次分配写进
                    # ComputeScheduler._models，而 gpu_model_count / max_gpu_models
                    # 这些准入判断都读它。漏记一次，调度器就以为这个模型没加载，
                    # 后续分配会按偏多的余量下判断（过量承诺 GPU），最终触发的正是
                    # 它要防的 OOM —— 而且现场看不到任何线索。
                    logger.warning(
                        "ComputeScheduler.register_loaded 失败：%s 已加载但未登记，"
                        "调度器的显存/模型数账目会偏少，后续分配可能过量承诺。原因：%s",
                        model_id,
                        exc,
                    )
            logger.info("LlamaCpp loaded: %s", model_id)
            return True
        except Exception as exc:
            logger.error("Failed to load %s: %s", model_id, exc)
            return False

    def _resolve_model_path(self, model_id: str) -> Optional[str]:
        """Resolve model path from various sources"""
        # 1. Direct local path
        if os.path.exists(model_id):
            return model_id

        # 2. Look up from HF Model Manager registry
        try:
            from core.huggingface_model_manager import get_hf_model_manager

            mgr = get_hf_model_manager()
            entry = mgr.registry.get(model_id)
            if entry and entry.is_gguf and os.path.exists(entry.local_path):
                return entry.local_path
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # 3. Search in models/ directory
        models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
        if os.path.isdir(models_dir):
            for root, dirs, files in os.walk(models_dir):
                for f in files:
                    if f.endswith(".gguf") and model_id.replace("/", "--") in root:
                        return os.path.join(root, f)

        # 4. Check if model_id is a file name in models/
        for root, dirs, files in os.walk(models_dir):
            for f in files:
                if f.endswith(".gguf") and (model_id in f or f == model_id):
                    return os.path.join(root, f)

        return None

    async def unload_model(self, model_id: str):
        if model_id in self._models:
            del self._models[model_id]
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    async def health_check(self) -> bool:
        return len(self._models) > 0

    def list_models(self) -> List[str]:
        return list(self._models.keys())


# ---------------------------------------------------------------------------
# TransformersBackend -- Direct PyTorch/Safetensors loading
# ---------------------------------------------------------------------------


class TransformersBackend(LocalModelBackend):
    """Transformers backend -- direct PyTorch/Safetensors loading

    Suitable for models requiring full transformers features (e.g., multimodal VLM).
    Needs more VRAM but has the most complete feature set.
    """

    name = "transformers"
    supports_streaming = True

    def __init__(self):
        self._pipelines: Dict[str, Any] = {}
        self._device = "cuda" if self._has_cuda() else "cpu"

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    async def generate(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=2048,
        **kwargs,
    ):
        import torch

        if model not in self._pipelines:
            loaded = await self.load_model(model)
            if not loaded:
                raise RuntimeError(f"Failed to load model: {model}")

        tokenizer, model_obj = self._pipelines[model]

        # Build prompt
        prompt = self._build_prompt(messages, tokenizer)

        inputs = tokenizer(prompt, return_tensors="pt").to(self._device)

        with torch.no_grad():
            outputs = model_obj.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=tokenizer.eos_token_id,
            )

        response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)
        return response

    def _build_prompt(self, messages, tokenizer):
        """Convert messages list to prompt string"""
        # Use chat template if the model supports it
        if hasattr(tokenizer, "apply_chat_template"):
            try:
                return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # Fallback: simple concatenation
        prompt = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt += f"<{role}>{content}</{role}>\n"
        prompt += "<assistant>"
        return prompt

    async def load_model(self, model_id: str) -> bool:
        """Load a HF transformers model"""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        try:
            # Resolve path: local path or HF Hub
            local_path = self._resolve_model_path(model_id)
            load_target = local_path if local_path else model_id

            # Ollama-style tags ("name:tag", e.g. "gemma4:12b") are NOT valid
            # HuggingFace repo ids (the colon is rejected) — they belong to the
            # Ollama backend.  Skip the transformers loader quietly instead of
            # raising a noisy ERROR on every fresh clone without Ollama running.
            if local_path is None and ":" in model_id and "/" not in model_id:
                logger.debug(
                    "Transformers backend skipping Ollama-style id %r "
                    "(not a HF repo id; handled by the Ollama backend)",
                    model_id,
                )
                return False

            # 计算调度:落位(cuda/cpu)听调度器分配,而不是盲选 cuda —— 与 LlamaCpp
            # 同款「咨询-使用-登记-降级」模式;调度器不可用时按原默认行为加载。
            _alloc = None
            _target_device = self._device
            try:
                from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

                _size_mb = 0
                if local_path and os.path.isfile(local_path):
                    _size_mb = os.path.getsize(local_path) // (1024 * 1024)
                elif local_path and os.path.isdir(local_path):
                    _total = 0
                    for _root, _dirs, _files in os.walk(local_path):
                        for _f in _files:
                            try:
                                _total += os.path.getsize(os.path.join(_root, _f))
                            except OSError:
                                pass
                    _size_mb = _total // (1024 * 1024)
                _alloc = await get_compute_scheduler().schedule_model(
                    model_id, _size_mb, preferred_backend="transformers"
                )
                if _alloc is not None and getattr(_alloc, "device", ""):
                    _target_device = "cuda" if str(_alloc.device).startswith("cuda") else "cpu"
            except Exception as _sched_err:  # noqa: BLE001
                logger.debug("compute_scheduler 不可用,按默认设备加载: %s", _sched_err)

            tokenizer = AutoTokenizer.from_pretrained(load_target, trust_remote_code=True)
            model_obj = AutoModelForCausalLM.from_pretrained(
                load_target,
                torch_dtype=torch.float16 if _target_device == "cuda" else torch.float32,
                device_map="auto" if _target_device == "cuda" else None,
                trust_remote_code=True,
            )
            if _target_device == "cpu":
                model_obj = model_obj.to("cpu")

            self._device = _target_device  # generate() 的 inputs.to() 必须与落位一致
            self._pipelines[model_id] = (tokenizer, model_obj)
            if _alloc is not None:
                try:
                    from core.compute_scheduler import get_compute_scheduler  # noqa: PLC0415

                    get_compute_scheduler().register_loaded(_alloc)
                except Exception:  # noqa: BLE001
                    pass
            logger.info("Transformers loaded: %s on %s", model_id, self._device)
            return True
        except Exception as exc:
            logger.error("Failed to load transformers %s: %s", model_id, exc)
            return False

    def _resolve_model_path(self, model_id: str) -> Optional[str]:
        """Resolve local model path if available"""
        # 1. Direct local path
        if os.path.exists(model_id):
            return model_id

        # 2. Look up from HF Model Manager registry
        try:
            from core.huggingface_model_manager import get_hf_model_manager

            mgr = get_hf_model_manager()
            entry = mgr.registry.get(model_id)
            if entry and entry.format.value == "transformers" and os.path.exists(entry.local_path):
                return entry.local_path
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # 3. Search in models/ directory
        models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
        if os.path.isdir(models_dir):
            for root, dirs, files in os.walk(models_dir):
                if model_id.replace("/", "--") in root:
                    # Check if this looks like a transformers model dir
                    if any(f in files for f in ["config.json", "model.safetensors", "pytorch_model.bin"]):
                        return root

        return None

    async def unload_model(self, model_id: str):
        if model_id in self._pipelines:
            del self._pipelines[model_id]
            gc.collect()
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    async def health_check(self) -> bool:
        return len(self._pipelines) > 0

    def list_models(self) -> List[str]:
        return list(self._pipelines.keys())


# ---------------------------------------------------------------------------
# VLLMBackend -- High-throughput service inference
# ---------------------------------------------------------------------------


class VLLMBackend(LocalModelBackend):
    """vLLM backend -- high-throughput service inference

    Suitable for high-concurrency scenarios. After starting, it provides
    an OpenAI-compatible API.
    """

    name = "vllm"
    supports_streaming = True

    def __init__(self, port: int = 8000):
        self.port = port
        self.base_url = f"http://localhost:{port}"
        self._process = None
        self._current_model = None

    async def generate(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=2048,
        **kwargs,
    ):
        import httpx

        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=120.0)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def load_model(self, model_id: str) -> bool:
        """Start vLLM service to load the model"""
        import subprocess

        # Stop current service
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except Exception:
                self._process.kill()

        cmd = [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            model_id,
            "--port",
            str(self.port),
            "--dtype",
            "half",
            "--tensor-parallel-size",
            "1",
        ]
        logger.info("Starting vLLM service: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._current_model = model_id

        # Wait for service to start
        for attempt in range(30):
            await asyncio.sleep(2)
            if await self.health_check():
                logger.info("vLLM service ready on port %d", self.port)
                return True

        logger.error("vLLM service failed to start within timeout")
        return False

    async def unload_model(self, model_id: str):
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except Exception:
                self._process.kill()
            self._process = None
            self._current_model = None

    async def health_check(self) -> bool:
        try:
            import httpx

            resp = httpx.get(f"{self.base_url}/health", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        if self._current_model:
            return [self._current_model]
        return []


# ---------------------------------------------------------------------------
# HFHubBackend -- HuggingFace Hub Cloud Inference (Fallback)
# ---------------------------------------------------------------------------


class HFHubBackend(LocalModelBackend):
    """HuggingFace Hub backend -- cloud inference via Inference API

    Uses HuggingFace's serverless inference API as a fallback when
    no local backend is available.
    """

    name = "hf_hub"
    supports_streaming = False

    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.environ.get("HF_API_TOKEN", "")
        self._loaded_models: Dict[str, bool] = {}

    async def generate(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=2048,
        **kwargs,
    ):
        import httpx

        # Convert messages to a single prompt
        prompt = self._messages_to_prompt(messages)

        api_url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        payload = {
            "inputs": prompt,
            "parameters": {
                "temperature": temperature,
                "max_new_tokens": max_tokens,
                "return_full_text": False,
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(api_url, headers=headers, json=payload, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("generated_text", "")
            return str(data)

    def _messages_to_prompt(self, messages: List[Dict]) -> str:
        """Convert chat messages to a single prompt string"""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        prompt_parts.append("Assistant:")
        return "\n".join(prompt_parts)

    async def load_model(self, model_id: str) -> bool:
        # HF Hub is serverless; no loading needed
        self._loaded_models[model_id] = True
        return True

    async def unload_model(self, model_id: str):
        self._loaded_models.pop(model_id, None)

    async def health_check(self) -> bool:
        return bool(self.api_token)

    def list_models(self) -> List[str]:
        return list(self._loaded_models.keys())


# ---------------------------------------------------------------------------
# Backend Factory
# ---------------------------------------------------------------------------

BACKEND_REGISTRY: Dict[str, type] = {
    "ollama": OllamaBackend,
    "llama_cpp": LlamaCppBackend,
    "transformers": TransformersBackend,
    "vllm": VLLMBackend,
    "hf_hub": HFHubBackend,
}


def create_backend(name: str, **kwargs) -> LocalModelBackend:
    """Create a backend instance

    Args:
        name: Backend name (ollama / llama_cpp / transformers / vllm / hf_hub)
        **kwargs: Backend-specific init arguments

    Returns:
        LocalModelBackend instance

    Raises:
        ValueError: If the backend name is unknown
    """
    backend_cls = BACKEND_REGISTRY.get(name)
    if not backend_cls:
        available = list(BACKEND_REGISTRY.keys())
        raise ValueError(f"Unknown backend: {name}. Available: {available}")
    return backend_cls(**kwargs)


def list_available_backends() -> List[str]:
    """List all backends whose dependencies are installed"""
    available = []
    for name, cls in BACKEND_REGISTRY.items():
        try:
            if name == "ollama":
                import httpx  # noqa: F401
            elif name == "llama_cpp":
                from llama_cpp import Llama  # noqa: F401
            elif name == "transformers":
                from transformers import AutoModelForCausalLM  # noqa: F401
            elif name == "vllm":
                import vllm  # noqa: F401
            elif name == "hf_hub":
                import httpx  # noqa: F401
            available.append(name)
        except ImportError:
            pass
    return available


def detect_best_backend(has_gpu: Optional[bool] = None) -> str:
    """Auto-detect the best available backend based on hardware

    Priority order:
    1. llama_cpp (fastest, direct GGUF, needs GPU for best performance)
    2. ollama (most stable, easiest setup)
    3. transformers (most compatible, needs more VRAM)
    4. hf_hub (cloud fallback, no local compute needed)

    Args:
        has_gpu: Whether GPU is available. Auto-detected if None.

    Returns:
        Best backend name string
    """
    available = list_available_backends()

    if has_gpu is None:
        try:
            import torch

            has_gpu = torch.cuda.is_available()
        except ImportError:
            has_gpu = False

    if has_gpu and "llama_cpp" in available:
        return "llama_cpp"
    if "ollama" in available:
        return "ollama"
    if "transformers" in available:
        return "transformers"
    if "hf_hub" in available:
        return "hf_hub"

    # Ultimate fallback
    return "ollama"


# -- Sentinel --

LOCAL_MODEL_BACKENDS_SENTINEL: str = (
    "LOCAL_MODEL_BACKENDS_V1: core/local_model_backends.py | "
    "Multi-backend local inference: Ollama + llama.cpp + transformers + vLLM + HF Hub. "
    "Unified LocalModelBackend interface. "
    "Auto-detection: GPU -> llama_cpp, no GPU -> ollama."
)
