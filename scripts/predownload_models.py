#!/usr/bin/env python3
"""
scripts/predownload_models.py
=============================
克隆/安装阶段预下载模型 —— 把记忆/跨模态用到的 HuggingFace 嵌入模型在安装时就拉到本地
缓存(~/.cache/huggingface)，这样首次运行不必等下载、断网也能用真语义检索。

设计原则
--------
1. **国内可达**：下载前先把 HF_ENDPOINT 指向镜像(默认 https://hf-mirror.com)，
   走 core.memory._hf_mirror.ensure_hf_mirror()。可用 GALAXY_HF_MIRROR=0 关闭。
2. **优雅**：任何模型下载失败(无网络/依赖缺失)都只 WARN，**绝不让安装中断**
   (退出码恒为 0)；运行时仍可懒加载或回退。
3. **按需**：只下当前配置真正会用到的模型——
     - 文本嵌入：GALAXY_EMBED_MODEL(默认 paraphrase-multilingual-MiniLM-L12-v2)
     - 跨模态(若该 provider 存在且 GALAXY_MEMORY_MEDIA 开)：CLIP / CLAP

用法
----
    python scripts/predownload_models.py            # 跟随 .env / 默认值
    GALAXY_EMBED_MODEL="" python scripts/...         # 跳过多语言、用 chroma 默认
    GALAXY_HF_MIRROR=0 python scripts/...            # 用 HuggingFace 官方域名
"""

from __future__ import annotations

import os
import sys

# 让 `python scripts/predownload_models.py` 能 import core.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _log(level: str, msg: str) -> None:
    colors = {"INFO": "\033[0;34m", "OK": "\033[0;32m", "WARN": "\033[1;33m", "ERR": "\033[0;31m"}
    nc = "\033[0m"
    print(f"{colors.get(level, '')}[{level}]{nc} {msg}", flush=True)


def _apply_mirror() -> None:
    try:
        from core.memory._hf_mirror import ensure_hf_mirror

        ep = ensure_hf_mirror()
        if ep:
            _log("INFO", f"HuggingFace 端点: {ep}")
        else:
            _log("INFO", "HF 镜像已关闭(GALAXY_HF_MIRROR=0)，使用官方域名")
    except Exception as exc:  # pragma: no cover - 极端环境
        _log("WARN", f"镜像设置跳过: {exc}")


def _predownload_embed() -> bool:
    """预下载文本嵌入模型(sentence-transformers)。返回是否成功。"""
    model = os.getenv("GALAXY_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2").strip()
    if not model or model.lower() in ("default", "all-minilm-l6-v2"):
        _log("INFO", "GALAXY_EMBED_MODEL 为默认/空，跳过多语言嵌入器预下载(将用 chroma 内置 all-MiniLM)")
        return True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:
        _log("WARN", f"sentence-transformers 未安装({exc})，跳过嵌入器预下载；运行时缺则自动回退关键词后端")
        return False
    try:
        _log("INFO", f"预下载文本嵌入模型: {model}(首次约 ~470MB)…")
        SentenceTransformer(model)  # 触发下载并落到 HF 缓存
        _log("OK", f"嵌入模型已就绪: {model}")
        return True
    except Exception as exc:
        _log("WARN", f"嵌入模型 {model} 下载失败({exc})；运行时会自动回退 chroma 默认 all-MiniLM，不影响启动")
        return False


def _predownload_crossmodal() -> None:
    """若跨模态 provider 存在且启用，预下载 CLIP/CLAP。全程 best-effort。"""
    if os.getenv("GALAXY_MEMORY_MEDIA", "0").strip().lower() in ("0", "false", "no", ""):
        return  # 跨模态记忆未开，无需预下载
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # CLIP(图像↔文本)
    if os.path.exists(os.path.join(here, "core", "memory", "clip_provider.py")):
        model = os.getenv("GALAXY_CLIP_MODEL", "clip-ViT-B-32").strip()
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            _log("INFO", f"预下载 CLIP 模型: {model}…")
            SentenceTransformer(model)
            _log("OK", f"CLIP 模型已就绪: {model}")
        except Exception as exc:
            _log("WARN", f"CLIP 模型下载失败({exc})；运行时懒加载，跨模态图像检索缺失时降级")
    # CLAP(音频↔文本)
    if os.path.exists(os.path.join(here, "core", "memory", "clap_provider.py")):
        model = os.getenv("GALAXY_CLAP_MODEL", "laion/clap-htsat-unfused").strip()
        try:
            from transformers import ClapModel, ClapProcessor  # type: ignore

            _log("INFO", f"预下载 CLAP 模型: {model}…")
            ClapModel.from_pretrained(model)
            ClapProcessor.from_pretrained(model)
            _log("OK", f"CLAP 模型已就绪: {model}")
        except Exception as exc:
            _log("WARN", f"CLAP 模型下载失败({exc})；运行时懒加载，跨模态音频检索缺失时降级")


def main() -> int:
    _log("INFO", "模型预下载开始(失败只告警，不会中断安装)")
    _apply_mirror()
    _predownload_embed()
    _predownload_crossmodal()
    _log("OK", "模型预下载阶段结束")
    return 0  # 永远成功 —— 安装不应因模型下载失败而中断


if __name__ == "__main__":
    sys.exit(main())
