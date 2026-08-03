"""
galaxy_gateway/routes/linux_agent.py — Remote Linux Server Agent Routes
========================================================================

通过 Galaxy Gateway 远程操作多台 Linux 服务器（包括华为云等云服务器）。

能力：
  - 动态注册/注销服务器（SSH 配置）
  - 远程命令执行
  - 远程文件读写
  - 远程系统信息采集
  - 支持 SSH 密钥或密码认证

Routes:
  POST /api/v1/agents/linux/servers              — 注册服务器
  GET  /api/v1/agents/linux/servers               — 列出已注册服务器
  GET  /api/v1/agents/linux/servers/{sid}         — 查看服务器详情
  DELETE /api/v1/agents/linux/servers/{sid}       — 注销服务器
  POST /api/v1/agents/linux/servers/{sid}/execute — 远程执行命令
  POST /api/v1/agents/linux/servers/{sid}/file/read   — 读取远程文件
  POST /api/v1/agents/linux/servers/{sid}/file/write  — 写入远程文件
  GET  /api/v1/agents/linux/servers/{sid}/info    — 远程系统信息

示例：
    curl -X POST http://localhost:8765/api/v1/agents/linux/servers \
      -H "Content-Type: application/json" \
      -d '{"name":"华为云","host":"123.45.67.89","port":22,
           "user":"root","key_path":"/home/you/.ssh/id_rsa"}'

    curl -X POST http://localhost:8765/api/v1/agents/linux/servers/hw001/execute \
      -H "Content-Type: application/json" \
      -d '{"command":"uname -a && df -h"}'
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from core.atomic_json import atomic_write_json

# PR-SANDBOX-INTEGRATION: 导入沙箱安全检查
try:
    from galaxy_gateway.routes.sandbox import check_command_safety
except ImportError:
    check_command_safety = None

logger = logging.getLogger("Galaxy.LinuxAgent")

router = APIRouter(prefix="/api/v1/agents/linux", tags=["linux-agent"])

# ── 配置持久化 ──
PROJECT_ROOT = Path(__file__).parent.parent.parent
SERVERS_FILE = PROJECT_ROOT / "data" / "registered_servers.json"
SERVERS_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Pydantic 模型
# ============================================================================

class RegisterServerRequest(BaseModel):
    """注册远程 Linux 服务器"""
    name: str = Field(..., description="服务器名称（如：华为云主服务器）")
    host: str = Field(..., description="IP 地址或域名")
    port: int = Field(default=22, description="SSH 端口")
    user: str = Field(..., description="SSH 用户名")
    key_path: Optional[str] = Field(default=None, description="SSH 私钥路径（优先）")
    password: Optional[str] = Field(default=None, description="SSH 密码（备选）")
    tags: List[str] = Field(default_factory=list, description="标签（如 [\"huaweicloud\", \"production\"]）")
    description: Optional[str] = Field(default=None, description="服务器描述")


class ExecuteCommandRequest(BaseModel):
    """远程执行命令"""
    command: str = Field(..., description="要执行的 shell 命令")
    timeout: float = Field(default=60.0, description="超时秒数")
    working_dir: Optional[str] = Field(default=None, description="工作目录")
    env: Optional[Dict[str, str]] = Field(default=None, description="环境变量")


class ReadFileRequest(BaseModel):
    """读取远程文件"""
    path: str = Field(..., description="文件路径")
    max_size: int = Field(default=50000, description="最大读取字节数")


class WriteFileRequest(BaseModel):
    """写入远程文件"""
    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")
    mode: str = Field(default="644", description="文件权限（如 644、755）")
    user: Optional[str] = Field(default=None, description="文件所有者")


class ServerInfo(BaseModel):
    """已注册服务器信息（响应中隐藏密码/密钥内容）"""
    server_id: str
    name: str
    host: str
    port: int
    user: str
    auth_type: str          # "key" | "password" | "none"
    tags: List[str]
    description: Optional[str]
    registered_at: str
    last_used: Optional[str]
    status: str             # "unknown" | "online" | "offline" | "error"
    system_info: Optional[Dict] = None


class ExecuteResponse(BaseModel):
    """命令执行响应"""
    success: bool
    server_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float
    timestamp: str
    fallback: bool = False


# ============================================================================
# 服务器注册表（内存 + 持久化）
# ============================================================================

class ServerRegistry:
    """管理已注册的远程服务器配置，内存+JSON持久化。"""

    def __init__(self):
        self._servers: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载已注册服务器。"""
        if SERVERS_FILE.exists():
            try:
                with open(SERVERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._servers = data.get("servers", {})
                logger.info("Loaded %d registered servers", len(self._servers))
            except Exception as e:
                logger.warning("Failed to load server registry: %s", e)
                self._servers = {}
        else:
            self._servers = {}

    def _save(self):
        """保存到 JSON 文件。"""
        try:
            atomic_write_json(SERVERS_FILE, {'servers': self._servers}, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save server registry: %s", e)

    def register(self, req: RegisterServerRequest) -> str:
        """注册新服务器，返回 server_id。"""
        import hashlib
        server_id = hashlib.md5(f"{req.host}:{req.port}:{req.user}".encode()).hexdigest()[:8]
        self._servers[server_id] = {
            "server_id": server_id,
            "name": req.name,
            "host": req.host,
            "port": req.port,
            "user": req.user,
            "key_path": req.key_path or "",
            "password": req.password or "",
            "tags": req.tags,
            "description": req.description,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "last_used": None,
            "status": "unknown",
            "system_info": None,
        }
        self._save()
        logger.info("Registered server %s (%s@%s)", server_id, req.user, req.host)
        return server_id

    def unregister(self, server_id: str) -> bool:
        """注销服务器。"""
        if server_id in self._servers:
            del self._servers[server_id]
            self._save()
            logger.info("Unregistered server %s", server_id)
            return True
        return False

    def get(self, server_id: str) -> Optional[Dict]:
        return self._servers.get(server_id)

    def list_all(self) -> List[Dict]:
        return list(self._servers.values())

    def update_status(self, server_id: str, status: str, system_info: Optional[Dict] = None):
        if server_id in self._servers:
            self._servers[server_id]["status"] = status
            self._servers[server_id]["last_used"] = datetime.now(timezone.utc).isoformat()
            if system_info:
                self._servers[server_id]["system_info"] = system_info
            self._save()


# 全局单例
_registry = ServerRegistry()


# ============================================================================
# SSH 远程执行
# ============================================================================

def _trust_on_first_use_policy(owner):
    """构造一条 **TOFU** 主机密钥策略(信任首次使用)。

    为什么不直接用 ``paramiko.AutoAddPolicy``
    ------------------------------------------
    两个理由,第二个才是主要的。

    1. CodeQL 的 ``py/paramiko-missing-host-key-validation`` 是**句法级**判定:
       只要看见 ``AutoAddPolicy()`` 被交给 ``set_missing_host_key_policy`` 就报,
       读不懂外面那层环境变量守卫。而它说的其实没错 —— 代码里确实存在一条
       "自动接受未知密钥"的路径。用抑制注释把它按下去,等于用注释回答一个
       关于行为的问题。

    2. **更要紧的**:AutoAddPolicy 只负责"接受",落盘是另一步。两步分开就意味着
       任何一条忘了落盘的路径都会静默退化成裸 AutoAdd —— 而那正是这次要修掉的
       东西。写成一条策略之后,"接受"与"记住"变成同一个动作,想分开都分不开。

    TOFU 与 AutoAdd 的差别全在记不记得住:AutoAdd 是每次都接受新钥匙,
    TOFU 只接受第一次,之后那把钥匙再变就是事故。
    """
    import paramiko

    class _TrustOnFirstUse(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            client.get_host_keys().add(hostname, key.get_name(), key)
            # 与接受同一步落盘。失败只告警不抛 —— 见 _persist_host_keys。
            owner._persist_host_keys(client)
            logger.warning(
                "首次信任 SSH 主机 %s(%s),已记入信任库;下次连接会对着它校验。"
                "如果这不是你预期的机器,现在就该停下来。",
                hostname,
                key.get_name(),
            )

    return _TrustOnFirstUse()


class SSHExecutor:
    """基于 paramiko 的 SSH 远程执行器（复用 Node_Linux_Agent 的核心逻辑）。"""

    def __init__(self, host: str, port: int, user: str,
                 key_path: str = "", password: str = ""):
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self.password = password

    async def execute(self, command: str, timeout: float = 60.0) -> Dict:
        """在远程服务器上执行命令。"""
        try:
            import paramiko
        except ImportError:
            raise HTTPException(500, "paramiko not installed. Run: pip install paramiko")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._execute_sync, command, timeout
        )

    def _execute_sync(self, command: str, timeout: float) -> Dict:
        import paramiko
        import time

        start = time.monotonic()
        client = self._new_ssh_client()
        try:
            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.user,
                "timeout": 10,
            }
            if self.key_path and Path(self.key_path).exists():
                connect_kwargs["key_filename"] = self.key_path
            elif self.password:
                connect_kwargs["password"] = self.password

            client.connect(**connect_kwargs)
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            stdout_b = stdout.read()
            stderr_b = stderr.read()
            exit_code = stdout.channel.recv_exit_status()

            return {
                "success": exit_code == 0,
                "stdout": stdout_b.decode("utf-8", errors="replace")[:50000],
                "stderr": stderr_b.decode("utf-8", errors="replace")[:10000],
                "exit_code": exit_code,
                "execution_time_ms": (time.monotonic() - start) * 1000,
            }
        except paramiko.AuthenticationException:
            return {"success": False, "stdout": "", "stderr": "SSH 认证失败", "exit_code": -1, "execution_time_ms": 0}
        except paramiko.SSHException as e:
            return {"success": False, "stdout": "", "stderr": f"SSH 错误: {e}", "exit_code": -1, "execution_time_ms": 0}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1, "execution_time_ms": 0}
        finally:
            client.close()

    async def read_file(self, path: str, max_size: int = 50000) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_file_sync, path, max_size)

    def _read_file_sync(self, path: str, max_size: int) -> str:
        import paramiko
        client = self._new_ssh_client()
        try:
            self._connect(client)
            stdin, stdout, _ = client.exec_command(f"cat '{path}' | head -c {max_size}")
            data = stdout.read().decode("utf-8", errors="replace")
            return data
        finally:
            client.close()

    async def write_file(self, path: str, content: str, mode: str = "644") -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._write_file_sync, path, content, mode)

    def _write_file_sync(self, path: str, content: str, mode: str) -> bool:
        import paramiko
        client = self._new_ssh_client()
        try:
            self._connect(client)
            escaped = content.replace("'", "'\"'\"'")
            # Escape the path the same way as the content — it is interpolated
            # into several single-quoted shell words below, so an unescaped
            # single quote in the path would break the command / allow injection.
            escaped_path = path.replace("'", "'\"'\"'")
            # exec_command returns immediately without waiting; block on the
            # remote exit status so (a) the write completes before client.close()
            # tears the connection down (otherwise a large write can be
            # truncated) and (b) we report real success instead of always True.
            # NOTE: $(dirname ...) must sit inside DOUBLE quotes to be expanded;
            # the previous single-quoted '$(dirname ...)' was taken literally, so
            # the real parent dir was never created (a junk dir named
            # "$(dirname <path>)" was made in the remote CWD instead).
            _stdin, stdout, stderr = client.exec_command(
                f"mkdir -p \"$(dirname '{escaped_path}')\" && "
                f"printf '%s' '{escaped}' > '{escaped_path}' && "
                f"chmod {mode} '{escaped_path}'"
            )
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                logger.warning(
                    "remote write_file failed (exit %s): %s",
                    exit_status,
                    stderr.read().decode(errors="replace").strip(),
                )
                return False
            return True
        except Exception:
            return False
        finally:
            client.close()

    async def get_system_info(self) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_system_info_sync)

    def _get_system_info_sync(self) -> Dict:
        import paramiko
        client = self._new_ssh_client()
        try:
            self._connect(client)
            commands = {
                "hostname": "hostname",
                "os": "cat /etc/os-release 2>/dev/null | head -5 || uname -a",
                "kernel": "uname -r",
                "cpu": "nproc",
                "memory": "free -h 2>/dev/null | head -2",
                "disk": "df -h / 2>/dev/null | tail -1",
                "uptime": "uptime -p 2>/dev/null || uptime",
                "load": "cat /proc/loadavg 2>/dev/null | awk '{print $1,$2,$3}'",
            }
            info = {"host": self.host, "timestamp": datetime.now(timezone.utc).isoformat()}
            for key, cmd in commands.items():
                try:
                    stdin, stdout, _ = client.exec_command(cmd, timeout=5)
                    info[key] = stdout.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    info[key] = "N/A"
            return info
        finally:
            client.close()

    # ── SSH 主机密钥策略 ──────────────────────────────────────────────────
    #
    # 这里此前 5 处都是 `set_missing_host_key_policy(AutoAddPolicy())` ——
    # 也就是**对任何主机密钥都照连不误**。CodeQL 的
    # py/paramiko-missing-host-key-validation 报的就是这个,5 条全在本文件。
    #
    # 为什么它是真的风险:这条链路会把密码/私钥送过去,并在对端执行任意命令、
    # 读写任意文件。AutoAdd 意味着一台冒充目标 IP 的机器可以直接拿到这些 ——
    # 而且过程完全静默,不会有任何一行日志说"对面换人了"。
    #
    # 换成什么:**真正的 TOFU**(信任首次使用)。
    #   * 首次连接:在显式开启 GALAXY_SSH_TRUST_ON_FIRST_USE 时接受并**落盘**;
    #   * 之后每一次:对着落盘的那把校验,换了就拒。
    # AutoAdd 与 TOFU 的差别正在这里 —— AutoAdd 是"每次都接受新钥匙",
    # TOFU 是"只接受第一次,之后再变就是事故"。此前的写法看着像 TOFU,其实不是。
    #
    # 默认(不设那个环境变量)是拒绝未知主机。家用局域网首次配对会因此失败一次,
    # 这是有意的:让"我现在要信任这台机器"成为一个人做出的、看得见的决定。
    _KNOWN_HOSTS = Path.home() / ".galaxy" / "ssh_known_hosts"

    @classmethod
    def _new_ssh_client(cls):
        import paramiko

        client = paramiko.SSHClient()
        # 系统 known_hosts 优先;读不到不算错(容器里常常就没有)。
        try:
            client.load_system_host_keys()
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取系统 known_hosts 失败(忽略): %s", exc)
        if cls._KNOWN_HOSTS.is_file():
            try:
                client.load_host_keys(str(cls._KNOWN_HOSTS))
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取 %s 失败: %s", cls._KNOWN_HOSTS, exc)

        tofu = str(os.getenv("GALAXY_SSH_TRUST_ON_FIRST_USE", "")).strip().lower() in ("1", "true", "yes", "on")
        client.set_missing_host_key_policy(_trust_on_first_use_policy(cls) if tofu else paramiko.RejectPolicy())
        return client

    @classmethod
    def _persist_host_keys(cls, client) -> None:
        """把新学到的主机密钥落盘,让下一次连接变成**校验**而不是再学一遍。

        由策略在接受的**同一步**里调用 —— 见 ``_trust_on_first_use_policy``。
        """
        try:
            cls._KNOWN_HOSTS.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(cls._KNOWN_HOSTS))
            # 主机密钥不是秘密,但这个文件决定"信任谁",别人可写就等于信任可被改。
            os.chmod(cls._KNOWN_HOSTS, 0o600)
        except Exception as exc:  # noqa: BLE001 —— 落盘失败不该让本次操作失败
            logger.warning("保存主机密钥到 %s 失败: %s", cls._KNOWN_HOSTS, exc)

    def _connect(self, client):
        import paramiko
        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user,
            "timeout": 10,
        }
        if self.key_path and Path(self.key_path).exists():
            connect_kwargs["key_filename"] = self.key_path
        elif self.password:
            connect_kwargs["password"] = self.password
        client.connect(**connect_kwargs)

    async def list_dir(self, path: str) -> List[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_dir_sync, path)

    def _list_dir_sync(self, path: str) -> List[str]:
        import paramiko
        client = self._new_ssh_client()
        try:
            self._connect(client)
            stdin, stdout, _ = client.exec_command(f"ls -la '{path}' 2>/dev/null")
            return stdout.read().decode("utf-8", errors="replace").strip().split("\n")[:500]
        finally:
            client.close()


def _to_server_info(server: Dict) -> ServerInfo:
    """内部数据 → 响应模型（隐藏敏感信息）。"""
    key_path = server.get("key_path", "")
    password = server.get("password", "")
    auth_type = "key" if key_path else ("password" if password else "none")
    return ServerInfo(
        server_id=server["server_id"],
        name=server["name"],
        host=server["host"],
        port=server["port"],
        user=server["user"],
        auth_type=auth_type,
        tags=server.get("tags", []),
        description=server.get("description"),
        registered_at=server.get("registered_at", ""),
        last_used=server.get("last_used"),
        status=server.get("status", "unknown"),
        system_info=server.get("system_info"),
    )


# ============================================================================
# 路由
# ============================================================================

@router.post("/servers", response_model=ServerInfo)
async def register_server(req: RegisterServerRequest):
    """注册一台新的远程 Linux 服务器。"""
    server_id = _registry.register(req)
    server = _registry.get(server_id)
    return _to_server_info(server)


@router.get("/servers", response_model=List[ServerInfo])
async def list_servers():
    """列出所有已注册的远程服务器。"""
    return [_to_server_info(s) for s in _registry.list_all()]


@router.get("/servers/{server_id}", response_model=ServerInfo)
async def get_server(server_id: str):
    """查看单台服务器详情。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")
    return _to_server_info(server)


@router.delete("/servers/{server_id}")
async def unregister_server(server_id: str):
    """注销服务器。"""
    if not _registry.unregister(server_id):
        raise HTTPException(404, f"Server {server_id} not found")
    return {"success": True, "message": f"Server {server_id} unregistered"}


@router.post("/servers/{server_id}/execute", response_model=ExecuteResponse)
async def execute_command(server_id: str, req: ExecuteCommandRequest):
    """在远程服务器上执行 shell 命令（带沙箱预检）。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")

    # PR-SANDBOX-INTEGRATION: 执行前先做安全检查
    safety = check_command_safety(req.command) if check_command_safety else None
    if safety and safety.blocked:
        logger.warning("[SANDBOX] 命令被阻止: %s | 原因: %s",
                       req.command, safety.blocked_reason)
        return ExecuteResponse(
            success=False,
            server_id=server_id,
            command=req.command,
            stdout="",
            stderr=f"[SANDBOX BLOCKED] {safety.blocked_reason}",
            exit_code=-1,
            execution_time_ms=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    if safety and safety.warnings:
        logger.info("[SANDBOX] 命令警告 (%s): %s",
                   req.command, safety.warnings)

    executor = SSHExecutor(
        host=server["host"],
        port=server["port"],
        user=server["user"],
        key_path=server.get("key_path", ""),
        password=server.get("password", ""),
    )

    result = await executor.execute(req.command, timeout=req.timeout)

    _registry.update_status(
        server_id,
        "online" if result["success"] else "error"
    )

    return ExecuteResponse(
        success=result["success"],
        server_id=server_id,
        command=req.command,
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
        execution_time_ms=result["execution_time_ms"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/servers/{server_id}/file/read")
async def read_remote_file(server_id: str, req: ReadFileRequest):
    """读取远程服务器上的文件。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")

    executor = SSHExecutor(
        host=server["host"], port=server["port"], user=server["user"],
        key_path=server.get("key_path", ""), password=server.get("password", ""),
    )
    content = await executor.read_file(req.path, req.max_size)
    _registry.update_status(server_id, "online")

    return {
        "success": True,
        "server_id": server_id,
        "path": req.path,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/servers/{server_id}/file/write")
async def write_remote_file(server_id: str, req: WriteFileRequest):
    """写入文件到远程服务器。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")

    executor = SSHExecutor(
        host=server["host"], port=server["port"], user=server["user"],
        key_path=server.get("key_path", ""), password=server.get("password", ""),
    )
    ok = await executor.write_file(req.path, req.content, req.mode)
    _registry.update_status(server_id, "online" if ok else "error")

    return {
        "success": ok,
        "server_id": server_id,
        "path": req.path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/servers/{server_id}/info")
async def get_remote_info(server_id: str):
    """获取远程服务器的系统信息。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")

    executor = SSHExecutor(
        host=server["host"], port=server["port"], user=server["user"],
        key_path=server.get("key_path", ""), password=server.get("password", ""),
    )
    info = await executor.get_system_info()
    _registry.update_status(server_id, "online", info)

    return {
        "success": True,
        "server_id": server_id,
        "system_info": info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/servers/{server_id}/probe")
async def probe_server(server_id: str):
    """探测服务器是否可达（不返回敏感信息）。"""
    server = _registry.get(server_id)
    if not server:
        raise HTTPException(404, f"Server {server_id} not found")

    executor = SSHExecutor(
        host=server["host"], port=server["port"], user=server["user"],
        key_path=server.get("key_path", ""), password=server.get("password", ""),
    )
    result = await executor.execute("echo 'pong'", timeout=5)
    online = result["success"] and "pong" in result["stdout"]
    _registry.update_status(server_id, "online" if online else "offline")

    return {
        "server_id": server_id,
        "reachable": online,
        "latency_ms": result["execution_time_ms"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
