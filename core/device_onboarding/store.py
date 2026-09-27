"""core/device_onboarding/store.py — 候选账本与成员花名册的落盘。

两份都是小 JSON 文件,原子写(``core.atomic_json``)。目录:
``GALAXY_ONBOARDING_STATE_DIR`` → ``GALAXY_DATA_DIR`` → ``./data``。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.Onboarding.Store")

T = TypeVar("T")


def state_dir() -> str:
    explicit = os.getenv("GALAXY_ONBOARDING_STATE_DIR", "").strip()
    if explicit:
        return explicit
    return os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")


class JsonRecordStore(Generic[T]):
    """id → 记录 的持久字典。读失败不等于"没有":记日志,当空处理,但**不覆盖**原文件。"""

    def __init__(
        self,
        filename: str,
        *,
        to_dict: Callable[[T], Dict[str, Any]],
        from_dict: Callable[[Dict[str, Any]], T],
    ) -> None:
        self._filename = filename
        self._to = to_dict
        self._from = from_dict
        self._lock = threading.RLock()
        self._items: Dict[str, T] = {}
        self._loaded_from: Optional[str] = None
        self._read_failed = False

    @property
    def path(self) -> str:
        return os.path.join(state_dir(), self._filename)

    def _ensure(self) -> None:
        path = self.path
        if self._loaded_from == path:
            return
        self._items = {}
        self._read_failed = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k, v in (raw.get("items") or {}).items():
                try:
                    self._items[k] = self._from(v)
                except Exception as exc:  # noqa: BLE001 — 一条坏记录不连坐其余
                    logger.warning("%s 里的记录 %s 读不出来,跳过: %s", self._filename, k, exc)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self._read_failed = True
            logger.warning("%s 读不出来(不等于没有,不会覆盖它): %s", path, exc)
        self._loaded_from = path

    def _save(self) -> None:
        if self._read_failed:
            logger.warning("%s 上次读失败,这次不写,免得把原文件覆盖成空的", self.path)
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        atomic_write_json(
            self.path, {"items": {k: self._to(v) for k, v in self._items.items()}}, ensure_ascii=False, indent=2
        )

    def get(self, key: str) -> Optional[T]:
        with self._lock:
            self._ensure()
            return self._items.get(key)

    def put(self, key: str, item: T) -> None:
        with self._lock:
            self._ensure()
            self._items[key] = item
            self._save()

    def pop(self, key: str) -> Optional[T]:
        with self._lock:
            self._ensure()
            item = self._items.pop(key, None)
            if item is not None:
                self._save()
            return item

    def values(self) -> List[T]:
        with self._lock:
            self._ensure()
            return list(self._items.values())

    def flush(self) -> None:
        with self._lock:
            self._ensure()
            self._save()
