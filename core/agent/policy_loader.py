"""
core/agent/policy_loader.py
============================
统一策略文件加载器

负责加载 core/agent/policies/ 下的三个策略文件：
  - SOUL.md   — Agent 核心人格（仅在 Agent 执行链路使用）
  - AGENTS.md — Agent 工作规范
  - USER.md   — 用户偏好与交互上下文

公共 API：
    get_soul()   -> str   # 仅供 kernel 在 task_execute / hybrid 执行阶段调用
    get_agents() -> str
    get_user()   -> str
    reload()             # 强制重新从磁盘读取
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Galaxy.Agent.PolicyLoader")

# 策略文件目录（与本模块同级的 policies/ 子目录）
_POLICIES_DIR = Path(__file__).parent / "policies"

# 缓存 TTL（秒）——策略文件不会频繁变更，缓存 60s
_CACHE_TTL = 60.0


class PolicyLoader:
    """线程安全的策略文件加载器（单例）。"""

    _instance: Optional["PolicyLoader"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "PolicyLoader":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (content, loaded_at)
        self._reload_lock = threading.Lock()
        logger.debug("PolicyLoader 已初始化，策略目录: %s", _POLICIES_DIR)

    # ──────────────────────────────────────────────────────────────────
    # 公共 API
    # ──────────────────────────────────────────────────────────────────

    def get_soul(self) -> str:
        """返回 SOUL.md 内容。
        
        ⚠️  此方法 **仅应** 由 kernel 在 intent = task_execute 或 hybrid
            的执行阶段调用，纯聊天路径禁止调用。
        """
        return self._load("SOUL")

    def get_agents(self) -> str:
        """返回 AGENTS.md 内容（Agent 工作规范）。"""
        return self._load("AGENTS")

    def get_user(self) -> str:
        """返回 USER.md 内容（用户偏好）。"""
        return self._load("USER")

    def reload(self) -> None:
        """强制清除缓存并重新从磁盘加载所有策略文件。"""
        with self._reload_lock:
            self._cache.clear()
        logger.info("PolicyLoader: 缓存已清除，下次访问将重新加载。")

    # ──────────────────────────────────────────────────────────────────
    # 内部实现
    # ──────────────────────────────────────────────────────────────────

    def _load(self, name: str) -> str:
        """从缓存或磁盘加载指定策略文件（线程安全）。"""
        now = time.monotonic()
        cached = self._cache.get(name)
        if cached is not None:
            content, loaded_at = cached
            if now - loaded_at < _CACHE_TTL:
                return content

        with self._reload_lock:
            # 双重检查：另一个线程可能刚刚完成加载（重新获取当前时间）
            now = time.monotonic()
            cached = self._cache.get(name)
            if cached is not None:
                content, loaded_at = cached
                if now - loaded_at < _CACHE_TTL:
                    return content

            content = self._read_file(name)
            self._cache[name] = (content, time.monotonic())
            return content

    def _read_file(self, name: str) -> str:
        """从磁盘读取策略文件，文件不存在时返回空字符串并记录警告。"""
        path = _POLICIES_DIR / f"{name}.md"
        if not path.exists():
            logger.warning("策略文件不存在: %s", path)
            return ""
        try:
            content = path.read_text(encoding="utf-8")
            logger.debug("策略文件已加载: %s (%d 字符)", path.name, len(content))
            return content
        except OSError as exc:
            logger.error("策略文件读取失败: %s — %s", path, exc)
            return ""


# ──────────────────────────────────────────────────────────────────────────────
# 模块级单例与便捷函数
# ──────────────────────────────────────────────────────────────────────────────

_loader = PolicyLoader()


def get_soul() -> str:
    """返回 SOUL.md 内容（仅供 Agent 执行链路调用）。"""
    return _loader.get_soul()


def get_agents() -> str:
    """返回 AGENTS.md 内容。"""
    return _loader.get_agents()


def get_user() -> str:
    """返回 USER.md 内容。"""
    return _loader.get_user()


def reload_policies() -> None:
    """强制重新从磁盘加载所有策略文件。"""
    _loader.reload()
