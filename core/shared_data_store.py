"""
UFO Galaxy - 共享数据持久化存储
================================

将跨设备共享数据（剪贴板、最近传输等）持久化到 JSON 文件。
从 galaxy_gateway.cross_device_coordinator 中提取为独立模块。
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("UFO-Galaxy.SharedData")


class SharedDataStore:
    """跨设备共享数据持久化存储"""

    def __init__(self, path: str = "data/shared_data.json"):
        self._path = path
        self._data: Dict[str, Any] = {}
        self._load()

    @property
    def path(self) -> str:
        return self._path

    @path.setter
    def path(self, value: str):
        self._path = value

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    @data.setter
    def data(self, value: Dict[str, Any]):
        self._data = value

    def set(self, key: str, value: Any):
        """设置共享数据（自动持久化）"""
        self._data[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        self._save()
        logger.info(f"共享数据已设置: {key}")

    def get(self, key: str) -> Optional[Any]:
        """获取共享数据"""
        entry = self._data.get(key)
        if entry:
            return entry.get("value")
        return None

    def _load(self):
        """从文件加载共享数据"""
        try:
            if os.path.exists(self._path):
                with open(self._path, encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception as e:
            logger.warning(f"加载共享数据失败: {e}")

    def _save(self):
        """保存共享数据到文件"""
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存共享数据失败: {e}")
