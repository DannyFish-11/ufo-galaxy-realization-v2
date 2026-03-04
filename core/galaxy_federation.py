"""
UFO Galaxy - 多实例联邦协作模块（Galaxy Federation）
===================================================

功能：
1. 实例注册 & 心跳（HTTP/WebSocket）
2. 远程任务转发
3. 配置项：FEDERATION_ENABLED、FEDERATION_PEERS

使用方法：
    from core.galaxy_federation import get_federation

    fed = get_federation()
    await fed.start()

    # 转发任务到远程实例
    result = await fed.forward_task("http://peer2:8000", {
        "command": "ping",
        "params": {}
    })

    # 列出在线 peer
    peers = fed.list_peers()
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.Federation")

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


# ============================================================================
# 配置
# ============================================================================

def _federation_enabled() -> bool:
    return os.environ.get("FEDERATION_ENABLED", "false").lower() in ("1", "true", "yes")


def _federation_peers() -> List[str]:
    raw = os.environ.get("FEDERATION_PEERS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _local_gateway_url() -> str:
    host = os.environ.get("FEDERATION_LOCAL_HOST", "http://127.0.0.1")
    port = os.environ.get("GATEWAY_PORT", "8000")
    return f"{host}:{port}"


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class PeerInstance:
    """远程 Galaxy 实例信息"""
    instance_id: str
    url: str
    name: str = ""
    last_heartbeat: float = field(default_factory=time.time)
    status: str = "unknown"  # healthy / degraded / offline
    capabilities: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    backoff_until: float = 0.0

    def is_alive(self, timeout: float = 30.0) -> bool:
        return (time.time() - self.last_heartbeat) < timeout

    def to_dict(self) -> Dict:
        return {
            "instance_id": self.instance_id,
            "url": self.url,
            "name": self.name,
            "last_heartbeat": self.last_heartbeat,
            "status": self.status,
            "capabilities": self.capabilities,
            "latency_ms": self.latency_ms,
            "alive": self.is_alive(),
        }


# ============================================================================
# 主类
# ============================================================================

class GalaxyFederation:
    """
    Galaxy 联邦协作管理器

    - 维护本实例信息
    - 定期向所有配置的 peers 发送心跳
    - 提供远程任务转发接口
    """

    def __init__(self):
        self.instance_id: str = os.environ.get(
            "FEDERATION_INSTANCE_ID", str(uuid.uuid4())[:12]
        )
        self.local_url: str = _local_gateway_url()
        self._peers: Dict[str, PeerInstance] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval: float = float(
            os.environ.get("FEDERATION_HEARTBEAT_INTERVAL", "15")
        )
        self._running = False
        self._offline_threshold: int = int(
            os.environ.get("FEDERATION_OFFLINE_THRESHOLD", "3")
        )

        # 从环境变量预注册 peers
        for url in _federation_peers():
            peer_id = f"peer_{url.replace('http://', '').replace('https://', '').replace(':', '_').replace('/', '_')}"
            self._peers[peer_id] = PeerInstance(
                instance_id=peer_id, url=url, status="unknown"
            )

    # ================================================================
    # 生命周期
    # ================================================================

    async def start(self) -> None:
        """启动联邦服务（心跳循环）"""
        if not _federation_enabled():
            logger.info("Federation is disabled (set FEDERATION_ENABLED=true to enable)")
            return
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            f"Galaxy Federation started: instance_id={self.instance_id}, "
            f"peers={list(self._peers.keys())}"
        )

    async def stop(self) -> None:
        """停止联邦服务"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("Galaxy Federation stopped")

    # ================================================================
    # Peer 管理
    # ================================================================

    def register_peer(self, url: str, instance_id: str = "", name: str = "") -> PeerInstance:
        """手动注册一个 peer"""
        pid = instance_id or f"peer_{url.replace('://', '_').replace(':', '_').replace('/', '_')}"
        peer = PeerInstance(instance_id=pid, url=url, name=name, status="unknown")
        self._peers[pid] = peer
        logger.info(f"Peer registered: {pid} @ {url}")
        return peer

    def unregister_peer(self, instance_id: str) -> bool:
        """注销 peer"""
        if instance_id in self._peers:
            del self._peers[instance_id]
            return True
        return False

    def list_peers(self) -> List[Dict]:
        """列出所有已知 peer"""
        return [p.to_dict() for p in self._peers.values()]

    def get_peer(self, instance_id: str) -> Optional[PeerInstance]:
        return self._peers.get(instance_id)

    def cleanup_stale_peers(self, max_age: int = 60) -> int:
        """移除 last_heartbeat 超过 max_age 秒的 stale peers，返回移除数量"""
        cutoff = time.time() - max_age
        stale = [pid for pid, p in self._peers.items() if p.last_heartbeat < cutoff]
        for pid in stale:
            del self._peers[pid]
            logger.info(f"Stale peer removed: {pid}")
        return len(stale)

    # ================================================================
    # 心跳
    # ================================================================

    async def _heartbeat_loop(self) -> None:
        """定期向所有 peers 发送心跳"""
        while self._running:
            await self._send_heartbeats()
            await asyncio.sleep(self._heartbeat_interval)

    async def _send_heartbeats(self) -> None:
        """向所有 peers 发送一轮心跳"""
        if not _AIOHTTP_AVAILABLE:
            logger.debug("aiohttp not available, skipping heartbeat")
            return

        payload = {
            "instance_id": self.instance_id,
            "url": self.local_url,
            "timestamp": time.time(),
        }

        now = time.time()
        for peer in list(self._peers.values()):
            if peer.backoff_until > now:
                logger.debug(f"Skipping heartbeat to {peer.url} (backoff until {peer.backoff_until:.1f})")
                continue
            asyncio.create_task(self._ping_peer(peer, payload))

    async def _ping_peer(self, peer: PeerInstance, payload: Dict) -> None:
        """向单个 peer 发送心跳"""
        t0 = time.time()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.post(
                    f"{peer.url}/api/v1/federation/heartbeat",
                    json=payload,
                ) as resp:
                    peer.latency_ms = round((time.time() - t0) * 1000, 1)
                    if resp.status == 200:
                        data = await resp.json()
                        peer.status = data.get("status", "healthy")
                    else:
                        peer.status = "degraded"
                    peer.last_heartbeat = time.time()
                    peer.consecutive_failures = 0
                    peer.backoff_until = 0.0
        except Exception as e:
            peer.consecutive_failures += 1
            if peer.consecutive_failures >= self._offline_threshold:
                peer.status = "offline"
            else:
                peer.status = "degraded"
            backoff_secs = min(2 ** min(peer.consecutive_failures, 10) * 5, 120)
            peer.backoff_until = time.time() + backoff_secs
            logger.debug(
                f"Heartbeat to {peer.url} failed "
                f"(consecutive={peer.consecutive_failures}, backoff={backoff_secs}s): {e}"
            )

    # ================================================================
    # 任务转发
    # ================================================================

    async def forward_task(
        self,
        target_url_or_id: str,
        task: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """
        向远程 peer 转发任务

        Args:
            target_url_or_id: peer 的 URL 或 instance_id
            task: 任务字典 {"command": ..., "params": ..., ...}
            timeout: 超时秒数

        Returns:
            远程响应字典
        """
        if not _AIOHTTP_AVAILABLE:
            return {"success": False, "error": "aiohttp not installed", "error_type": "MissingDependency", "target": target_url_or_id}

        # 解析目标
        if target_url_or_id.startswith("http"):
            url = target_url_or_id
        else:
            peer = self._peers.get(target_url_or_id)
            if not peer:
                return {"success": False, "error": f"Unknown peer: {target_url_or_id}", "error_type": "UnknownPeer", "target": target_url_or_id}
            url = peer.url

        payload = {
            "from_instance": self.instance_id,
            "task": task,
            "timestamp": time.time(),
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.post(
                    f"{url}/api/v1/federation/task",
                    json=payload,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}: {text}",
                            "error_type": "HTTPError",
                            "target": url,
                        }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "target": url,
            }

    # ================================================================
    # 接收端（处理来自其他实例的心跳/任务）
    # ================================================================

    def receive_heartbeat(self, data: Dict) -> Dict:
        """处理来自其他实例的心跳"""
        instance_id = data.get("instance_id", "")
        url = data.get("url", "")
        if not instance_id:
            return {"status": "error", "error": "missing instance_id"}

        if instance_id not in self._peers:
            self._peers[instance_id] = PeerInstance(
                instance_id=instance_id, url=url, status="healthy"
            )
        else:
            self._peers[instance_id].last_heartbeat = time.time()
            self._peers[instance_id].status = "healthy"
            if url:
                self._peers[instance_id].url = url

        return {
            "status": "ok",
            "instance_id": self.instance_id,
            "timestamp": time.time(),
        }

    def local_info(self) -> Dict:
        """返回本实例的公开信息"""
        return {
            "instance_id": self.instance_id,
            "url": self.local_url,
            "enabled": _federation_enabled(),
            "peers_count": len(self._peers),
            "peers": self.list_peers(),
        }


# ============================================================================
# 单例
# ============================================================================

_federation_instance: Optional[GalaxyFederation] = None


def get_federation() -> GalaxyFederation:
    global _federation_instance
    if _federation_instance is None:
        _federation_instance = GalaxyFederation()
    return _federation_instance
