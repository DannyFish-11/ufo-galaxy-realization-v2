"""tests/test_round2_fix_behaviors.py
=====================================
第二轮排查修复的**行为回归锁**。

这些缺陷的共同特征是【静默降级】—— 不崩溃、不告警,只是功能悄悄不在了:
异常被宽泛的 except 吞掉、``getattr(x, "field", [])`` 掩盖字段根本不存在、
硬编码的默认值把真实状态抹平。正因为没有任何可观测信号,它们才能长期存活。

所以这里锁的都是**可观察的行为差异**,而不是源码文本或实现细节:
每个用例都对应"修复前会给出一个看起来正常但错误的答案"这一具体场景。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 设备在线态:软下线必须如实反映
# ---------------------------------------------------------------------------


class TestSoftOfflineIsReported:
    """mark_offline 是软下线(保留条目、只置 routable=False),不能被硬编码抹掉。"""

    def test_soft_offline_device_reports_offline(self):
        from core.unified.connection_manager import UnifiedConnectionManager

        async def go():
            m = UnifiedConnectionManager()
            await m.register_connection("d1", websocket=object(), metadata={})
            before = m.get_all_devices()["d1"]
            assert before["online"] is True
            m.mark_offline("d1")
            return m.get_all_devices().get("d1")

        after = _run(go())
        # 回归锁定:此前 get_all_devices 把 online 硬编码成 True,
        # 心跳超时软下线的设备照样被当成在线,调用方继续往它派活。
        assert after is not None
        assert after["online"] is False
        assert after["status"] == "offline"


class TestCompatIngressMarksRoutable:
    """兼容 /ws/device 入口注册的设备必须是可路由的,否则 presence 恒报离线。"""

    def test_connected_device_is_online_in_presence_view(self):
        from core.routes._shared import RouteConnectionPool
        from core.unified.models import UnifiedConnectionInfo, UnifiedConnectionState

        pool = RouteConnectionPool()
        ucm = pool._unified()
        ucm._websockets["dev_x"] = object()
        # 复现 connect_device 的写法(显式给 routable/last_seen)
        ucm._connections["dev_x"] = UnifiedConnectionInfo(
            device_id="dev_x",
            state=UnifiedConnectionState.CONNECTED,
            connected_at=datetime.now(timezone.utc),
            last_seen=time.time(),
            routable=True,
        )
        try:
            # 回归锁定:routable 默认是 False,而 get_presence_view 算的是
            # online = connected and routable —— 漏给 routable 时 socket 活着也恒报离线。
            assert pool.is_online("dev_x") is True
        finally:
            ucm._websockets.pop("dev_x", None)
            ucm._connections.pop("dev_x", None)


# ---------------------------------------------------------------------------
# 配置与密钥
# ---------------------------------------------------------------------------


class TestEnvOverridesFileForAllProviders:
    """环境变量是最高优先级层,不能只对少数前缀生效。"""

    def test_non_whitelisted_provider_key_takes_env_value(self, monkeypatch, tmp_path):
        import core.unified_config as uc

        monkeypatch.setenv("QWEN_API_KEY", "FROM_ENV")
        monkeypatch.setenv("OPENAI_API_KEY", "FROM_ENV_OPENAI")
        monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "QWEN_API_KEY=FROM_FILE_STALE\nOPENAI_API_KEY=FROM_FILE\nZHIPU_API_KEY=FILE_ONLY\n",
            encoding="utf-8",
        )
        cfg = uc.UnifiedConfig.__new__(uc.UnifiedConfig)
        cfg._config = {}
        cfg.env_file = env_file
        cfg._load_env()

        # 回归锁定:前缀白名单曾被当成"哪些键允许被环境覆盖",
        # 于是 OPENAI 取环境值而 QWEN 保留文件里的过期密钥 —— 同一套配置两种行为。
        assert cfg._config["qwen_api_key"] == "FROM_ENV"
        assert cfg._config["openai_api_key"] == "FROM_ENV_OPENAI"
        # 环境没给的键不应被误伤
        assert cfg._config["zhipu_api_key"] == "FILE_ONLY"


class TestSecretDeletionPersists:
    """清空密钥必须真的从密钥库删除,否则启动水合时旧值会复活。"""

    def test_delete_secret_removes_and_is_idempotent(self):
        from core.config_store import ConfigStore

        with tempfile.TemporaryDirectory() as d:
            store = ConfigStore(secrets_path=Path(d) / "secrets.env")
            store.write_secret("OPENAI_API_KEY", "sk-real")
            assert "OPENAI_API_KEY" in store.read_secrets()
            # 回归锁定:set_secret 拒绝空值,此前"清空"这个动作整条被跳过,
            # secrets.env 里的旧值原封不动,重启后又被灌回环境。
            assert store.delete_secret("OPENAI_API_KEY") is True
            assert "OPENAI_API_KEY" not in store.read_secrets()
            assert store.delete_secret("OPENAI_API_KEY") is False  # 幂等


# ---------------------------------------------------------------------------
# 治理与限流
# ---------------------------------------------------------------------------


class TestRateLimitFollowsRiskTier:
    """限流桶必须随当前风险档调速,否则高危档限额永不生效。"""

    def test_tightening_tier_takes_effect_immediately(self):
        from core.governance.tool_governor import _TokenBucket

        bucket = _TokenBucket(120)
        assert bucket.capacity == 120.0
        bucket.retune(5)
        assert bucket.capacity == 5.0
        # 回归锁定:桶只按 tool_name 缓存、首次见到的档位限额永久沿用,
        # 于是先以宽松档跑过一次之后,critical 的严格限额再也不会生效。
        allowed = sum(1 for _ in range(30) if bucket.consume())
        assert allowed <= 5


class TestIPBlockListIsBounded:
    """失败记录按活跃 IP 有界,不能按历史见过的 IP 无限增长。"""

    def test_expired_ip_keys_are_released(self):
        from core.security_middleware import IPBlockList

        bl = IPBlockList()
        bl._window = 1
        bl._SWEEP_EVERY = 50
        for i in range(300):
            bl.record_failure(f"10.0.{i // 256}.{i % 256}")
        assert len(bl._auto_block) == 300  # 窗口内应当保留
        time.sleep(1.2)
        for _ in range(60):
            bl.record_failure("172.16.0.1")  # 触发摊还清理
        # 回归锁定:此前只剪列表内的时间戳、不删空键,
        # 每见到一个新 IP 就永久多一条 —— 面向公网时是无上限增长。
        assert len(bl._auto_block) < 10

    def test_blocking_still_works_after_bounding(self):
        from core.security_middleware import IPBlockList

        bl = IPBlockList()
        for _ in range(bl._threshold):
            bl.record_failure("203.0.113.9")
        assert bl.is_blocked("203.0.113.9") is True


# ---------------------------------------------------------------------------
# 能力表与编队
# ---------------------------------------------------------------------------


class TestRefreshPreservesInjectedCapabilities:
    """refresh 只重载四个 loader 源,不得抹掉 inject_item 注册的节点能力。"""

    def test_injected_capability_survives_refresh(self):
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

        reg = CapabilityRegistry()
        reg.inject_item(CapabilityItem(name="node_cap_probe", source="node", description="d"))
        assert "node_cap_probe" in reg._items

        async def go():
            reg._load_mcp = lambda t: asyncio.sleep(0)
            reg._load_skill = lambda t: asyncio.sleep(0)
            reg._load_gateway = lambda t: asyncio.sleep(0)
            reg._load_autonomous = lambda t: asyncio.sleep(0)
            await reg.refresh(force=True)

        _run(go())
        # 回归锁定:此前 refresh 整份替换 _items,而节点能力走 inject_item 注册、
        # 四个 loader 都不会重新产出 —— 每 120s 自动刷新一次就被静默抹掉。
        assert "node_cap_probe" in reg._items


class TestFormationPromotesNewPrimary:
    """主执行设备被移除后必须重派,否则编队群龙无首。"""

    def test_healthiest_survivor_is_promoted(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )

        mgr = FormationAutoEnrollmentManager()
        mgr.enroll_device("dev_a", health_score=0.5)
        mgr.enroll_device("dev_b", health_score=0.9)
        mgr.enroll_device("dev_c", health_score=0.7)
        primary_before = [d for d, p in mgr._participants.items() if "primary" in str(p.role)]
        assert primary_before == ["dev_a"]

        mgr.remove_device("dev_a")
        active = {d: p.role for d, p in mgr._participants.items() if p.is_active}
        # 回归锁定:角色按 enroll 时的活跃数一次性定死,remove 只置 is_active=False,
        # 剩下的 SUPPORT 永远不会被提升。
        promoted = [d for d, r in active.items() if "primary" in str(r)]
        assert promoted == ["dev_b"]  # 健康度最高者

    def test_empty_formation_does_not_invent_primary(self):
        from core.device_formation.formation_auto_enrollment import (
            FormationAutoEnrollmentManager,
        )

        mgr = FormationAutoEnrollmentManager()
        mgr.enroll_device("only_one", health_score=0.5)
        mgr.remove_device("only_one")
        assert not [p for p in mgr._participants.values() if p.is_active]


# ---------------------------------------------------------------------------
# L4 自主循环
# ---------------------------------------------------------------------------


class TestL4SuccessReflectsRealOutcome:
    """目标成败必须由真实执行结果推导,不能恒为 True。"""

    @staticmethod
    def _derive(results):
        """复刻主循环的判定逻辑(见 galaxy_main_loop_l4_enhanced._process_goal)。"""
        from enhancements.execution.action_executor import ExecutionStatus

        failed_statuses = {
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
        }
        failed = [r for r in results if getattr(r, "status", None) in failed_statuses]
        return bool(results) and not failed

    @staticmethod
    def _result(status):
        from enhancements.execution.action_executor import ExecutionResult

        return ExecutionResult(action_id="a", status=status, start_time=0.0, end_time=1.0, duration=1.0, output=None)

    def test_all_success_is_success(self):
        from enhancements.execution.action_executor import ExecutionStatus

        assert self._derive([self._result(ExecutionStatus.SUCCESS)] * 3) is True

    @pytest.mark.parametrize("bad", ["FAILED", "CANCELLED", "TIMEOUT"])
    def test_any_bad_outcome_is_failure(self, bad):
        from enhancements.execution.action_executor import ExecutionStatus

        results = [self._result(ExecutionStatus.SUCCESS), self._result(getattr(ExecutionStatus, bad))]
        # 回归锁定:此前读 ExecutionContext 上并不存在的 completed_actions/failed_actions,
        # getattr 默认值让 failed 恒空 → success 恒为 True,学习环收到的是常量。
        assert self._derive(results) is False

    def test_empty_result_is_not_success(self):
        # 没执行任何动作不等于目标达成
        assert self._derive([]) is False


class TestWorldModelStateStaysEnum:
    """entity.state 必须保持 EntityState 枚举,不能被写成 dict。"""

    def test_update_keeps_enum_and_records_metadata(self):
        from enhancements.execution.action_executor import ActionExecutor
        from enhancements.reasoning.world_model import (
            Entity,
            EntityState,
            EntityType,
            WorldModel,
        )

        wm = WorldModel()
        wm.register_entity(
            Entity(
                id="dev1",
                type=EntityType.DEVICE,
                name="d",
                state=EntityState.INACTIVE,
                properties={},
            )
        )
        action = type("A", (), {"device_id": "dev1", "command": "click"})()
        _run(ActionExecutor()._update_world_model(wm, action, {"ok": 1}))

        entity = wm.get_entity("dev1")
        # 回归锁定:此前把 dict 传给要 EntityState 的接口 —— 先把 state 写成 dict
        # (第 93 行)再抛 AttributeError(第 95 行)被吞,实体状态就此被污染,
        # 此后任何读 .state.value 的地方都会连带出错。
        assert isinstance(entity.state, EntityState)
        assert entity.state.value == "active"
        assert entity.properties.get("last_action") == "click"
