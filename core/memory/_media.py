"""core/memory/_media.py — base64 媒体 → 临时文件桥。

Omni-SimpleMem 的 add_image/add_audio/add_video 接收**文件路径**，而本系统的
摄像头/麦克风是 base64 内存数据。本模块把 base64 落成临时文件供其摄入，调用方
摄入完即删除（OSM 在 add_* 调用内同步读取文件，返回后即可安全删除）。
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger("Galaxy.Memory.Media")

_EXT_BY_MIME = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif",
    "audio/webm": ".webm", "audio/wav": ".wav", "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg", "audio/m4a": ".m4a",
    "video/mp4": ".mp4", "video/webm": ".webm",
}
_EXT_BY_MODALITY = {"image": ".jpg", "audio": ".webm", "video": ".mp4"}


def _ext_for(mime: str, modality: str) -> str:
    if mime and mime.lower() in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime.lower()]
    return _EXT_BY_MODALITY.get(modality, ".bin")


def write_temp_media(data_b64: str, mime: str = "", modality: str = "image") -> Optional[str]:
    """把 base64 媒体写入临时文件，返回路径；失败返回 None。"""
    if not data_b64:
        return None
    try:
        raw = base64.b64decode(data_b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("media base64 decode failed: %s", exc)
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=_ext_for(mime, modality), prefix="galaxy_mem_")
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        return path
    except Exception as exc:  # noqa: BLE001
        logger.debug("media temp write failed: %s", exc)
        return None


def remove_temp(path: Optional[str]) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
