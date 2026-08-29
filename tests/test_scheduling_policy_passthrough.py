"""选路策略在决策层算,底座不再自己算一遍(SCHED-003)。

改之前是什么样
--------------
``DeviceRouter`` 侧的**接收端**早就建好了:``route_task()`` 读
``ctx["_command_router_pre_analyzed"]`` 与 ``ctx["_pre_analysis"]``,命中就跳过
自己的 ``_analyze_command()``。哨兵
``DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL`` 把这个契约写得清清楚楚,
注释里还写明它"partially closes SCHED-003"。

**但没有任何一处生产代码盖过那两个标。** 全仓搜下来只命中 device_router.py 自己
(注释 + 读取端)。那条 passthrough 从来没被触发过,底座每次都还是自己做策略分析。

又一次"接收端建好了、发送端没接" —— 与 WebRTC 绑定那次、``require_migration``
那次是同一个形状。区别只在于这次连哨兵都写好了,所以它看起来尤其像已经完成。

为什么这件事要紧
----------------
策略分析(目标设备类型、task_type、exec_mode)是**决策**,它属于 CommandRouter
那一层;DeviceRouter 是**底座**。两层各算一遍的后果不是慢,是**同一条命令可能被
判成不同的 task_type,而两边都不认为自己错了**。
"""

from __future__ import annotations

import inspect

import pytest


class TestTheDecisionLayerStampsTheAnalysis:
    def test_a01_the_command_router_actually_stamps_it(self):
        """回归:这两个标此前在生产代码里一次都没被盖过。"""
        from core.command_router import CommandRouter

        body = inspect.getsource(CommandRouter)
        assert '"_pre_analysis"' in body
        assert '"_command_router_pre_analyzed"' in body

    def test_a02_it_uses_the_same_analyser_as_the_substrate(self):
        """用**同一个函数**,不在决策层另写一份。

        另写一份的表现是两层各自演进,然后同一条命令在两边被判成不同的 task_type。
        """
        from core.command_router import CommandRouter

        body = inspect.getsource(CommandRouter)
        assert "galaxy_gateway.routing.policy" in body

        # 底座那一侧委托的也是它 —— 两边同源才叫"一处权威"
        from galaxy_gateway.device_router import DeviceRouter

        substrate = inspect.getsource(DeviceRouter._analyze_command)
        assert "policy" in substrate or "_routing_analyze_command" in substrate

    def test_a03_stamping_failure_falls_back_to_the_old_behaviour(self):
        """算不出来时让底座自己算 —— 与改前逐字节一致,不是把选路打死。"""
        from core.command_router import CommandRouter

        body = inspect.getsource(CommandRouter)
        idx = body.index('"_command_router_pre_analyzed"')
        window = body[max(0, idx - 1500) : idx + 400]
        assert "except Exception" in window


class TestTheSubstrateHonoursIt:
    def test_b01_the_receiver_skips_its_own_analysis(self):
        from galaxy_gateway.device_router import DeviceRouter

        body = inspect.getsource(DeviceRouter.route_task)
        assert "_command_router_pre_analyzed" in body
        assert "_pre_analysis" in body

    def test_b02_the_governance_sentinel_still_describes_the_contract(self):
        """哨兵是这个契约的对外说明。改了行为不改哨兵,下一个人读到的就是旧契约。"""
        from galaxy_gateway.device_router import DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL as sentinel

        assert "_command_router_pre_analyzed" in sentinel
        assert "SCHED-003" in sentinel

    def test_b03_the_explicit_target_half_was_already_done(self):
        """A2 的另一半(外部解析的目标优先、缺失才退回自选)此前就做完了。

        钉住它是为了防反向回归:有人"统一"这两半时把已经做好的那半也拆了。
        """
        from galaxy_gateway.device_router import DeviceRouter

        body = inspect.getsource(DeviceRouter.route_task)
        assert "_resolve_explicit_target_devices" in body
        idx = body.index("_resolve_explicit_target_devices")
        assert "_select_devices" in body[idx : idx + 400], "外部目标缺失时要能退回底层选择"


class TestTheAnalysisShapeIsWhatTheSubstrateExpects:
    @pytest.mark.parametrize("field", ["task_type", "exec_mode"])
    def test_c01_the_analyser_produces_the_fields_the_substrate_reads(self, field):
        """底座从 analysis 里读 task_type 与 exec_mode。分析器不产出这两个字段的话,
        passthrough 命中之后底座会拿到空值 —— 那比不 passthrough 更糟。"""
        from galaxy_gateway.routing.policy import analyze_command

        analysis = analyze_command("打开设置", {"exec_mode": "both"})
        assert field in analysis

    def test_c02_context_fields_survive_the_analysis(self):
        """context 里的 exec_mode 要原样透出来 —— 决策层刚定的东西不能被分析器吃掉。"""
        from galaxy_gateway.routing.policy import analyze_command

        assert analyze_command("查询状态", {"exec_mode": "local"})["exec_mode"] == "local"
