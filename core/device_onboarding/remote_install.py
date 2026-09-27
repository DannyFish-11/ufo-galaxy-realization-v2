"""core/device_onboarding/remote_install.py — 智能体经 SSH 把客户端装到那台电脑上并配对。

**这条路省掉的是"人去敲命令",不是"那台电脑同意"。** 前提有两个,都由人给:

1. 那台电脑开着远程登录(mDNS 里能看到 ``_ssh``,见 :mod:`core.lan_computers`);
2. 人把登录凭据给我们一次(用户名 + 密码或私钥)。

拿到这两样,剩下的全自动:校验主机指纹 → 看清是什么系统 → 传客户端过去 → 远程执行
配对 → 等它真的连上主脑,才算接入成功。凭据只在这一次用,不落盘(见 :func:`install_and_pair`)。

**主机指纹必须先过。** 走 :mod:`core.ssh_host_keys`:第一次连记下指纹并告诉人,之后
对不上就拒 —— 局域网里冒充那台电脑骗走密码的路要先堵上,否则这条"方便"就是个洞。

**装得了什么,如实说。** 客户端的连接层三个系统共用,执行层按系统:

* Linux / macOS:``device_client`` 加上 Linux 需要的 ``x11_actions``,几个文件,能传过去直接跑;
* Windows:执行层是 ``WindowsExecutionArbiter``(体量大、依赖 Windows 本机组件),
  现在**不能**这样远程装。这时如实回一条给人执行的命令,不假装装好了。
"""

from __future__ import annotations

import logging
import os
import posixpath
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Onboarding.RemoteInstall")

#: 传过去的文件:连接层 + 三个执行插件 + Linux 执行插件用到的动作实现。
#: 每一项是 (本仓库里的路径, 远端相对路径)。
PAYLOAD: Tuple[Tuple[str, str], ...] = (
    ("device_client/__init__.py", "device_client/__init__.py"),
    ("device_client/__main__.py", "device_client/__main__.py"),
    ("device_client/client.py", "device_client/client.py"),
    ("device_client/pairing.py", "device_client/pairing.py"),
    ("device_client/autostart.py", "device_client/autostart.py"),
    ("device_client/executors/__init__.py", "device_client/executors/__init__.py"),
    ("device_client/executors/linux_x11.py", "device_client/executors/linux_x11.py"),
    ("device_client/executors/macos.py", "device_client/executors/macos.py"),
    ("device_client/executors/windows.py", "device_client/executors/windows.py"),
    (
        "nodes/Node_124_LinuxDesktopAuto/x11_actions.py",
        "nodes/Node_124_LinuxDesktopAuto/x11_actions.py",
    ),
    ("nodes/Node_124_LinuxDesktopAuto/__init__.py", "nodes/Node_124_LinuxDesktopAuto/__init__.py"),
)

#: 远端放客户端的地方(用户自己的目录,不需要管理员)。
REMOTE_DIR = ".galaxy-device-client"

#: 能这样远程装的系统。Windows 见模块头。
INSTALLABLE = ("linux", "macos")


class RemoteInstallError(Exception):
    def __init__(self, message: str, how_to_fix: str = "") -> None:
        super().__init__(message)
        self.how_to_fix = how_to_fix


@dataclass
class RemoteFacts:
    """在那台电脑上看到的事实。全部来自实际执行的命令,不猜。"""

    uname: str = ""
    platform: str = "unknown"  # linux / macos / windows / unknown
    python: str = ""  # 能用的 python 可执行名(python3 / python)
    python_version: str = ""
    has_display: bool = False
    hostname: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uname": self.uname,
            "platform": self.platform,
            "python": self.python,
            "python_version": self.python_version,
            "has_display": self.has_display,
            "hostname": self.hostname,
            "notes": list(self.notes),
        }


def platform_from_uname(uname: str) -> str:
    u = (uname or "").strip().lower()
    if "darwin" in u:
        return "macos"
    if "linux" in u:
        return "linux"
    if any(w in u for w in ("mingw", "msys", "cygwin", "windows")):
        return "windows"
    return "unknown"


def credential_inputs() -> List[Dict[str, Any]]:
    """要人填的那几项。``secret`` 的不进日志、不落盘。"""
    return [
        {"name": "username", "label": "那台电脑的登录用户名", "required": True},
        {"name": "password", "label": "登录密码(用私钥就不用填)", "required": False, "secret": True},
        {"name": "private_key", "label": "私钥内容(有就用它,比密码稳)", "required": False, "secret": True},
        {"name": "port", "label": "SSH 端口(默认 22)", "required": False},
    ]


def _redact(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """能进日志/回包的那一份 —— 把密码私钥摘掉。"""
    secret = {i["name"] for i in credential_inputs() if i.get("secret")}
    return {k: ("<已收到,不记录>" if k in secret and v else v) for k, v in (inputs or {}).items()}


# ── 远端执行的几步(每一步都是可单测的纯函数 + 一次远端调用) ─────────────────────


PROBE = 'uname -a; echo ---; hostname; echo ---; (python3 -V || python -V) 2>&1; echo ---; echo "DISPLAY=${DISPLAY-}"'


def parse_probe(output: str) -> RemoteFacts:
    """解析体检输出。拿不到的就留空,不编。"""
    parts = [p.strip() for p in (output or "").split("---")]
    facts = RemoteFacts()
    if parts:
        facts.uname = parts[0].splitlines()[0].strip() if parts[0] else ""
        facts.platform = platform_from_uname(facts.uname)
    if len(parts) > 1 and parts[1]:
        facts.hostname = parts[1].splitlines()[0].strip()
    if len(parts) > 2 and parts[2]:
        line = parts[2].splitlines()[0].strip()
        if line.lower().startswith("python"):
            facts.python_version = line
            facts.python = "python3" if "python3" in line.lower() or line.startswith("Python 3") else "python"
    if len(parts) > 3:
        facts.has_display = "DISPLAY=" in parts[3] and parts[3].split("DISPLAY=", 1)[1].strip() not in ("", "''")
    if not facts.python:
        facts.notes.append("那台电脑上没找到 python3")
    return facts


def pair_command(python: str, code: str, gateway: str, remote_dir: str = REMOTE_DIR) -> str:
    """远端要跑的那一条。cd 到客户端目录,带上配对码与主脑地址,并设置开机自连。"""
    return (
        f"cd {shlex.quote(remote_dir)} && "
        f"{shlex.quote(python)} -m device_client --pair {shlex.quote(code)} "
        f"--gateway {shlex.quote(gateway)} --install-autostart --no-run"
    )


def run_in_background_command(python: str, remote_dir: str = REMOTE_DIR) -> str:
    """配对完让它自己连上 —— nohup 起在后台,SSH 断开也不会被带走。"""
    return (
        f"cd {shlex.quote(remote_dir)} && "
        f"nohup {shlex.quote(python)} -m device_client > device_client.log 2>&1 & echo started"
    )


def repo_root() -> str:
    # core/device_onboarding/remote_install.py → core/device_onboarding → core → 仓库根
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def payload_files(root: Optional[str] = None) -> List[Tuple[str, str]]:
    """要传的文件,过滤掉本仓库里确实没有的(不同分支文件可能有出入)。"""
    base = root or repo_root()
    out = []
    for local, remote in PAYLOAD:
        p = os.path.join(base, local)
        if os.path.exists(p):
            out.append((p, posixpath.join(REMOTE_DIR, remote)))
    return out


def windows_fallback(code: str, gateway: str) -> Dict[str, Any]:
    """Windows:如实说远程装不了,给人一条命令。"""
    cmd = f"python -m device_client --pair {code} --gateway {gateway} --install-autostart"
    return {
        "installed": False,
        "platform": "windows",
        "commands": [cmd],
        "why": "Windows 的执行层是 WindowsExecutionArbiter,依赖 Windows 本机组件,现在不能这样远程装",
        "how_to_fix": f"在那台 Windows 上进到本仓库目录执行:{cmd}",
    }


# ── 真正走一趟 ────────────────────────────────────────────────────────────────────


async def install_and_pair(
    host: str,
    inputs: Dict[str, Any],
    code: str,
    gateway: str,
    *,
    connector: Optional[Any] = None,
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """登进去、装上、配对。返回做了什么;失败抛 :class:`RemoteInstallError`。

    ``connector`` 只为测试留口:默认用 :func:`_asyncssh_connect`(真 SSH,带主机指纹校验)。
    凭据从 ``inputs`` 里拿,用完就随函数栈消失 —— **不写盘、不进日志**(日志走 :func:`_redact`)。
    """
    username = str(inputs.get("username") or "").strip()
    if not username:
        raise RemoteInstallError("没有登录用户名", "告诉我那台电脑的登录用户名")
    password = inputs.get("password") or None
    private_key = inputs.get("private_key") or None
    if not password and not private_key:
        raise RemoteInstallError("没有登录凭据", "给我那台电脑的登录密码,或者一份私钥")
    try:
        port = int(inputs.get("port") or 22)
    except (TypeError, ValueError):
        port = 22

    logger.info("远程接入 %s@%s:%s(凭据 %s)", username, host, port, _redact(inputs))
    connect = connector or _asyncssh_connect
    session = await connect(host=host, port=port, username=username, password=password, private_key=private_key)
    try:
        probe = await session.run(PROBE)
        facts = parse_probe(probe.get("stdout", ""))
        facts.hostname = facts.hostname or host
        if facts.platform == "windows":
            return {"facts": facts.to_dict(), **windows_fallback(code, gateway)}
        if facts.platform not in INSTALLABLE:
            raise RemoteInstallError(
                f"认不出那台电脑是什么系统(uname: {facts.uname or '没拿到'})",
                "确认它是 Linux 或 macOS;Windows 走给人执行命令那条路",
            )
        if not facts.python:
            raise RemoteInstallError(
                "那台电脑上没有 python3",
                "先在它上面装 Python 3(macOS: brew install python;Debian/Ubuntu: sudo apt install python3)",
            )

        files = payload_files(root)
        if not files:
            raise RemoteInstallError("本机找不到要传过去的客户端文件", "检查仓库是否完整(device_client/ 在不在)")
        await session.put(files)

        paired = await session.run(pair_command(facts.python, code, gateway))
        if not paired.get("ok"):
            raise RemoteInstallError(
                f"在那台电脑上配对没成功:{(paired.get('stderr') or paired.get('stdout') or '').strip()[:300]}",
                "多半是它连不到主脑地址,或者配对码过期了(10 分钟);让我重新发一个",
            )
        started = await session.run(run_in_background_command(facts.python))
        return {
            "installed": True,
            "platform": facts.platform,
            "facts": facts.to_dict(),
            "files": [r for _l, r in files],
            "pair_output": (paired.get("stdout") or "").strip()[-500:],
            "started": bool(started.get("ok")),
            "notes": facts.notes,
        }
    finally:
        await session.close()


# ── 真 SSH(带主机指纹校验) ─────────────────────────────────────────────────────


class _AsyncsshSession:
    """把 asyncssh 连接收成三个动作:run / put / close。测试用同形状的假对象顶替。"""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def run(self, command: str) -> Dict[str, Any]:
        result = await self._conn.run(command, check=False)
        return {
            "ok": result.exit_status == 0,
            "exit_status": result.exit_status,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
        }

    async def put(self, files: List[Tuple[str, str]]) -> None:
        async with self._conn.start_sftp_client() as sftp:
            for local, remote in files:
                parent = posixpath.dirname(remote)
                if parent:
                    await sftp.makedirs(parent, exist_ok=True)
                await sftp.put(local, remote)

    async def close(self) -> None:
        self._conn.close()
        await self._conn.wait_closed()


async def _asyncssh_connect(
    *, host: str, port: int, username: str, password: Optional[str], private_key: Optional[str]
) -> _AsyncsshSession:
    import asyncssh

    from core.ssh_host_keys import connect_kwargs

    kwargs: Dict[str, Any] = {"host": host, "port": port, "username": username, **connect_kwargs()}
    if password:
        kwargs["password"] = password
    if private_key:
        kwargs["client_keys"] = [asyncssh.import_private_key(private_key)]
    try:
        conn = await asyncssh.connect(**kwargs)
    except asyncssh.HostKeyNotVerifiable as exc:
        raise RemoteInstallError(
            f"那台电脑的主机指纹对不上,没有把凭据发出去:{exc}",
            "如果它刚重装或换了机器,先忘掉旧指纹再来;否则局域网里有人在冒充它",
        ) from exc
    except asyncssh.PermissionDenied as exc:
        raise RemoteInstallError("用户名或密码/私钥不对", "确认登录凭据;macOS 要先在「共享」里打开远程登录") from exc
    except OSError as exc:
        raise RemoteInstallError(f"连不上 {host}:{port}:{exc}", "确认那台电脑开着远程登录,且在同一个网里") from exc
    return _AsyncsshSession(conn)
