"""进程自己往 ``os.environ`` 里写的值 —— 不是人配的，「保存设置」不把它们钉进 ``.env``。

「保存设置」把登记表里每个键的 ``os.environ`` 现值整份写进 ``.env``（``core/routes/config.py::_write_env_file_with``）。
可有一批键是进程**这一次运行**自己推出来、写进环境变量供别处读的：``--backend`` / ``-v`` / ``--model`` 落的值、内置
NATS 起在哪、本机推理服务的地址、B 档原生在不在线、按硬件临时降的档。被写进 ``.env`` 之后，下次启动它们就成了
「人配过」。真跑里一次保存就钉进了 ``GALAXY_SKIP_ELECTRON=1``（之后正常启动也不开桌面窗口）和
``GALAXY_NATS_URL``（非空就算要用总线，本地模式也起 NATS）。降档的注释写着「只影响本进程」，钉进去就成了永久降档。

经 :func:`export` 写的值记下来，连同进程替它写之前人配的那个。保存时现值仍是进程写的，就换回人配的（没配过就不写）。
人后来在面板上明确改了的，照旧按人改的写。
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

_lock = threading.Lock()
_ORIGINAL: Dict[str, Optional[str]] = {}  # 进程第一次替它写之前环境里的值（None = 没配）
_EXPORTED: Dict[str, str] = {}  # 进程最后一次写的值


def export(key: str, value: str, *, keep_existing: bool = False) -> None:
    """把进程这一次推出来的值写进 ``os.environ``，并记下它不是人配的。

    ``keep_existing``：环境里已经有值（人配的）就不动 —— ``os.environ.setdefault`` 的语义。
    人配的恰好就是这个值时，也不记成进程写的。
    """
    with _lock:
        current = os.environ.get(key)
        if keep_existing and current:
            return
        if current == value and key not in _EXPORTED:
            return
        _ORIGINAL.setdefault(key, current)
        os.environ[key] = value
        _EXPORTED[key] = value


def value_to_save(key: str, current: str) -> str:
    """「保存设置」时这个键该落盘的值：现值仍是进程自己写的那个，就换回人配的（没配过给空串 = 不写）。"""
    with _lock:
        if key in _EXPORTED and current == _EXPORTED[key]:
            return _ORIGINAL.get(key) or ""
        return current


__all__ = ["export", "value_to_save"]
