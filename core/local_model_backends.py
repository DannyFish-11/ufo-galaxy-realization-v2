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

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator
import asyncio
import logging
import os
import json
import gc
import shutil

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
        self.base_url = base_url
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
        # Ollama loads on-demand automatically
        self._loaded_models[model_id] = True
        return True

    async def unload_model(self, model_id: str):
        # Ollama keeps models in memory; we can only track our reference
        self._loaded_models.pop(model_id, None)
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

            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
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

        try:
            llm = Llama(
                model_path=model_path,
                n_gpu_layers=self._n_gpu_layers,
                n_ctx=self._n_ctx,
                verbose=False,
            )
            self._models[model_id] = llm
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

        response = tokenizer.decode(
            outputs[0][inputs.input_ids.shape[1] :], skip_special_tokens=True
        )
        return response

    def _build_prompt(self, messages, tokenizer):
        """Convert messages list to prompt string"""
        # Use chat template if the model supports it
        if hasattr(tokenizer, "apply_chat_template"):
            try:
                return tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
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
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        try:
            # Resolve path: local path or HF Hub
            local_path = self._resolve_model_path(model_id)
            load_target = local_path if local_path else model_id

            tokenizer = AutoTokenizer.from_pretrained(
                load_target, trust_remote_code=True
            )
            model_obj = AutoModelForCausalLM.from_pretrained(
                load_target,
                torch_dtype=torch.float16
                if self._device == "cuda"
                else torch.float32,
                device_map="auto" if self._device == "cuda" else None,
                trust_remote_code=True,
            )
            if self._device == "cpu":
                model_obj = model_obj.to("cpu")

            self._pipelines[model_id] = (tokenizer, model_obj)
            logger.info(
                "Transformers loaded: %s on %s", model_id, self._device
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to load transformers %s: %s", model_id, exc
            )
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
                    if any(
                        f in files
                        for f in ["config.json", "model.safetensors", "pytorch_model.bin"]
                    ):
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
            resp = await client.post(
                api_url, headers=headers, json=payload, timeout=120.0
            )
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
        raise ValueError(
            f"Unknown backend: {name}. Available: {available}"
        )
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
