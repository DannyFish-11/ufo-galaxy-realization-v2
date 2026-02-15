"""
配置热更新管理器 (Config Hot-Reload Manager)
=============================================

在现有 launcher/config_manager.py 基础上，为运行时提供：
- 配置热更新：文件变更自动重载
- 版本控制：记录每次变更的 diff
- Schema 验证：JSON Schema 校验配置合法性
- 变更订阅：配置变更时通知订阅者
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger("UFO-Galaxy.ConfigHotReload")


# ───────────────────── 配置版本记录 ─────────────────────

@dataclass
class ConfigVersion:
    """配置版本快照"""
    version: int
    timestamp: float
    config_hash: str
    changes: Dict[str, Any] = field(default_factory=dict)  # key → {old, new}
    source: str = ""  # 变更来源描述

    def to_dict(self) -> Dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "config_hash": self.config_hash,
            "changes_count": len(self.changes),
            "source": self.source,
        }


class ConfigVersionStore:
    """配置版本存储"""

    def __init__(self, max_versions: int = 100):
        self._versions: deque = deque(maxlen=max_versions)
        self._current_version = 0

    def record(self, config: Dict, changes: Dict, source: str = "") -> ConfigVersion:
        """记录新版本"""
        self._current_version += 1
        ver = ConfigVersion(
            version=self._current_version,
            timestamp=time.time(),
            config_hash=self._hash(config),
            changes=changes,
            source=source,
        )
        self._versions.append(ver)
        return ver

    def get_history(self, limit: int = 20) -> List[Dict]:
        return [v.to_dict() for v in list(self._versions)[-limit:]]

    @property
    def current_version(self) -> int:
        return self._current_version

    @staticmethod
    def _hash(config: Dict) -> str:
        raw = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ───────────────────── 配置验证器 ─────────────────────

class ConfigValidator:
    """
    轻量级配置验证器

    支持注册字段规则：类型、范围、必填、自定义校验函数。
    """

    def __init__(self):
        self._rules: Dict[str, Dict] = {}

    def add_rule(self, key: str, type_: type = None, required: bool = False,
                 min_val: Any = None, max_val: Any = None,
                 choices: List = None, validator: Callable = None):
        """添加字段验证规则"""
        self._rules[key] = {
            "type": type_,
            "required": required,
            "min": min_val,
            "max": max_val,
            "choices": choices,
            "validator": validator,
        }

    def validate(self, config: Dict) -> List[str]:
        """
        验证配置

        Returns: 错误列表（空 = 通过）
        """
        errors = []

        for key, rule in self._rules.items():
            value = self._get_nested(config, key)

            if value is None:
                if rule["required"]:
                    errors.append(f"缺少必填字段: {key}")
                continue

            if rule["type"] and not isinstance(value, rule["type"]):
                errors.append(f"字段 {key} 类型错误: 期望 {rule['type'].__name__}, 实际 {type(value).__name__}")
                continue

            if rule["min"] is not None and value < rule["min"]:
                errors.append(f"字段 {key} 值过小: {value} < {rule['min']}")

            if rule["max"] is not None and value > rule["max"]:
                errors.append(f"字段 {key} 值过大: {value} > {rule['max']}")

            if rule["choices"] and value not in rule["choices"]:
                errors.append(f"字段 {key} 值无效: {value}，可选: {rule['choices']}")

            if rule["validator"]:
                try:
                    result = rule["validator"](value)
                    if result is False:
                        errors.append(f"字段 {key} 自定义验证失败")
                    elif isinstance(result, str):
                        errors.append(f"字段 {key}: {result}")
                except Exception as e:
                    errors.append(f"字段 {key} 验证异常: {e}")

        return errors

    @staticmethod
    def _get_nested(config: Dict, key: str) -> Any:
        """支持 'a.b.c' 格式的嵌套取值"""
        parts = key.split(".")
        current = config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current


# ───────────────────── 热更新配置管理器 ─────────────────────

class HotReloadConfigManager:
    """
    热更新配置管理器

    功能：
    1. 从文件加载配置（JSON）
    2. 定期检测文件变更并自动重载
    3. 验证配置合法性
    4. 记录版本历史
    5. 通知订阅者配置变更
    6. 支持运行时动态修改
    """

    def __init__(self, config_path: Optional[str] = None,
                 check_interval: float = 5.0):
        self._config_path = config_path
        self._check_interval = check_interval
        self._config: Dict[str, Any] = {}
        self._file_mtime: float = 0
        self._file_hash: str = ""

        self._validator = ConfigValidator()
        self._versions = ConfigVersionStore()
        self._subscribers: List[Callable] = []

        self._running = False
        self._watch_task: Optional[asyncio.Task] = None

    # ─── 配置读写 ───

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（支持 dot notation）"""
        parts = key.split(".")
        current = self._config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any, source: str = "api") -> List[str]:
        """
        设置配置值

        Returns: 验证错误列表（空 = 成功）
        """
        # 应用变更到临时副本
        new_config = deepcopy(self._config)
        parts = key.split(".")
        current = new_config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        old_value = current.get(parts[-1])
        current[parts[-1]] = value

        # 验证
        errors = self._validator.validate(new_config)
        if errors:
            return errors

        # 记录变更
        changes = {key: {"old": old_value, "new": value}}
        self._config = new_config
        ver = self._versions.record(self._config, changes, source=source)
        logger.info(f"配置已更新: {key} (v{ver.version}, source={source})")

        # 通知订阅者
        self._notify_subscribers(changes)
        return []

    def get_all(self) -> Dict:
        """获取完整配置（深拷贝）"""
        return deepcopy(self._config)

    # ─── 文件操作 ───

    def load_from_file(self, path: Optional[str] = None) -> List[str]:
        """从文件加载配置"""
        path = path or self._config_path
        if not path or not os.path.exists(path):
            return [f"配置文件不存在: {path}"]

        try:
            with open(path, "r", encoding="utf-8") as f:
                new_config = json.load(f)
        except json.JSONDecodeError as e:
            return [f"JSON 解析失败: {e}"]
        except Exception as e:
            return [f"文件读取失败: {e}"]

        # 验证
        errors = self._validator.validate(new_config)
        if errors:
            return errors

        # 计算差异
        changes = self._diff(self._config, new_config)

        old_config = self._config
        self._config = new_config
        self._config_path = path

        # 更新文件状态
        stat = os.stat(path)
        self._file_mtime = stat.st_mtime
        self._file_hash = ConfigVersionStore._hash(new_config)

        if changes:
            ver = self._versions.record(self._config, changes, source=f"file:{path}")
            logger.info(f"配置已从文件加载: {path} (v{ver.version}, {len(changes)} 项变更)")
            self._notify_subscribers(changes)
        else:
            logger.debug(f"配置文件未变更: {path}")

        return []

    def save_to_file(self, path: Optional[str] = None) -> Optional[str]:
        """保存配置到文件"""
        path = path or self._config_path
        if not path:
            return "未指定配置文件路径"

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {path}")
            return None
        except Exception as e:
            return f"保存失败: {e}"

    # ─── 热更新 ───

    async def start_watching(self):
        """启动文件监控"""
        if not self._config_path:
            logger.warning("未指定配置文件路径，跳过文件监控")
            return

        self._running = True
        self._watch_task = asyncio.create_task(self._watch_loop())
        logger.info(f"配置文件监控已启动: {self._config_path} (间隔 {self._check_interval}s)")

    async def stop_watching(self):
        """停止文件监控"""
        self._running = False
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self):
        """文件变更检测循环"""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                if self._config_path and os.path.exists(self._config_path):
                    stat = os.stat(self._config_path)
                    if stat.st_mtime > self._file_mtime:
                        logger.info(f"检测到配置文件变更: {self._config_path}")
                        errors = self.load_from_file()
                        if errors:
                            logger.warning(f"热更新失败（保留旧配置）: {errors}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"文件监控异常: {e}")

    # ─── 订阅 ───

    def subscribe(self, callback: Callable):
        """订阅配置变更"""
        self._subscribers.append(callback)

    def _notify_subscribers(self, changes: Dict):
        for cb in self._subscribers:
            try:
                cb(changes)
            except Exception as e:
                logger.warning(f"配置变更通知回调异常: {e}")

    # ─── 验证 ───

    @property
    def validator(self) -> ConfigValidator:
        return self._validator

    # ─── 版本 ───

    @property
    def versions(self) -> ConfigVersionStore:
        return self._versions

    # ─── 工具 ───

    @staticmethod
    def _diff(old: Dict, new: Dict, prefix: str = "") -> Dict:
        """计算两个配置的差异"""
        changes = {}
        all_keys = set(list(old.keys()) + list(new.keys()))

        for key in all_keys:
            full_key = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)

            if old_val == new_val:
                continue

            if isinstance(old_val, dict) and isinstance(new_val, dict):
                nested = HotReloadConfigManager._diff(old_val, new_val, full_key)
                changes.update(nested)
            else:
                changes[full_key] = {"old": old_val, "new": new_val}

        return changes

    def get_status(self) -> Dict:
        return {
            "config_path": self._config_path,
            "version": self._versions.current_version,
            "config_keys": len(self._config),
            "watching": self._running,
            "check_interval": self._check_interval,
            "validation_rules": len(self._validator._rules),
        }


# ───────────────────── 单例 ─────────────────────

_instance: Optional[HotReloadConfigManager] = None


def get_config_manager(config_path: Optional[str] = None,
                       **kwargs) -> HotReloadConfigManager:
    global _instance
    if _instance is None:
        _instance = HotReloadConfigManager(config_path=config_path, **kwargs)
    return _instance
