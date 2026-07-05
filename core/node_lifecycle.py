"""
core/node_lifecycle.py — 单节点一键启停(阶段2a)
=====================================================

面板节点名单台的「一键启停」后端。每个节点就是 ``python nodes/Node_XX/main.py``
监听一个端口的独立服务;这里直接用受管子进程拉起/停掉单个节点,并用一个 PID 文件
(runtime/node_pids.json)记录,重启 Galaxy 后仍能识别自己拉起的节点。

自包含、不依赖 launcher 内部实例(API 路由可直接调用)。阶段3 会在此基础上加一个
「按所选 Docker/Podman 起容器」的变体。全程容错。

判断"是否在运行":优先 PID 存活;PID 未知/已死则退回 HTTP 端口探测(节点可能由
launcher 或其它方式起的)。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.NodeLifecycle")

_ROOT = Path(__file__).resolve().parent.parent
_NODES_DIR = _ROOT / "nodes"
_PID_FILE = _ROOT / "runtime" / "node_pids.json"
_LOG_DIR = _ROOT / "logs" / "nodes"


def _load_pids() -> Dict[str, int]:
    try:
        if _PID_FILE.exists():
            return {str(k): int(v) for k, v in json.loads(_PID_FILE.read_text("utf-8")).items()}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_pids(pids: Dict[str, int]) -> None:
    try:
        _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PID_FILE.write_text(json.dumps(pids), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("写 node_pids.json 失败: %s", exc)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            return str(pid) in out
        os.kill(pid, 0)  # 不发信号,只探测存在
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_dir(node: str) -> Optional[str]:
    """把 '71' / 'Node_71' / 'Node_71_MultiDeviceCoordination' / 'MultiDevice...' 归一到实际目录名。"""
    node = str(node).strip()
    if (_NODES_DIR / node).is_dir():
        return node
    # 纯数字或 Node_数字
    digits = node.replace("Node_", "").split("_")[0]
    if digits.isdigit():
        want = int(digits)
        for d in os.listdir(_NODES_DIR):
            if d.startswith("Node_"):
                parts = d.split("_", 2)
                if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) == want:
                    return d
    # 按名字尾段匹配
    for d in os.listdir(_NODES_DIR):
        if d.startswith("Node_") and d.split("_", 2)[-1].lower() == node.lower():
            return d
    return None


def _port_probe(dir_name: str) -> bool:
    try:
        import httpx
        from core.port_config import get_node_port
        port = get_node_port(dir_name)
        if not port:
            return False
        r = httpx.get(f"http://127.0.0.1:{int(port)}/", timeout=1.5)
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def is_running(node: str) -> Tuple[bool, str]:
    """(是否在跑, 依据)。先看我们记录的 PID,再退回端口探测。"""
    dir_name = _resolve_dir(node)
    if not dir_name:
        return (False, "not_found")
    pid = _load_pids().get(dir_name, 0)
    if pid and _pid_alive(pid):
        return (True, f"pid:{pid}")
    if _port_probe(dir_name):
        return (True, "port")
    return (False, "stopped")


def start_node(node: str) -> Dict[str, object]:
    """一键启动单个节点(python main.py,受管子进程,日志写 logs/nodes/)。"""
    dir_name = _resolve_dir(node)
    if not dir_name:
        return {"ok": False, "error": f"未找到节点: {node}"}
    main_py = _NODES_DIR / dir_name / "main.py"
    if not main_py.exists():
        return {"ok": False, "error": f"{dir_name}/main.py 不存在"}
    running, why = is_running(dir_name)
    if running:
        return {"ok": True, "already": True, "dir": dir_name, "why": why}
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        logf = open(_LOG_DIR / f"{dir_name}.log", "ab")
        kwargs: Dict[str, object] = dict(
            cwd=str(_ROOT), stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([sys.executable, str(main_py)], **kwargs)  # noqa: S603
        pids = _load_pids()
        pids[dir_name] = proc.pid
        _save_pids(pids)
        logger.info("节点已启动 %s (pid=%d)", dir_name, proc.pid)
        return {"ok": True, "dir": dir_name, "pid": proc.pid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "dir": dir_name}


def stop_node(node: str) -> Dict[str, object]:
    """一键停止我们拉起的单个节点。只停 PID 文件里记录的(不误杀别人起的)。"""
    dir_name = _resolve_dir(node)
    if not dir_name:
        return {"ok": False, "error": f"未找到节点: {node}"}
    pids = _load_pids()
    pid = pids.get(dir_name, 0)
    if not pid or not _pid_alive(pid):
        pids.pop(dir_name, None)
        _save_pids(pids)
        return {"ok": True, "already_stopped": True, "dir": dir_name}
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        pids.pop(dir_name, None)
        _save_pids(pids)
        logger.info("节点已停止 %s (pid=%d)", dir_name, pid)
        return {"ok": True, "dir": dir_name, "stopped_pid": pid}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "dir": dir_name}
