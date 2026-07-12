"""core/fast_loop.py — 高性能事件循环接入(Linux/macOS: uvloop, Windows: winloop)
==================================================================================

Windows 默认的 Proactor 循环开销大(真机:面板首开的并发请求把循环拖出 10s 级
整体冻结)。winloop(uvloop 的 Windows 移植,libuv 底座)对默认循环有约 5 倍的
吞吐提升;Linux/macOS 用 uvloop。

**安全设计(务必满足):**

- **进程入口调用**:必须在任何事件循环创建之前调用 :func:`install_fast_loop`
  (main.py / unified_launcher 的最顶部),循环一旦跑起来就不能换策略。
- **子进程探针**:TTS 播放(PowerShell/mpg123)、SAPI 合成、节点拉起全都依赖
  ``asyncio.create_subprocess_exec``。装上新策略后先在一次性循环里真实拉一个
  子进程验证;失败立即还原默认策略——**宁可慢,不能哑**。
- **可关**:``GALAXY_FAST_LOOP=0`` 直接跳过。缺包/任何异常都静默退回默认。
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

logger = logging.getLogger("Galaxy.FastLoop")

_installed_name = "default"


def active_loop_name() -> str:
    """当前生效的循环实现名("winloop"/"uvloop"/"default"),供自检展示。"""
    return _installed_name


def _probe_subprocess_support() -> bool:
    """在新策略下真实拉一个子进程验证支持(约几十毫秒,一次性循环)。"""
    async def _probe() -> bool:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "pass",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return (await proc.wait()) == 0

    try:
        return bool(asyncio.run(_probe()))
    except Exception as exc:  # noqa: BLE001
        logger.info("子进程探针失败: %s", exc)
        return False


def install_fast_loop() -> str:
    """尽量换上高性能事件循环。返回生效名;任何失败都安全退回默认策略。"""
    global _installed_name
    if os.environ.get("GALAXY_FAST_LOOP", "1").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return _installed_name
    original_policy = asyncio.get_event_loop_policy()
    try:
        if sys.platform == "win32":
            import winloop  # type: ignore
            winloop.install()
            name = "winloop"
        else:
            import uvloop  # type: ignore
            uvloop.install()
            name = "uvloop"
    except Exception as exc:  # noqa: BLE001
        logger.info("高性能事件循环不可用(用默认): %s", exc)
        return _installed_name

    # 子进程探针:语音播放/SAPI 合成/节点拉起都靠 asyncio 子进程。
    if not _probe_subprocess_support():
        asyncio.set_event_loop_policy(original_policy)
        logger.warning(
            "%s 子进程探针未通过,还原默认事件循环(宁慢勿哑)", name,
        )
        return _installed_name

    _installed_name = name
    logger.info("高性能事件循环已启用: %s", name)
    return _installed_name
