"""core/memory/clap_provider.py — 真·跨模态音频记忆(CLAP 音↔文同空间)。

与 CLIP 同范式：用 CLAP(`transformers` 的 ClapModel/ClapProcessor，
laion/clap-htsat-unfused)把**音频和文本编码进同一向量空间**，于是"用一句话召回
相关声音片段"成为可能——真音频跨模态(不是把音频转成文字 caption)。音频向量持久化
在独立的 Chroma 集合(cosine)。

职责边界：只存**音频**(modality=audio，经 media_path 读取波形)；文本/图像由别的
后端负责。recall(query)：把查询文本 CLAP-编码 → 去音频集合按声学语义召回。

依赖可选：缺 transformers / chromadb / (librosa|soundfile) 时 available()=False，
上层跳过。模型较重(首次下权重)且音频解码需 librosa+ffmpeg；故惰性加载、失败即跳过，
绝不影响主流程。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.CLAP")

_COLLECTION = "galaxy_clap_memory"
_SR = 48000  # CLAP 采样率


class ClapMemoryProvider(MemoryProvider):
    backend_name = "clap"

    def __init__(self) -> None:
        self._model = None
        self._proc = None
        self._col = None
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if self._available is None:
            try:
                import transformers  # noqa: F401
                import chromadb  # noqa: F401
                # 音频解码后端(librosa 或 soundfile)二选一即可
                try:
                    import librosa  # noqa: F401
                except Exception:  # noqa: BLE001
                    import soundfile  # noqa: F401
                self._available = hasattr(__import__("transformers"), "ClapModel")
            except Exception:  # noqa: BLE001
                self._available = False
            if not self._available:
                logger.debug("CLAP backend unavailable (need transformers + chromadb + librosa/soundfile)")
        return self._available

    def _get_model(self):
        if self._model is None:
            from transformers import ClapModel, ClapProcessor
            name = os.getenv("GALAXY_CLAP_MODEL", "laion/clap-htsat-unfused")
            logger.info("Loading CLAP model %s (first run downloads weights)…", name)
            self._model = ClapModel.from_pretrained(name)
            self._proc = ClapProcessor.from_pretrained(name)
        return self._model

    def _get_col(self):
        if self._col is None:
            import chromadb
            persist = os.getenv("GALAXY_CLAP_DIR", "./data/clap_memory")
            try:
                os.makedirs(persist, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            client = chromadb.PersistentClient(path=persist)
            self._col = client.get_or_create_collection(
                _COLLECTION, metadata={"hnsw:space": "cosine"}
            )
        return self._col

    @staticmethod
    def _load_wave(path: str):
        try:
            import librosa
            wav, _ = librosa.load(path, sr=_SR, mono=True)
            return wav
        except Exception:  # noqa: BLE001
            import soundfile as sf
            wav, sr = sf.read(path)
            if getattr(wav, "ndim", 1) > 1:
                wav = wav.mean(axis=1)
            return wav

    def _embed_text(self, text: str):
        import torch
        m = self._get_model()
        inputs = self._proc(text=[text], return_tensors="pt", padding=True)
        with torch.no_grad():
            feats = m.get_text_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats[0].tolist()

    def _embed_audio(self, path: str):
        import torch
        m = self._get_model()
        wav = self._load_wave(path)
        inputs = self._proc(audios=wav, sampling_rate=_SR, return_tensors="pt")
        with torch.no_grad():
            feats = m.get_audio_features(**inputs)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats[0].tolist()

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if modality != "audio" or not self.available():
            return
        md = metadata or {}
        path = md.get("media_path")
        if not path or not os.path.exists(path):
            return
        try:
            vec = self._embed_audio(path)
            doc = content or md.get("caption") or "[audio]"
            store_md = {"modality": "audio"}
            for k, v in md.items():
                if k != "media_path" and isinstance(v, (str, int, float, bool)):
                    store_md[k] = v
            if tags:
                store_md["tags"] = ",".join(tags)
            self._get_col().add(
                ids=[str(md.get("id") or f"aud_{uuid.uuid4().hex[:12]}")],
                embeddings=[vec], documents=[doc], metadatas=[store_md],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("clap remember failed: %s", exc)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        if not query or not self.available():
            return []
        try:
            col = self._get_col()
            if col.count() == 0:
                return []
            qv = self._embed_text(query)
            res = col.query(query_embeddings=[qv], n_results=min(top_k, col.count()))
        except Exception as exc:  # noqa: BLE001
            logger.debug("clap recall failed: %s", exc)
            return []
        hits: List[MemoryHit] = []
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for i, doc in enumerate(docs):
            dist = dists[i] if i < len(dists) else 1.0
            hits.append(MemoryHit(
                content=str(doc), score=round(1.0 - float(dist), 4),
                source=self.backend_name, modality="audio",
                metadata=metas[i] if i < len(metas) else {},
            ))
        return hits
