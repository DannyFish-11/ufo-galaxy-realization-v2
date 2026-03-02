"""
Node 71 - State Synchronizer Module
状态同步模块，实现向量时钟和 Gossip 协议
"""
import asyncio
import json
import logging
import time
import hashlib
from typing import Dict, List, Optional, Any, Callable, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
import random

from models.device import Device, DeviceState, VectorClock

logger = logging.getLogger(__name__)


class SyncEventType(str, Enum):
    """同步事件类型"""
    STATE_UPDATED = "state_updated"
    STATE_CONFLICT = "state_conflict"
    STATE_MERGED = "state_merged"
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    ERROR = "error"


class ConflictResolution(str, Enum):
    """冲突解决策略"""
    LAST_WRITE_WINS = "last_write_wins"     # 最后写入胜出
    FIRST_WRITE_WINS = "first_write_wins"   # 最先写入胜出
    MERGE = "merge"                          # 合并策略
    HIGHEST_PRIORITY = "highest_priority"   # 最高优先级胜出
    MANUAL = "manual"                        # 人工干预


@dataclass
class StateEvent:
    """状态事件"""
    event_id: str
    event_type: str
    device_id: str
    timestamp: float
    vector_clock: VectorClock
    data: Dict[str, Any]
    source_node: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "vector_clock": self.vector_clock.to_dict(),
            "data": self.data,
            "source_node": self.source_node
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateEvent":
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            device_id=data["device_id"],
            timestamp=data["timestamp"],
            vector_clock=VectorClock.from_dict(data["vector_clock"]),
            data=data["data"],
            source_node=data.get("source_node", "")
        )


@dataclass
class SyncConfig:
    """同步配置"""
    # Gossip 配置
    gossip_interval: float = 5.0            # Gossip 间隔(秒)
    gossip_fanout: int = 3                  # 每次传播的节点数
    gossip_max_hops: int = 10               # 最大跳数
    
    # 状态配置
    state_ttl: float = 3600.0               # 状态过期时间(秒)
    max_events: int = 10000                 # 最大事件数
    snapshot_interval: float = 300.0        # 快照间隔(秒)
    
    # 冲突解决
    conflict_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS
    
    # 心跳
    heartbeat_interval: float = 10.0        # 心跳间隔(秒)
    heartbeat_timeout: float = 60.0         # 心跳超时(秒)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gossip_interval": self.gossip_interval,
            "gossip_fanout": self.gossip_fanout,
            "gossip_max_hops": self.gossip_max_hops,
            "state_ttl": self.state_ttl,
            "max_events": self.max_events,
            "snapshot_interval": self.snapshot_interval,
            "conflict_resolution": self.conflict_resolution.value,
            "heartbeat_interval": self.heartbeat_interval,
            "heartbeat_timeout": self.heartbeat_timeout
        }


@dataclass
class StateSnapshot:
    """状态快照"""
    snapshot_id: str
    timestamp: float
    states: Dict[str, Dict[str, Any]]       # device_id -> state
    vector_clock: VectorClock
    checksum: str = ""
    
    def compute_checksum(self) -> str:
        """计算校验和"""
        data = json.dumps({
            "states": self.states,
            "vector_clock": self.vector_clock.to_dict()
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "states": self.states,
            "vector_clock": self.vector_clock.to_dict(),
            "checksum": self.checksum
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateSnapshot":
        snapshot = cls(
            snapshot_id=data["snapshot_id"],
            timestamp=data["timestamp"],
            states=data["states"],
            vector_clock=VectorClock.from_dict(data["vector_clock"]),
            checksum=data.get("checksum", "")
        )
        if not snapshot.checksum:
            snapshot.checksum = snapshot.compute_checksum()
        return snapshot


class ConflictResolver:
    """冲突解决器"""
    
    def __init__(self, strategy: ConflictResolution = ConflictResolution.LAST_WRITE_WINS):
        self.strategy = strategy
    
    def resolve(self, local: StateEvent, remote: StateEvent) -> StateEvent:
        """解决冲突"""
        if self.strategy == ConflictResolution.LAST_WRITE_WINS:
            return self._last_write_wins(local, remote)
        elif self.strategy == ConflictResolution.FIRST_WRITE_WINS:
            return self._first_write_wins(local, remote)
        elif self.strategy == ConflictResolution.MERGE:
            return self._merge(local, remote)
        elif self.strategy == ConflictResolution.HIGHEST_PRIORITY:
            return self._highest_priority(local, remote)
        else:
            return self._last_write_wins(local, remote)
    
    def _last_write_wins(self, local: StateEvent, remote: StateEvent) -> StateEvent:
        """最后写入胜出"""
        if remote.timestamp > local.timestamp:
            return remote
        return local
    
    def _first_write_wins(self, local: StateEvent, remote: StateEvent) -> StateEvent:
        """最先写入胜出"""
        if remote.timestamp < local.timestamp:
            return remote
        return local
    
    def _merge(self, local: StateEvent, remote: StateEvent) -> StateEvent:
        """合并策略"""
        merged_data = {**local.data, **remote.data}
        
        return StateEvent(
            event_id=f"merged-{time.time()}",
            event_type="merged",
            device_id=local.device_id,
            timestamp=max(local.timestamp, remote.timestamp),
            vector_clock=local.vector_clock.copy().update(remote.vector_clock),
            data=merged_data,
            source_node=local.source_node
        )
    
    def _highest_priority(self, local: StateEvent, remote: StateEvent) -> StateEvent:
        """最高优先级胜出"""
        local_priority = local.data.get("priority", 5)
        remote_priority = remote.data.get("priority", 5)
        
        if remote_priority < local_priority:
            return remote
        return local


class GossipProtocol:
    """
    Gossip 协议实现
    用于状态传播
    """
    
    def __init__(self, config: SyncConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self._peers: Dict[str, str] = {}         # node_id -> address
        self._pending_messages: List[Dict] = []
        self._seen_messages: Set[str] = set()
        self._event_handlers: List[Callable] = []
        
    def add_peer(self, node_id: str, address: str) -> None:
        """添加对等节点"""
        self._peers[node_id] = address
    
    def remove_peer(self, node_id: str) -> None:
        """移除对等节点"""
        self._peers.pop(node_id, None)
    
    def add_event_handler(self, handler: Callable) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def create_gossip_message(self, event: StateEvent, hop_count: int = 0) -> Dict:
        """创建 Gossip 消息"""
        return {
            "type": "gossip",
            "message_id": event.event_id,
            "source_node": self.node_id,
            "hop_count": hop_count,
            "max_hops": self.config.gossip_max_hops,
            "event": event.to_dict(),
            "timestamp": time.time()
        }
    
    def should_propagate(self, message: Dict) -> bool:
        """判断是否应该传播"""
        message_id = message.get("message_id")
        hop_count = message.get("hop_count", 0)
        max_hops = message.get("max_hops", self.config.gossip_max_hops)
        
        # 检查是否已见过
        if message_id in self._seen_messages:
            return False
        
        # 检查跳数
        if hop_count >= max_hops:
            return False
        
        return True
    
    def select_peers(self) -> List[str]:
        """选择传播目标"""
        peers = list(self._peers.keys())
        fanout = min(self.config.gossip_fanout, len(peers))
        
        if fanout >= len(peers):
            return peers
        
        return random.sample(peers, fanout)
    
    def mark_seen(self, message_id: str) -> None:
        """标记消息已见"""
        self._seen_messages.add(message_id)
        
        # 清理过期的已见消息
        if len(self._seen_messages) > 10000:
            # 简单清理：保留最近的一半
            self._seen_messages = set(list(self._seen_messages)[-5000:])
    
    async def broadcast(self, event: StateEvent) -> List[str]:
        """广播事件"""
        message = self.create_gossip_message(event)
        self.mark_seen(event.event_id)
        
        targets = self.select_peers()
        
        for handler in self._event_handlers:
            try:
                await handler("broadcast", message, targets)
            except Exception as e:
                logger.error(f"Broadcast handler error: {e}")
        
        return targets
    
    async def handle_message(self, message: Dict) -> Optional[StateEvent]:
        """处理接收到的消息"""
        if not self.should_propagate(message):
            return None
        
        message_id = message.get("message_id")
        self.mark_seen(message_id)
        
        event_data = message.get("event")
        if not event_data:
            return None
        
        event = StateEvent.from_dict(event_data)
        
        # 通知处理器
        for handler in self._event_handlers:
            try:
                await handler("receive", message, event)
            except Exception as e:
                logger.error(f"Message handler error: {e}")
        
        # 继续传播
        if message.get("hop_count", 0) < self.config.gossip_max_hops - 1:
            new_message = message.copy()
            new_message["hop_count"] = message.get("hop_count", 0) + 1
            new_message["source_node"] = self.node_id
            
            targets = self.select_peers()
            for handler in self._event_handlers:
                try:
                    await handler("propagate", new_message, targets)
                except Exception as e:
                    logger.error(f"Propagate handler error: {e}")
        
        return event


class StateSynchronizer:
    """
    状态同步器
    管理设备状态的同步和一致性
    """
    
    def __init__(self, config: SyncConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        
        # 状态存储
        self._device_states: Dict[str, Dict[str, Any]] = {}     # device_id -> state
        self._vector_clocks: Dict[str, VectorClock] = {}        # device_id -> vector_clock
        self._event_history: List[StateEvent] = []
        
        # 冲突解决
        self._conflict_resolver = ConflictResolver(config.conflict_resolution)
        
        # Gossip 协议
        self._gossip = GossipProtocol(config, node_id)
        self._gossip.add_event_handler(self._handle_gossip_event)
        
        # 快照
        self._snapshots: List[StateSnapshot] = []
        self._current_snapshot: Optional[StateSnapshot] = None
        
        # 事件处理器
        self._event_handlers: List[Callable[[str, Dict], None]] = []
        
        # 运行状态
        self._running = False
        self._sync_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 本地向量时钟
        self._local_clock = VectorClock(node_id=node_id)
    
    def add_event_handler(self, handler: Callable[[str, Dict], None]) -> None:
        """添加事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event_type: str, data: Dict) -> None:
        """发送事件"""
        for handler in self._event_handlers:
            try:
                handler(event_type, data)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def _handle_gossip_event(self, action: str, message: Dict, extra: Any) -> None:
        """处理 Gossip 事件"""
        if action == "receive":
            event = extra
            if event:
                await self._apply_remote_event(event)
        elif action in ("broadcast", "propagate"):
            # 这里应该通过网络发送消息
            # 实际实现中需要集成通信层
            pass
    
    async def start(self) -> bool:
        """启动状态同步器"""
        if self._running:
            return True
        
        self._running = True
        
        # 启动同步任务
        self._sync_task = asyncio.create_task(self._sync_loop())
        
        # 启动快照任务
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("State synchronizer started")
        self._emit_event(SyncEventType.SYNC_STARTED, {"node_id": self.node_id})
        
        return True
    
    async def stop(self) -> None:
        """停止状态同步器"""
        self._running = False
        
        for task in [self._sync_task, self._snapshot_task, self._cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("State synchronizer stopped")
        self._emit_event(SyncEventType.SYNC_COMPLETED, {"node_id": self.node_id})
    
    async def _sync_loop(self) -> None:
        """同步循环"""
        while self._running:
            try:
                # 执行增量同步
                await self._incremental_sync()
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
            
            await asyncio.sleep(self.config.gossip_interval)
    
    async def _incremental_sync(self) -> None:
        """增量同步"""
        # 获取最近的事件
        recent_events = self._event_history[-100:] if self._event_history else []
        
        for event in recent_events:
            await self._gossip.broadcast(event)
    
    async def _snapshot_loop(self) -> None:
        """快照循环"""
        while self._running:
            try:
                await self._create_snapshot()
            except Exception as e:
                logger.error(f"Snapshot loop error: {e}")
            
            await asyncio.sleep(self.config.snapshot_interval)
    
    async def _create_snapshot(self) -> StateSnapshot:
        """创建快照"""
        snapshot = StateSnapshot(
            snapshot_id=f"snapshot-{time.time()}",
            timestamp=time.time(),
            states=dict(self._device_states),
            vector_clock=self._local_clock.copy()
        )
        snapshot.checksum = snapshot.compute_checksum()
        
        self._snapshots.append(snapshot)
        self._current_snapshot = snapshot
        
        # 保留最近的快照
        if len(self._snapshots) > 10:
            self._snapshots = self._snapshots[-10:]
        
        logger.debug(f"Created snapshot: {snapshot.snapshot_id}")
        return snapshot
    
    async def _cleanup_loop(self) -> None:
        """清理循环"""
        while self._running:
            try:
                current_time = time.time()
                
                # 清理过期状态
                expired = []
                for device_id, state in self._device_states.items():
                    if current_time - state.get("updated_at", 0) > self.config.state_ttl:
                        expired.append(device_id)
                
                for device_id in expired:
                    del self._device_states[device_id]
                    self._vector_clocks.pop(device_id, None)
                    logger.debug(f"Cleaned up expired state: {device_id}")
                
                # 清理事件历史
                if len(self._event_history) > self.config.max_events:
                    self._event_history = self._event_history[-self.config.max_events:]
                
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
            
            await asyncio.sleep(60)
    
    async def update_state(self, device_id: str, state: Dict[str, Any]) -> StateEvent:
        """更新设备状态"""
        # 递增向量时钟
        self._local_clock.increment()
        
        # 创建状态事件
        event = StateEvent(
            event_id=f"event-{time.time()}-{device_id}",
            event_type="state_update",
            device_id=device_id,
            timestamp=time.time(),
            vector_clock=self._local_clock.copy(),
            data=state,
            source_node=self.node_id
        )
        
        # 更新本地状态
        self._device_states[device_id] = {
            **state,
            "updated_at": time.time(),
            "updated_by": self.node_id
        }
        
        # 更新向量时钟
        if device_id not in self._vector_clocks:
            self._vector_clocks[device_id] = VectorClock(node_id=self.node_id)
        self._vector_clocks[device_id].update(self._local_clock)
        
        # 记录事件
        self._event_history.append(event)
        
        # 广播更新
        await self._gossip.broadcast(event)
        
        # 发送事件
        self._emit_event(SyncEventType.STATE_UPDATED, {
            "device_id": device_id,
            "state": state,
            "event": event.to_dict()
        })
        
        return event
    
    async def _apply_remote_event(self, event: StateEvent) -> bool:
        """应用远程事件"""
        device_id = event.device_id
        
        # 检查是否需要处理
        local_clock = self._vector_clocks.get(device_id)
        
        if local_clock:
            # 比较向量时钟
            comparison = local_clock.compare(event.vector_clock)
            
            if comparison == 1:
                # 本地更新，忽略远程
                return False
            elif comparison == 0:
                # 并发事件，需要解决冲突
                local_event = self._find_event_for_device(device_id)
                if local_event:
                    event = self._conflict_resolver.resolve(local_event, event)
                    self._emit_event(SyncEventType.STATE_CONFLICT, {
                        "device_id": device_id,
                        "local_event": local_event.to_dict(),
                        "remote_event": event.to_dict(),
                        "resolution": self.config.conflict_resolution.value
                    })
        
        # 应用状态
        self._device_states[device_id] = {
            **event.data,
            "updated_at": event.timestamp,
            "updated_by": event.source_node
        }
        
        # 更新向量时钟
        if device_id not in self._vector_clocks:
            self._vector_clocks[device_id] = VectorClock(node_id=self.node_id)
        self._vector_clocks[device_id].update(event.vector_clock)
        
        # 更新本地时钟
        self._local_clock.update(event.vector_clock)
        
        # 记录事件
        self._event_history.append(event)
        
        self._emit_event(SyncEventType.STATE_UPDATED, {
            "device_id": device_id,
            "state": event.data,
            "source": "remote"
        })
        
        return True
    
    def _find_event_for_device(self, device_id: str) -> Optional[StateEvent]:
        """查找设备的最近事件"""
        for event in reversed(self._event_history):
            if event.device_id == device_id:
                return event
        return None
    
    def get_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备状态"""
        return self._device_states.get(device_id)
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有状态"""
        return dict(self._device_states)
    
    def get_vector_clock(self, device_id: str) -> Optional[VectorClock]:
        """获取设备的向量时钟"""
        return self._vector_clocks.get(device_id)
    
    def get_event_history(self, device_id: Optional[str] = None, limit: int = 100) -> List[StateEvent]:
        """获取事件历史"""
        events = self._event_history
        
        if device_id:
            events = [e for e in events if e.device_id == device_id]
        
        return events[-limit:]
    
    def get_latest_snapshot(self) -> Optional[StateSnapshot]:
        """获取最新快照"""
        return self._current_snapshot
    
    def get_snapshots(self) -> List[StateSnapshot]:
        """获取所有快照"""
        return list(self._snapshots)
    
    async def restore_from_snapshot(self, snapshot: StateSnapshot) -> bool:
        """从快照恢复"""
        try:
            self._device_states = dict(snapshot.states)
            self._local_clock = snapshot.vector_clock.copy()
            
            logger.info(f"Restored from snapshot: {snapshot.snapshot_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore from snapshot: {e}")
            return False
    
    def add_peer(self, node_id: str, address: str) -> None:
        """添加对等节点"""
        self._gossip.add_peer(node_id, address)
    
    def remove_peer(self, node_id: str) -> None:
        """移除对等节点"""
        self._gossip.remove_peer(node_id)
    
    def get_peers(self) -> Dict[str, str]:
        """获取所有对等节点"""
        return dict(self._gossip._peers)
    
    async def handle_gossip_message(self, message: Dict) -> Optional[StateEvent]:
        """处理 Gossip 消息"""
        return await self._gossip.handle_message(message)
    
    def get_sync_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        return {
            "node_id": self.node_id,
            "device_count": len(self._device_states),
            "event_count": len(self._event_history),
            "snapshot_count": len(self._snapshots),
            "peer_count": len(self._gossip._peers),
            "vector_clock": self._local_clock.to_dict(),
            "running": self._running
        }
