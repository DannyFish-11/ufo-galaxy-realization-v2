"""device_client/executors/carrier.py — Agent 载体的执行插件(跨设备整体方案阶段 5)。

载体装在别的电脑、Linux 服务器、云主机上,接中心派来的 Agent、在本机把整段目标做完。它能做的动作:

* ``run_code`` —— 跑一段 Python 或 shell,**一律在沙箱里**(Docker:不联网、限内存 / CPU / 进程数、只读根、
  无特权用户、跑完即删);本机没有可用的 Docker 时这个动作不报(报了做不到的动作,智能体会去调,然后失败);
* ``read_file`` / ``write_file`` / ``list_files`` —— 只在载体自己的工作目录里(``GALAXY_CARRIER_WORKDIR``,
  默认 ``~/.galaxy-carrier/work``),目录外的路径一律拒绝;
* ``get_status`` —— 这台机器有什么:系统、CPU、内存、GPU、有没有图形界面、沙箱能不能用。

不点屏幕、不动键鼠 —— 那是「手和眼」式电脑(``device_client`` 的桌面插件)的事。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from device_client.executors import DesktopExecutor

SANDBOX_IMAGE = os.environ.get("GALAXY_CARRIER_SANDBOX_IMAGE", "python:3.11-slim")
MAX_OUTPUT = 20000
MAX_FILE_BYTES = 2_000_000
MAX_RUN_S = 600

#: 每个动作一句话说明 + 参数(报能力时进设备整体卡;载体上的推理加行动循环也拿它当工具说明)。
ACTIONS: Dict[str, Dict[str, Any]] = {
    "run_code": {
        "description": "在载体上的沙箱里跑一段 Python 或 shell(不联网、限内存与时间、跑完即删),拿回输出",
        "parameters": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["python", "sh"]},
                "code": {"type": "string"},
                "timeout_s": {"type": "integer", "description": f"最长秒数,上限 {MAX_RUN_S}"},
            },
            "required": ["code"],
        },
    },
    "read_file": {
        "description": "读载体工作目录里的一个文本文件",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    "write_file": {
        "description": "在载体工作目录里写一个文本文件(没有就建,有就覆盖)",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "list_files": {
        "description": "列出载体工作目录(或其中一个子目录)里的文件",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    "get_status": {
        "description": "这台机器有什么:系统、CPU、内存、GPU、有没有图形界面、沙箱能不能用",
        "parameters": {"type": "object", "properties": {}},
    },
}


def _workdir() -> Path:
    raw = os.environ.get("GALAXY_CARRIER_WORKDIR", "").strip()
    p = Path(raw).expanduser() if raw else Path.home() / ".galaxy-carrier" / "work"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def _docker_ok() -> Tuple[bool, str]:
    exe = shutil.which("docker")
    if not exe:
        return False, "没装 Docker:代码只在沙箱里跑,没有沙箱就不接 run_code。装好 Docker 后重启载体"
    try:
        r = subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker 不通:{exc}"
    if r.returncode != 0:
        return False, f"Docker 守护进程不通:{(r.stderr or r.stdout).strip()[:200]}"
    return True, f"Docker {r.stdout.strip()}"


def carrier_device_type(platform_name: str) -> str:
    """载体在名册里算什么:容器里 → ``container_docker``;没有图形界面的 Linux → ``linux_server``;
    否则就是这台电脑本来的类型(笔记本 / 台式机)。能不能接 Agent 不看它,看报能力时的声明。"""
    from device_client.pairing import detect_device_type

    if Path("/.dockerenv").exists():
        return "container_docker"
    if platform_name == "linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "linux_server"
    return detect_device_type(platform_name)


class CarrierExecutor(DesktopExecutor):
    name = "carrier"

    def __init__(self) -> None:
        from device_client.pairing import this_platform

        self.platform = this_platform()
        self._sandbox: Optional[Tuple[bool, str]] = None

    def sandbox(self) -> Tuple[bool, str]:
        if self._sandbox is None:
            self._sandbox = _docker_ok()
        return self._sandbox

    def available(self) -> Tuple[bool, str]:
        # 没有沙箱照样能用(文件、状态、整段目标),只是不接 run_code
        ok, why = self.sandbox()
        return True, ("沙箱可用:" + why) if ok else why

    def supported_actions(self) -> List[str]:
        base = ["read_file", "write_file", "list_files", "get_status"]
        return (["run_code"] + base) if self.sandbox()[0] else base

    def capability_schemas(self) -> List[Dict[str, Any]]:
        """报能力时带上的每个动作的说明与参数(``capability_schemas``)。"""
        return [{"action": a, **ACTIONS[a]} for a in self.supported_actions()]

    def host_facts(self) -> Dict[str, Any]:
        system = platform.system()
        facts: Dict[str, Any] = {
            "os": f"{system} {platform.release()}",
            "arch": platform.machine(),
            "cpus": os.cpu_count() or 0,
            "has_gui": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            or system in ("Windows", "Darwin"),
            "gpu": bool(shutil.which("nvidia-smi")),
            "sandbox": self.sandbox()[0],
        }
        try:
            facts["memory_mb"] = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024)
        except (ValueError, OSError, AttributeError):
            pass
        return facts

    def describe(self) -> Dict[str, Any]:
        out = super().describe()
        out["host"] = self.host_facts()
        return out

    # ── 动作 ──────────────────────────────────────────────────────────────────

    def _path(self, rel: str) -> Path:
        base = _workdir()
        target = (base / str(rel or "")).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"只能在载体的工作目录里读写:{rel!r} 在目录外")
        return target

    def _do(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "get_status":
            return {"success": True, "host": self.host_facts(), "workdir": str(_workdir())}
        if action == "list_files":
            d = self._path(params.get("path", ""))
            if not d.is_dir():
                return {"success": False, "error": f"不是目录:{params.get('path', '')}"}
            return {"success": True, "files": sorted(str(p.relative_to(_workdir())) for p in d.iterdir())[:500]}
        if action == "read_file":
            f = self._path(params.get("path", ""))
            if not f.is_file():
                return {"success": False, "error": f"没有这个文件:{params.get('path', '')}"}
            return {"success": True, "content": f.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")}
        if action == "write_file":
            f = self._path(params.get("path", ""))
            data = str(params.get("content", "")).encode("utf-8")
            if len(data) > MAX_FILE_BYTES:
                return {"success": False, "error": f"太大了(上限 {MAX_FILE_BYTES} 字节)"}
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
            return {"success": True, "path": str(f.relative_to(_workdir())), "bytes": len(data)}
        if action == "run_code":
            return self._run_code(params)
        return {"success": False, "error": f"不支持 {action}"}

    def _run_code(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok, why = self.sandbox()
        if not ok:
            return {"success": False, "error": why}
        language = str(params.get("language") or "python").lower()
        code = str(params.get("code") or params.get("command") or "")
        if not code.strip():
            return {"success": False, "error": "需要 code"}
        try:
            timeout = max(1, min(int(params.get("timeout_s") or 60), MAX_RUN_S))
        except (TypeError, ValueError):
            timeout = 60
        if language in ("python", "py"):
            cmd = ["python", "-c", code]
        elif language in ("sh", "shell", "bash"):
            cmd = ["sh", "-c", code]
        else:
            return {"success": False, "error": f"不支持的语言 {language!r}(python / sh)"}
        name = f"galaxy-carrier-{uuid.uuid4().hex[:12]}"
        docker = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none", "--memory", "512m", "--cpus", "1", "--pids-limit", "128",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            SANDBOX_IMAGE, "timeout", "-s", "KILL", str(timeout), *cmd,
        ]  # fmt: skip
        try:
            # 沙箱里的 timeout 先到;外面多给一截给拉起容器(第一次可能要拉镜像)
            r = subprocess.run(docker, capture_output=True, text=True, timeout=timeout + 120)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
            return {"success": False, "error": f"沙箱里跑了 {timeout} 秒没结束,已停"}
        out: Dict[str, Any] = {
            "success": r.returncode == 0,
            "exit_code": r.returncode,
            "stdout": r.stdout[-MAX_OUTPUT:],
            "stderr": r.stderr[-MAX_OUTPUT:],
            "sandbox": SANDBOX_IMAGE,
        }
        if r.returncode == 137:
            out["error"] = f"沙箱里的程序被强行停了:跑满 {timeout} 秒,或用满 512MB 内存"
        elif r.returncode != 0:
            out["error"] = (r.stderr or r.stdout).strip()[-500:] or f"退出码 {r.returncode}"
        return out
