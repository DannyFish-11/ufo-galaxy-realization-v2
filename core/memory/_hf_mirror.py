"""
core/memory/_hf_mirror.py
=========================
国内可达的 HuggingFace 镜像 / pip 源辅助。

为什么需要它
-----------
记忆/跨模态用到的嵌入模型(paraphrase-multilingual-MiniLM-L12-v2、CLIP、CLAP 等)
首次需要从 HuggingFace 下载。HuggingFace 官方域名在国内常常连不上，导致模型下不动、
记忆语义检索退化到关键词。`huggingface_hub` / `sentence-transformers` 都从
**os.environ["HF_ENDPOINT"]** 读取下载端点，所以只要在 import 这些库之前把它指到国内
镜像(https://hf-mirror.com)，下载就能在国内正常完成。

注意：本仓库运行时 **不会** 把 .env 自动注入 os.environ(unified_config 只读进自己的
dict)，因此这里必须由代码主动 setdefault，而不能只靠 .env。

行为
----
- 默认开启镜像(GALAXY_HF_MIRROR 不显式设为 0/false/no)。
- 已经显式设过 HF_ENDPOINT 的，尊重用户设置、不覆盖(setdefault)。
- 镜像地址可用 GALAXY_HF_ENDPOINT 覆盖,默认 https://hf-mirror.com。
- 设 GALAXY_HF_MIRROR=0 可彻底关闭(回到 HuggingFace 官方域名)。

这个函数是幂等的，可在任意模型加载点调用前安全多次调用。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("Galaxy.Memory.HFMirror")

_DEFAULT_MIRROR = "https://hf-mirror.com"
_applied = False


def ensure_hf_mirror() -> str | None:
    """在加载任何 HF 模型前调用：把 HF_ENDPOINT 指向国内镜像。

    Returns
    -------
    生效的镜像地址(str)，或 None 表示镜像被显式关闭/已被用户接管。
    """
    global _applied

    flag = os.getenv("GALAXY_HF_MIRROR", "1").strip().lower()
    if flag in ("0", "false", "no", "off", ""):
        return None  # 用户显式关闭镜像

    endpoint = os.getenv("GALAXY_HF_ENDPOINT", _DEFAULT_MIRROR).strip() or _DEFAULT_MIRROR

    # 用户已显式设置 HF_ENDPOINT(例如指向自建镜像) → 尊重，不覆盖。
    existing = os.environ.get("HF_ENDPOINT", "").strip()
    if existing:
        if not _applied:
            logger.info("HF_ENDPOINT 已由环境设置: %s(沿用，不覆盖)", existing)
            _applied = True
        return existing

    os.environ["HF_ENDPOINT"] = endpoint
    # huggingface_hub 的部分旧版本读 HF_MIRROR；一并兜底。
    os.environ.setdefault("HF_MIRROR", endpoint)
    if not _applied:
        logger.info("已启用 HuggingFace 国内镜像 HF_ENDPOINT=%s(设 GALAXY_HF_MIRROR=0 关闭)", endpoint)
        _applied = True
    return endpoint
