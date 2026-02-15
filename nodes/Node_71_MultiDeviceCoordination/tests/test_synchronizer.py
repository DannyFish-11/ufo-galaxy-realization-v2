"""
Node 71 - State Synchronizer Tests
状态同步器单元测试
"""
import asyncio
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import VectorClock
from core.state_synchronizer import (
    StateSynchronizer, SyncConfig, StateEvent, SyncEventType,
    ConflictResolution, ConflictResolver, GossipProtocol,
    StateSnapshot
)


class TestSyncConfig:
    """同步配置测试"""

    def test_defaults(self):
        config = SyncConfig()
        assert config.gossip_interval == 5.0
        assert config.gossip_fanout == 3
        assert config.gossip_max_hops == 10
        assert config.conflict_resolution == ConflictResolution.LAST_WRITE_WINS

    def test_to_dict(self):
        config = SyncConfig()
        data = config.to_dict()
        assert "gossip_interval" in data
        assert "conflict_resolution" in data


class TestConflictResolver:
    """冲突解决器测试"""

    @pytest.fixture
    def local_event(self):
        return StateEvent(
            event_id="local-1",
            event_type="state_update",
            device_id="dev-1",
            timestamp=100.0,
            vector_clock=VectorClock(clock={"A": 1}),
            data={"temperature": 25.0, "priority": 3},
            source_node="A"
        )

    @pytest.fixture
    def remote_event(self):
        return StateEvent(
            event_id="remote-1",
            event_type="state_update",
            device_id="dev-1",
            timestamp=200.0,
            vector_clock=VectorClock(clock={"B": 1}),
            data={"temperature": 30.0, "humidity": 60.0, "priority": 1},
            source_node="B"
        )

    def test_last_write_wins(self, local_event, remote_event):
        resolver = ConflictResolver(ConflictResolution.LAST_WRITE_WINS)
        result = resolver.resolve(local_event, remote_event)
        assert result.timestamp == 200.0  # remote wins

    def test_first_write_wins(self, local_event, remote_event):
        resolver = ConflictResolver(ConflictResolution.FIRST_WRITE_WINS)
        result = resolver.resolve(local_event, remote_event)
        assert result.timestamp == 100.0  # local wins

    def test_merge(self, local_event, remote_event):
        resolver = ConflictResolver(ConflictResolution.MERGE)
        result = resolver.resolve(local_event, remote_event)
        assert "temperature" in result.data
        assert "humidity" in result.data

    def test_highest_priority(self, local_event, remote_event):
        resolver = ConflictResolver(ConflictResolution.HIGHEST_PRIORITY)
        result = resolver.resolve(local_event, remote_event)
        # remote has priority=1 (lower is higher), so remote wins
        assert result.data["priority"] == 1


class TestGossipProtocol:
    """Gossip 协议测试"""

    @pytest.fixture
    def gossip(self):
        config = SyncConfig(gossip_fanout=2, gossip_max_hops=3)
        return GossipProtocol(config, "node-1")

    def test_add_remove_peer(self, gossip):
        gossip.add_peer("node-2", "192.168.1.2:8071")
        assert "node-2" in gossip._peers

        gossip.remove_peer("node-2")
        assert "node-2" not in gossip._peers

    def test_create_gossip_message(self, gossip):
        event = StateEvent(
            event_id="evt-1",
            event_type="update",
            device_id="dev-1",
            timestamp=time.time(),
            vector_clock=VectorClock(node_id="node-1"),
            data={"state": "online"}
        )

        message = gossip.create_gossip_message(event)
        assert message["type"] == "gossip"
        assert message["source_node"] == "node-1"
        assert message["hop_count"] == 0

    def test_should_propagate_new(self, gossip):
        message = {"message_id": "msg-1", "hop_count": 0}
        assert gossip.should_propagate(message) is True

    def test_should_not_propagate_seen(self, gossip):
        gossip.mark_seen("msg-1")
        message = {"message_id": "msg-1", "hop_count": 0}
        assert gossip.should_propagate(message) is False

    def test_should_not_propagate_max_hops(self, gossip):
        message = {"message_id": "msg-1", "hop_count": 3}  # max_hops=3
        assert gossip.should_propagate(message) is False

    def test_select_peers(self, gossip):
        for i in range(5):
            gossip.add_peer(f"node-{i}", f"192.168.1.{i}:8071")

        peers = gossip.select_peers()
        assert len(peers) == 2  # fanout=2

    def test_mark_seen_cleanup(self, gossip):
        for i in range(11000):
            gossip.mark_seen(f"msg-{i}")
        # 清理后应该只保留最近的一半
        assert len(gossip._seen_messages) <= 10000


class TestStateSnapshot:
    """状态快照测试"""

    def test_creation(self):
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            timestamp=time.time(),
            states={"dev-1": {"state": "online"}},
            vector_clock=VectorClock(node_id="node-1")
        )
        assert snapshot.snapshot_id == "snap-1"

    def test_checksum(self):
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            timestamp=time.time(),
            states={"dev-1": {"state": "online"}},
            vector_clock=VectorClock(node_id="node-1")
        )
        checksum = snapshot.compute_checksum()
        assert len(checksum) == 64  # SHA-256

    def test_serialization(self):
        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            timestamp=time.time(),
            states={"dev-1": {"state": "online"}},
            vector_clock=VectorClock(node_id="node-1")
        )
        snapshot.checksum = snapshot.compute_checksum()

        data = snapshot.to_dict()
        restored = StateSnapshot.from_dict(data)
        assert restored.snapshot_id == "snap-1"
        assert restored.checksum == snapshot.checksum


class TestStateSynchronizer:
    """状态同步器测试"""

    @pytest.fixture
    def sync_config(self):
        return SyncConfig(
            gossip_interval=0.5,
            snapshot_interval=1.0,
            state_ttl=60.0
        )

    @pytest.fixture
    def synchronizer(self, sync_config):
        return StateSynchronizer(sync_config, "test-node")

    @pytest.mark.asyncio
    async def test_start_stop(self, synchronizer):
        """测试启动和停止"""
        success = await synchronizer.start()
        assert success is True
        assert synchronizer._running is True

        await synchronizer.stop()
        assert synchronizer._running is False

    @pytest.mark.asyncio
    async def test_update_state(self, synchronizer):
        """测试更新状态"""
        await synchronizer.start()

        event = await synchronizer.update_state("dev-1", {"state": "online", "temp": 25.0})
        assert event is not None
        assert event.device_id == "dev-1"

        state = synchronizer.get_state("dev-1")
        assert state is not None
        assert state["state"] == "online"

        await synchronizer.stop()

    @pytest.mark.asyncio
    async def test_multiple_updates(self, synchronizer):
        """测试多次更新"""
        await synchronizer.start()

        await synchronizer.update_state("dev-1", {"state": "online"})
        await synchronizer.update_state("dev-1", {"state": "busy"})

        state = synchronizer.get_state("dev-1")
        assert state["state"] == "busy"

        await synchronizer.stop()

    @pytest.mark.asyncio
    async def test_get_all_states(self, synchronizer):
        """测试获取所有状态"""
        await synchronizer.start()

        await synchronizer.update_state("dev-1", {"state": "online"})
        await synchronizer.update_state("dev-2", {"state": "idle"})

        states = synchronizer.get_all_states()
        assert "dev-1" in states
        assert "dev-2" in states

        await synchronizer.stop()

    @pytest.mark.asyncio
    async def test_event_history(self, synchronizer):
        """测试事件历史"""
        await synchronizer.start()

        await synchronizer.update_state("dev-1", {"state": "online"})
        await synchronizer.update_state("dev-1", {"state": "busy"})

        history = synchronizer.get_event_history("dev-1")
        assert len(history) == 2

        await synchronizer.stop()

    @pytest.mark.asyncio
    async def test_event_handler(self, synchronizer):
        """测试事件处理器"""
        events = []

        def handler(event_type, data):
            events.append((event_type, data))

        synchronizer.add_event_handler(handler)
        await synchronizer.start()

        await synchronizer.update_state("dev-1", {"state": "online"})

        # 等待事件传播
        await asyncio.sleep(0.1)

        # 应该收到 SYNC_STARTED 和 STATE_UPDATED 事件
        assert len(events) >= 2

        await synchronizer.stop()

    def test_add_remove_peer(self, synchronizer):
        """测试添加和移除对等节点"""
        synchronizer.add_peer("node-2", "192.168.1.2:8071")
        peers = synchronizer.get_peers()
        assert "node-2" in peers

        synchronizer.remove_peer("node-2")
        peers = synchronizer.get_peers()
        assert "node-2" not in peers

    def test_get_sync_status(self, synchronizer):
        """测试同步状态"""
        status = synchronizer.get_sync_status()
        assert "node_id" in status
        assert "device_count" in status
        assert "event_count" in status
        assert "running" in status


class TestStateEvent:
    """状态事件测试"""

    def test_creation(self):
        event = StateEvent(
            event_id="evt-1",
            event_type="state_update",
            device_id="dev-1",
            timestamp=time.time(),
            vector_clock=VectorClock(node_id="node-1"),
            data={"state": "online"}
        )
        assert event.event_id == "evt-1"

    def test_serialization(self):
        event = StateEvent(
            event_id="evt-1",
            event_type="state_update",
            device_id="dev-1",
            timestamp=time.time(),
            vector_clock=VectorClock(node_id="node-1"),
            data={"state": "online"},
            source_node="node-1"
        )

        data = event.to_dict()
        restored = StateEvent.from_dict(data)
        assert restored.event_id == event.event_id
        assert restored.device_id == event.device_id
        assert restored.source_node == "node-1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
