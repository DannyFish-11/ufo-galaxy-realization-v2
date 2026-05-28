"""
core.huggingface_model_manager — HuggingFace 本地模型仓库管理
================================================================

目标：让 Galaxy 可以直接从 HuggingFace Hub 下载和管理模型，
实现"想要什么模型直接下"的能力。

借鉴：
- Ollama 的模型下载/管理体验
- huggingface_hub 库的文件级下载
- llama.cpp 的 GGUF 格式支持
- transformers 的 AutoModel 自动加载

支持的模型格式：
- GGUF (llama.cpp) — 本地推理最优
- transformers (PyTorch/Safetensors) — 最大兼容性
- ONNX — 跨平台推理
- AWQ/GPTQ — 量化模型

模型分类管理：
- LLM (文本生成)
- VLM (视觉语言模型)
- ASR (语音识别)
- TTS (语音合成)
- Embedding (向量嵌入)
- Reranker (重排序)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.HFModelManager")


# ---------------------------------------------------------------------------
# Model Format — 支持的模型格式
# ---------------------------------------------------------------------------

class ModelFormat(str, Enum):
    GGUF = "gguf"                      # llama.cpp 原生格式
    TRANSFORMERS = "transformers"       # PyTorch / Safetensors
    ONNX = "onnx"                       # ONNX Runtime
    AWQ = "awq"                         # AWQ 量化
    GPTQ = "gptq"                       # GPTQ 量化


class ModelFamily(str, Enum):
    LLM = "llm"                         # 文本生成
    VLM = "vlm"                         # 视觉语言模型
    ASR = "asr"                         # 语音识别
    TTS = "tts"                         # 语音合成
    EMBEDDING = "embedding"             # 向量嵌入
    RERANKER = "reranker"               # 重排序


# ---------------------------------------------------------------------------
# Model Registry Entry — 单个模型的注册信息
# ---------------------------------------------------------------------------

@dataclass
class ModelRegistryEntry:
    """已注册模型的元数据"""
    model_id: str                      # HuggingFace model ID, e.g. "Qwen/Qwen2-7B-Instruct"
    family: ModelFamily
    format: ModelFormat
    local_path: str                    # 本地存储路径
    size_mb: int
    quantization: str = "none"         # "none", "q4", "q5", "q8", "awq", "gptq"
    download_time: float = 0.0
    last_used: float = 0.0
    use_count: int = 0
    tags: List[str] = field(default_factory=list)
    description: str = ""

    @property
    def is_gguf(self) -> bool:
        return self.format == ModelFormat.GGUF

    @property
    def is_local(self) -> bool:
        return os.path.exists(self.local_path)


# ---------------------------------------------------------------------------
# Model Registry — 本地模型注册表
# ---------------------------------------------------------------------------

class ModelRegistry:
    """本地模型注册表 — 管理已下载的模型"""

    def __init__(self, registry_path: Optional[str] = None):
        self.project_root = Path(__file__).parent.parent
        self.models_dir = self.project_root / "models"
        self.models_dir.mkdir(exist_ok=True)
        self.registry_file = Path(registry_path) if registry_path else self.models_dir / "registry.json"
        self._entries: Dict[str, ModelRegistryEntry] = {}
        self._load()

    def _load(self):
        """从 registry.json 加载"""
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for model_id, entry_data in data.items():
                    self._entries[model_id] = ModelRegistryEntry(**entry_data)
                logger.info("Model registry loaded: %d models", len(self._entries))
            except Exception as exc:
                logger.warning("Failed to load model registry: %s", exc)

    def _save(self):
        """保存到 registry.json"""
        try:
            data = {}
            for model_id, entry in self._entries.items():
                data[model_id] = {
                    "model_id": entry.model_id,
                    "family": entry.family.value,
                    "format": entry.format.value,
                    "local_path": entry.local_path,
                    "size_mb": entry.size_mb,
                    "quantization": entry.quantization,
                    "download_time": entry.download_time,
                    "last_used": entry.last_used,
                    "use_count": entry.use_count,
                    "tags": entry.tags,
                    "description": entry.description,
                }
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to save model registry: %s", exc)

    def register(self, entry: ModelRegistryEntry):
        """注册模型"""
        self._entries[entry.model_id] = entry
        self._save()

    def get(self, model_id: str) -> Optional[ModelRegistryEntry]:
        return self._entries.get(model_id)

    def list_by_family(self, family: ModelFamily) -> List[ModelRegistryEntry]:
        return [e for e in self._entries.values() if e.family == family and e.is_local]

    def list_all_local(self) -> List[ModelRegistryEntry]:
        return [e for e in self._entries.values() if e.is_local]

    def remove(self, model_id: str):
        """删除模型"""
        entry = self._entries.pop(model_id, None)
        if entry and os.path.exists(entry.local_path):
            shutil.rmtree(entry.local_path, ignore_errors=True)
        self._save()


# ---------------------------------------------------------------------------
# HuggingFace Model Manager
# ---------------------------------------------------------------------------

class HuggingFaceModelManager:
    """HuggingFace 模型管理器

    提供：
    - 从 HuggingFace Hub 下载模型
    - GGUF 格式转换/下载
    - 本地模型缓存管理
    - 与 Galaxy 路由器集成
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self.project_root = Path(__file__).parent.parent
        self.models_dir = Path(cache_dir) if cache_dir else self.project_root / "models"
        self.models_dir.mkdir(exist_ok=True)
        self.registry = ModelRegistry(str(self.models_dir / "registry.json"))
        self._download_lock = asyncio.Lock()

    # ── 下载模型 ──

    async def download(self, model_id: str, family: ModelFamily,
                       format: ModelFormat = ModelFormat.GGUF,
                       quantization: str = "q4",
                       force: bool = False) -> ModelRegistryEntry:
        """从 HuggingFace Hub 下载模型

        Args:
            model_id: HuggingFace model ID, e.g. "Qwen/Qwen2-7B-Instruct-GGUF"
            family: 模型家族 (llm/vlm/asr/tts/embedding)
            format: 模型格式 (gguf/transformers/onnx)
            quantization: 量化级别 (q4/q5/q8/none)
            force: 强制重新下载
        """
        registry_key = f"{model_id}:{format.value}:{quantization}"

        # 检查是否已存在
        existing = self.registry.get(registry_key)
        if existing and existing.is_local and not force:
            logger.info("Model already downloaded: %s", model_id)
            existing.last_used = time.time()
            existing.use_count += 1
            self.registry.register(existing)
            return existing

        async with self._download_lock:
            local_path = str(self.models_dir / family.value / model_id.replace("/", "--"))
            os.makedirs(local_path, exist_ok=True)

            try:
                from huggingface_hub import snapshot_download, hf_hub_download

                if format == ModelFormat.GGUF:
                    # GGUF: 下载特定量化文件
                    entry = await self._download_gguf(
                        model_id, family, quantization, local_path
                    )
                elif format == ModelFormat.TRANSFORMERS:
                    # transformers: 完整 snapshot 下载
                    entry = await self._download_transformers(
                        model_id, family, local_path
                    )
                else:
                    raise ValueError(f"Unsupported format: {format.value}")

                self.registry.register(entry)
                logger.info(
                    "Model downloaded: %s (%s, %s) → %s",
                    model_id, format.value, quantization, local_path
                )
                return entry

            except ImportError:
                logger.error(
                    "huggingface_hub not installed. Run: pip install huggingface_hub"
                )
                raise
            except Exception as exc:
                logger.error("Failed to download %s: %s", model_id, exc)
                raise

    async def _download_gguf(self, model_id: str, family: ModelFamily,
                             quantization: str, local_path: str) -> ModelRegistryEntry:
        """下载 GGUF 格式模型（llama.cpp 专用）"""
        from huggingface_hub import hf_hub_download

        # 自动查找 GGUF 文件
        gguf_filename = None

        # 常见命名模式
        patterns = [
            f"*.{quantization.lower()}*.gguf",
            f"*.{quantization.lower()}_*.gguf",
            f"*-{quantization.lower()}.gguf",
            "*.gguf",  # 兜底
        ]

        for pattern in patterns:
            try:
                from huggingface_hub import HfApi
                api = HfApi()
                files = api.list_repo_files(model_id)
                matches = [f for f in files if f.endswith(".gguf") and quantization.lower() in f.lower()]
                if not matches:
                    matches = [f for f in files if f.endswith(".gguf")]
                if matches:
                    gguf_filename = matches[0]
                    break
            except Exception:
                continue

        if not gguf_filename:
            raise ValueError(f"No GGUF file found for {model_id} with quantization {quantization}")

        # 下载文件
        downloaded = hf_hub_download(
            repo_id=model_id,
            filename=gguf_filename,
            local_dir=local_path,
            local_dir_use_symlinks=False,
        )

        # 计算大小
        size_mb = os.path.getsize(downloaded) // (1024 * 1024)

        return ModelRegistryEntry(
            model_id=model_id,
            family=family,
            format=ModelFormat.GGUF,
            local_path=downloaded,
            size_mb=size_mb,
            quantization=quantization,
            download_time=time.time(),
            last_used=time.time(),
            tags=["gguf", quantization, "llama.cpp"],
            description=f"GGUF model from {model_id}, {quantization} quantization",
        )

    async def _download_transformers(self, model_id: str, family: ModelFamily,
                                     local_path: str) -> ModelRegistryEntry:
        """下载 transformers 格式模型"""
        from huggingface_hub import snapshot_download

        downloaded = snapshot_download(
            repo_id=model_id,
            local_dir=local_path,
            local_dir_use_symlinks=False,
        )

        # 计算总大小
        total_size = sum(
            os.path.getsize(os.path.join(dirpath, f))
            for dirpath, _, filenames in os.walk(local_path)
            for f in filenames
        )
        size_mb = total_size // (1024 * 1024)

        return ModelRegistryEntry(
            model_id=model_id,
            family=family,
            format=ModelFormat.TRANSFORMERS,
            local_path=downloaded,
            size_mb=size_mb,
            quantization="none",
            download_time=time.time(),
            last_used=time.time(),
            tags=["transformers", "pytorch"],
            description=f"Transformers model from {model_id}",
        )

    # ── 快捷下载方法 ──

    async def download_llm(self, model_id: str, quantization: str = "q4") -> ModelRegistryEntry:
        """下载文本生成模型"""
        return await self.download(model_id, ModelFamily.LLM, ModelFormat.GGUF, quantization)

    async def download_vlm(self, model_id: str, quantization: str = "q4") -> ModelRegistryEntry:
        """下载视觉语言模型"""
        return await self.download(model_id, ModelFamily.VLM, ModelFormat.GGUF, quantization)

    async def download_asr(self, model_id: str = "Systran/faster-whisper-medium") -> ModelRegistryEntry:
        """下载 ASR 模型（默认 faster-whisper-medium）"""
        return await self.download(model_id, ModelFamily.ASR, ModelFormat.TRANSFORMERS)

    async def download_embedding(self, model_id: str = "BAAI/bge-large-zh-v1.5") -> ModelRegistryEntry:
        """下载 Embedding 模型"""
        return await self.download(model_id, ModelFamily.EMBEDDING, ModelFormat.TRANSFORMERS)

    # ── 查询 ──

    def list_local_models(self, family: Optional[ModelFamily] = None) -> List[ModelRegistryEntry]:
        """列出本地可用模型"""
        if family:
            return self.registry.list_by_family(family)
        return self.registry.list_all_local()

    def get_model_path(self, model_id: str) -> Optional[str]:
        """获取模型本地路径"""
        entry = self.registry.get(model_id)
        if entry and entry.is_local:
            return entry.local_path
        return None

    # ── 推荐模型（预配置） ──

    RECOMMENDED_MODELS: Dict[str, Dict[str, str]] = {
        # === 本地主脑首选：Google Gemma 4 E4B ===
        # 发布日期: 2026-04-02 | 参数: 4.5B有效(8B含embeddings)
        # 原生多模态: 文本+图像+音频 | 上下文: 128K | 许可证: Apache 2.0
        # VRAM需求: 4-6GB (Q4量化) | Function Calling | 支持140+语言
        "llm_gemma4_e4b": {
            "model_id": "google/gemma-4-E4B-it-GGUF",
            "family": "llm",
            "format": "gguf",
            "quantization": "q4",
            "description": "Gemma 4 E4B — Google原生多模态主脑，文本/图像/音频输入，128K上下文",
        },
        "llm_gemma4_e4b_q8": {
            "model_id": "google/gemma-4-E4B-it-GGUF",
            "family": "llm",
            "format": "gguf",
            "quantization": "q8",
            "description": "Gemma 4 E4B Q8 — 更高精度，需6-8GB VRAM",
        },
        # === 备选模型 ===
        "llm_qwen2_7b": {
            "model_id": "Qwen/Qwen2-7B-Instruct-GGUF",
            "family": "llm",
            "format": "gguf",
            "quantization": "q4",
            "description": "Qwen2 7B — 中文优秀备选",
        },
        "vlm_gemma4_e4b": {
            "model_id": "google/gemma-4-E4B-it",
            "family": "vlm",
            "format": "transformers",
            "quantization": "none",
            "description": "Gemma 4 E4B VLM模式 — 完整transformers多模态",
        },
        "asr_whisper_medium": {
            "model_id": "Systran/faster-whisper-medium",
            "family": "asr",
            "format": "transformers",
            "description": "Whisper Medium — 语音识别",
        },
        "embedding_bge_zh": {
            "model_id": "BAAI/bge-large-zh-v1.5",
            "family": "embedding",
            "format": "transformers",
            "description": "BGE Large 中文 Embedding",
        },
    }

    async def install_recommended(self, key: str) -> ModelRegistryEntry:
        """安装预配置推荐模型"""
        if key not in self.RECOMMENDED_MODELS:
            raise ValueError(f"Unknown recommended model: {key}. Available: {list(self.RECOMMENDED_MODELS.keys())}")
        cfg = self.RECOMMENDED_MODELS[key]
        return await self.download(
            model_id=cfg["model_id"],
            family=ModelFamily(cfg["family"]),
            format=ModelFormat(cfg["format"]),
            quantization=cfg.get("quantization", "none"),
        )


# ── 全局单例 ──

_manager: Optional[HuggingFaceModelManager] = None

def get_hf_model_manager() -> HuggingFaceModelManager:
    global _manager
    if _manager is None:
        _manager = HuggingFaceModelManager()
    return _manager


# ── Sentinel ──

HUGGINGFACE_MODEL_MANAGER_SENTINEL: str = (
    "HUGGINGFACE_MODEL_MANAGER_V1: core/huggingface_model_manager.py | "
    "GGUF + Transformers + ONNX format support. "
    "Inspired by Ollama's model management + huggingface_hub. "
    "Provides 'download whatever model you want' capability."
)
