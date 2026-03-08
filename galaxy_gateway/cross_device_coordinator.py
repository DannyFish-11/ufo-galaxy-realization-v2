"""
Cross-Device Coordinator - 跨设备协同协调器

DEPRECATED: 此模块为向后兼容包装器。新代码请使用 core.unified_coordinator。

所有方法委托到 core.unified_coordinator.UnifiedDeviceCoordinator。
保留原有的公共 API 签名，确保现有消费者零变更：
  - galaxy_gateway.device_router  (惰性导入 execute_cross_device_task)
  - galaxy_gateway.session_roaming (set_shared_data / get_shared_data)
  - tests.test_cross_device_unified (使用 __new__ + _SHARED_DATA_PATH)
"""

import json
import logging
import os
import warnings
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CrossDeviceCoordinator:
    """跨设备协同协调器 — 委托到 core.unified_coordinator

    保留以下属性以兼容现有测试（test_cross_device_unified.py 通过 __new__ 构造）：
      - _SHARED_DATA_PATH
      - shared_clipboard
      - device_states
      - _load_shared_data / _save_shared_data
      - set_shared_data / get_shared_data
    """

    _SHARED_DATA_PATH = os.path.join("data", "shared_data.json")

    def __init__(self):
        self.shared_clipboard: Dict[str, Any] = {}
        self.device_states: Dict[str, Dict] = {}
        self._delegate = None

        # 尝试加载统一协调器
        try:
            from core.unified_coordinator import get_unified_coordinator
            self._delegate = get_unified_coordinator()
            # 同步共享数据引用
            self.shared_clipboard = self._delegate._shared_data.data
        except Exception as e:
            logger.warning(f"统一协调器不可用，使用本地模式: {e}")

        self._load_shared_data()

    # === 主要 API（委托） ===

    async def execute_cross_device_task(self, command: str, context: Dict = None) -> Dict:
        """执行跨设备协同任务"""
        if getattr(self, '_delegate', None):
            return await self._delegate.execute_cross_device_task(command, context)
        return {"success": False, "error": "统一协调器不可用"}

    # === 共享数据（直接实现以支持 __new__ 构造模式） ===

    def set_shared_data(self, key: str, value: Any):
        """设置共享数据（自动持久化）"""
        self.shared_clipboard[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        self._save_shared_data()
        # 同步到统一协调器
        if getattr(self, '_delegate', None):
            self._delegate.set_shared_data(key, value)
        logger.info(f"共享数据已设置: {key}")

    def get_shared_data(self, key: str) -> Optional[Any]:
        """获取共享数据"""
        data = self.shared_clipboard.get(key)
        if data:
            return data.get("value")
        return None

    def update_device_state(self, device_id: str, state: Dict):
        """更新设备状态"""
        self.device_states[device_id] = {
            **state,
            "updated_at": datetime.now().isoformat()
        }
        if getattr(self, '_delegate', None):
            self._delegate.update_device_state(device_id, state)

    def get_device_state(self, device_id: str) -> Optional[Dict]:
        """获取设备状态"""
        return self.device_states.get(device_id)

    # === 持久化（直接实现以支持 __new__ 构造模式） ===

    def _load_shared_data(self):
        """从文件加载共享数据"""
        try:
            if os.path.exists(self._SHARED_DATA_PATH):
                with open(self._SHARED_DATA_PATH, encoding="utf-8") as f:
                    self.shared_clipboard = json.load(f)
        except Exception as e:
            logger.warning(f"加载共享数据失败: {e}")

    def _save_shared_data(self):
        """保存共享数据到文件"""
        try:
            os.makedirs(os.path.dirname(self._SHARED_DATA_PATH) or ".", exist_ok=True)
            with open(self._SHARED_DATA_PATH, "w", encoding="utf-8") as f:
                json.dump(self.shared_clipboard, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存共享数据失败: {e}")


# 全局跨设备协调器实例
cross_device_coordinator = CrossDeviceCoordinator()
