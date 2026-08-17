"""阈限空间三类内容 + 转移语汇的上线契约。

这一轮补上了什么
================
``core/liminal_space_mapping.py`` 把阈限空间定义为「运行时的空间执行场」，装三类
内容：本机执行链、跨设备执行链、沙盘推演。第三类早就上了线，前两类
**一直只走到 ``continuum.state`` 事件为止** —— ``RuntimeSession._build_chain_views()``
每 200ms 都在产，而在场桥的 ``_on_continuum_state`` 只挑了 ``liminal_activity``
与 ``simulation`` 两项，两条链就在那一步被丢掉。

同时补上主轴的 ``previous_lifecycle`` / ``transition_kind``：覆盖层此前唯一的
依据是一个标量深度，深度从 manifest 走回 silent 时画面上放的就是进场动画倒放，
因为「正在返回」没有任何独立表示。

覆盖矩阵
========
A. 执行链视图与源定义逐字段对齐（源侧改名 → 这里红，而不是静默变成零）
B. 空态可区分（「还没跑过」≠「拿不到这条链」）
C. 转移语汇：handoff 与 dissolving 都是合法出口，不预先选一台状态机
D. 桥端到端：相位序列走一遍，转移语汇与两条链都出现在线材上
E. 契约取值域与后端权威枚举同源（不手抄）
"""

from __future__ import annotations

import pytest

from core.phase_contract import (
    CHAIN_KINDS,
    HYBRID_EXECUTION_MODES,
    LIFECYCLE_STATES,
    TRANSITION_KIND_OF,
    TRANSITION_KINDS,
    WORLD_MODEL_SOURCES,
    ExecutionChainView,
    HybridExecutionView,
    WorldModelView,
    resolve_render_posture,
    transition_kind_of,
)

# ---------------------------------------------------------------------------
# A. 执行链视图与源定义逐字段对齐
# ---------------------------------------------------------------------------


class TestGroupAChainViewAlignment:
    """渲染契约里的 ``ExecutionChainView`` 是源侧两个 view 的收形，不是另造一套。

    为什么不直接 import 源类型到 ``core/phase_contract``：实测导入
    ``core.liminal_space_mapping`` 约 142ms，而 phase_contract 自身约 6ms 且被
    **每一次相位事件**调用。所以那边保持不导入，对齐由本组测试保证 —— 测试可以慢慢 import。
    """

    def test_a01_local_view_fields_all_land_somewhere(self) -> None:
        from core.liminal_space_mapping import LocalChainView

        src = set(LocalChainView().to_dict())
        # timestamp 不进渲染契约：帧本身自带时间，链上再带一个只会让下游
        # 分不清「这条链的时间」和「这一帧的时间」。
        mapped = {
            "total_executions": "total_executions",
            "canonical_executions": "canonical_executions",
            "legacy_executions": "legacy_executions",
            "canonical_chain_order": "chain_order",
            "last_task_id": "last_target",
            "last_step": "last_step",
            "is_active": "is_active",
        }
        assert set(mapped) | {"timestamp"} == src, (
            "LocalChainView 的字段集变了 —— 渲染契约的映射表要跟着改，"
            "否则新字段永远到不了前端、改名的字段会静默变成零。"
        )

    def test_a02_cross_device_view_differs_only_in_the_target_field(self) -> None:
        from core.liminal_space_mapping import CrossDeviceChainView, LocalChainView

        local = set(LocalChainView().to_dict())
        cross = set(CrossDeviceChainView().to_dict())
        assert local - cross == {"last_task_id"}
        assert cross - local == {"last_device_id"}, (
            "两个源 view 的差异不再只是「最近这次的对象是谁」—— "
            "收成同一个渲染形状的前提没了，得重新想 ExecutionChainView 该长什么样。"
        )

    def test_a03_local_dict_maps_task_id_into_last_target(self) -> None:
        from core.liminal_space_mapping import build_local_chain_view

        src = build_local_chain_view(
            {
                "total_executions": 4,
                "canonical_executions": 3,
                "legacy_executions": 1,
                "canonical_chain_order": ["intake", "route", "execute"],
                "recent_records": [{"task_id": "task-77", "steps_completed": ["intake", "route"]}],
            }
        ).to_dict()
        view = ExecutionChainView.from_view_dict("local", src)

        assert view.kind == "local"
        assert view.total_executions == 4
        assert view.canonical_executions == 3
        assert view.legacy_executions == 1
        assert view.chain_order == ("intake", "route", "execute")
        assert view.last_step == "route"
        assert view.last_target == "task-77"
        assert view.is_active is True

    def test_a04_cross_device_dict_maps_device_id_into_last_target(self) -> None:
        from core.liminal_space_mapping import build_cross_device_chain_view

        src = build_cross_device_chain_view(
            {
                "total_executions": 2,
                "canonical_chain_order": ["dispatch", "ack"],
                "recent_records": [{"device_id": "phone-3", "steps_completed": ["dispatch"]}],
            }
        ).to_dict()
        view = ExecutionChainView.from_view_dict("cross_device", src)

        assert view.kind == "cross_device"
        assert view.last_target == "phone-3", "跨设备链读的是 last_device_id，读成 task_id 会恒为 None"
        assert view.last_step == "dispatch"

    def test_a05_wrong_kind_does_not_silently_read_the_other_field(self) -> None:
        """种类给错时不去猜 —— 读不到就是 None，而不是碰巧读到另一条链的字段。"""
        cross_raw = {"total_executions": 1, "last_device_id": "phone-3", "is_active": True}
        view = ExecutionChainView.from_view_dict("local", cross_raw)
        assert view.last_target is None

    def test_a06_unknown_kind_falls_back_to_local_not_crash(self) -> None:
        view = ExecutionChainView.from_view_dict("wormhole", {"total_executions": 1})
        assert view.kind in CHAIN_KINDS


# ---------------------------------------------------------------------------
# B. 空态可区分
# ---------------------------------------------------------------------------


class TestGroupBEmptyIsDistinguishable:
    """零态是有意义的信号，不是「没有这个东西」。"""

    @pytest.mark.parametrize("kind", CHAIN_KINDS)
    def test_b01_empty_chain_is_inactive_but_present(self, kind: str) -> None:
        v = ExecutionChainView.empty(kind)
        assert v.kind == kind
        assert v.is_active is False
        assert v.total_executions == 0
        assert v.chain_order == ()
        assert v.last_target is None

    def test_b02_missing_payload_yields_empty_not_none(self) -> None:
        for raw in (None, {}, "not-a-dict", []):
            v = ExecutionChainView.from_view_dict("local", raw)  # type: ignore[arg-type]
            assert isinstance(v, ExecutionChainView)
            assert v.is_active is False

    def test_b03_ran_zero_times_differs_from_ran_once(self) -> None:
        never = ExecutionChainView.empty("local")
        once = ExecutionChainView.from_view_dict(
            "local", {"total_executions": 1, "is_active": True, "recent_records": [{"task_id": "t"}]}
        )
        assert never != once
        assert (never.is_active, once.is_active) == (False, True)

    def test_b04_world_model_unwired_is_not_zero_entities(self) -> None:
        wm = WorldModelView.unwired()
        assert wm.is_wired is False
        assert wm.source == "unwired"
        assert wm.source in WORLD_MODEL_SOURCES
        # 「链路没建」与「建好了但一个实体都没有」必须能分开：前者 source=unwired，
        # 后者会是 source=live 且 entity_count=0。
        live_but_empty = WorldModelView(is_wired=True, source="live", entity_count=0, entity_kinds=())
        assert wm != live_but_empty

    def test_b04b_hybrid_from_decision_dict_round_trips(self) -> None:
        v = HybridExecutionView.from_decision_dict(
            {"mode": "parallel_race", "reason": "低延迟且两级都在", "confidence": 0.9}
        )
        assert (v.is_decided, v.mode, v.confidence) == (True, "parallel_race", 0.9)

    def test_b04c_unknown_mode_is_refused_not_passed_through(self) -> None:
        """前端的类型里没有那个字面量，放进去只会在 switch 里掉到 default。"""
        for bad in ({"mode": "teleport"}, {"mode": "none"}, {"mode": ""}, {}, None):
            v = HybridExecutionView.from_decision_dict(bad)  # type: ignore[arg-type]
            assert (v.is_decided, v.mode) == (False, "none"), bad

    def test_b04d_audit_snapshot_never_reaches_the_wire(self) -> None:
        """``context_snapshot`` 是给审计的完整上下文，里面有 app_id / device_id。

        渲染要的只是「选了哪种、为什么、有多确定」；顺手带上等于把目标应用和
        设备标识暴露给渲染层。
        """
        import dataclasses

        v = HybridExecutionView.from_decision_dict(
            {
                "mode": "staged_hybrid",
                "reason": "r",
                "confidence": 1.0,
                "context_snapshot": {"app_id": "wechat", "device_id": "phone-1"},
            }
        )
        assert "context_snapshot" not in {f.name for f in dataclasses.fields(v)}

    def test_b05_hybrid_undecided_is_not_a_decision(self) -> None:
        h = HybridExecutionView.undecided()
        assert h.is_decided is False
        assert h.mode == "none"
        decided_no_reason = HybridExecutionView(is_decided=True, mode="parallel_race", reason="", confidence=0.0)
        assert h != decided_no_reason


# ---------------------------------------------------------------------------
# C. 转移语汇
# ---------------------------------------------------------------------------


class TestGroupCTransitionKind:
    """``handoff`` 与 ``dissolving`` **都是**合法出口 —— 契约不替渲染端选一条。"""

    def test_c01_no_previous_means_no_transition(self) -> None:
        assert transition_kind_of(None, "silent") == "none"
        assert transition_kind_of("", "manifest") == "none"

    def test_c02_same_phase_repeat_is_not_a_transition(self) -> None:
        """同档位的重复广播不能被算成一次转移，否则退场动画会反复重播。"""
        for life in LIFECYCLE_STATES:
            assert transition_kind_of(life, life) == "none"

    def test_c03_forward_arc(self) -> None:
        assert transition_kind_of("silent", "liminal") == "emerging"
        assert transition_kind_of("liminal", "manifest") == "committing"

    def test_c04_both_exits_from_manifest_are_modelled(self) -> None:
        """这是本组的核心。

        后端有两套三态描述，一度看起来在打架：continuum 副轴的禁止表说
        ``manifest → liminal`` 不许，在场层的转移策略却有一条
        ``MANIFEST → LIMINAL``（触发条件 ``execution_completed_or_result_committed``）。

        它们在**不同的轴**上：前者说的是内部连续体的相位图，后者说的是主体生命
        周期。所以契约两条都认，由渲染端按实际收到的这一位编排。
        """
        assert transition_kind_of("manifest", "liminal") == "handoff"
        assert transition_kind_of("manifest", "silent") == "dissolving"
        assert {"handoff", "dissolving"} <= set(TRANSITION_KINDS)

    def test_c05_liminal_can_also_dissolve_without_ever_manifesting(self) -> None:
        """意图没成形就散了 —— 这条弧真实存在（转移表里 liminal → formless）。"""
        assert transition_kind_of("liminal", "silent") == "dissolving"

    def test_c06_emergency_jump_is_committing_not_a_new_kind(self) -> None:
        assert transition_kind_of("silent", "manifest") == "committing"

    def test_c07_table_covers_every_ordered_pair_of_distinct_states(self) -> None:
        expected = {(a, b) for a in LIFECYCLE_STATES for b in LIFECYCLE_STATES if a != b}
        assert set(TRANSITION_KIND_OF) == expected, (
            "转移表漏了一对主轴组合 —— 漏掉的那一对会算成 none，" "渲染端于是在一次真实转移上什么都不播。"
        )

    def test_c08_every_kind_in_the_table_is_in_the_vocabulary(self) -> None:
        assert set(TRANSITION_KIND_OF.values()) <= set(TRANSITION_KINDS)

    def test_c09_posture_carries_both_the_pair_and_the_kind(self) -> None:
        p = resolve_render_posture("silent", previous_lifecycle="manifest")
        assert p.previous_lifecycle == "manifest"
        assert p.transition_kind == "dissolving"
        d = p.to_dict()
        assert d["previous_lifecycle"] == "manifest"
        assert d["transition_kind"] == "dissolving"

    def test_c10_bogus_previous_is_dropped_not_propagated(self) -> None:
        p = resolve_render_posture("liminal", previous_lifecycle="banana")
        assert p.previous_lifecycle is None
        assert p.transition_kind == "none"


# ---------------------------------------------------------------------------
# D. 桥端到端
# ---------------------------------------------------------------------------


class TestGroupDBridgeWire:
    """相位序列走一遍，看线材上真的出现了这些东西。"""

    @staticmethod
    def _bridge():
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        return GalaxyPresenceBridge()

    def test_d01_phase_sequence_produces_the_expected_transition_kinds(self) -> None:
        b = self._bridge()
        seen = []
        # 桥内部用 "static" 表示静息；契约主轴用 "silent"。
        for token in ("static", "liminal", "manifest", "static"):
            seen.append(b._render_payload(token)["transition_kind"])
        assert seen == ["none", "emerging", "committing", "dissolving"]

    def test_d02_handoff_appears_when_manifest_returns_to_liminal(self) -> None:
        b = self._bridge()
        b._render_payload("liminal")
        b._render_payload("manifest")
        assert b._render_payload("liminal")["transition_kind"] == "handoff"

    def test_d03_repeated_broadcast_of_the_same_phase_reports_none(self) -> None:
        b = self._bridge()
        b._render_payload("static")
        assert b._render_payload("liminal")["transition_kind"] == "emerging"
        assert b._render_payload("liminal")["transition_kind"] == "none"

    def test_d04_continuum_tick_chain_views_reach_the_wire(self) -> None:
        """这条钉的就是本轮修的那个断点。

        两条链一直在 ``continuum.state`` 的 payload 里，而回调只挑了两项。
        """
        b = self._bridge()
        b._on_continuum_state(
            {
                "liminal_activity": "rehearsing",
                "local_chain": {
                    "total_executions": 5,
                    "canonical_chain_order": ["intake", "execute"],
                    "last_task_id": "task-5",
                    "last_step": "execute",
                    "is_active": True,
                },
                "cross_device_chain": {
                    "total_executions": 2,
                    "last_device_id": "phone-1",
                    "is_active": True,
                },
            }
        )
        d = b._render_payload("liminal")
        assert d["local_chain"]["last_target"] == "task-5"
        assert d["local_chain"]["chain_order"] == ["intake", "execute"]
        assert d["cross_device_chain"]["last_target"] == "phone-1"
        assert d["liminal_activity"] == "rehearsing"

    def test_d05_chains_are_not_cropped_by_phase(self) -> None:
        """执行链的推进恰恰发生在 MANIFEST，只在阈限期带就截掉了最该看的一段。"""
        b = self._bridge()
        b._on_continuum_state({"local_chain": {"total_executions": 3, "is_active": True}})
        for token in ("static", "liminal", "manifest"):
            assert b._render_payload(token)["local_chain"]["total_executions"] == 3

    async def test_d06_chains_survive_return_to_silent(self) -> None:
        """推演摘要随请求清空，执行链是会话级累计 —— 清掉会让静息期显示成从没跑过。

        必须是 async：``_on_phase_silent`` 会 ``create_task`` 去广播，没有事件循环
        直接抛 RuntimeError。广播本身被换成空协程 —— 本条钉的是清空策略，
        不是那条 IPC/WS 出口（它有自己的测试），让它去连 127.0.0.1:9231 只会让
        这条测试变慢且依赖环境。
        """

        async def _noop() -> None:
            return None

        b = self._bridge()
        b._broadcast_state = _noop  # type: ignore[method-assign]
        b._on_continuum_state(
            {
                "liminal_activity": "rehearsing",
                "simulation": {"is_active": True, "candidate_paths": ["a"]},
                "local_chain": {"total_executions": 7, "is_active": True},
            }
        )
        b._on_phase_silent({})
        d = b._render_payload("static")
        assert d["local_chain"]["total_executions"] == 7
        assert d["simulation"]["is_active"] is False, "推演摘要应当随请求结束清空"

    def test_d07_absent_chain_in_a_tick_does_not_wipe_the_last_good_one(self) -> None:
        b = self._bridge()
        b._on_continuum_state({"local_chain": {"total_executions": 9, "is_active": True}})
        b._on_continuum_state({"liminal_activity": "thinking"})
        assert b._render_payload("liminal")["local_chain"]["total_executions"] == 9

    def test_d08a_hybrid_decision_reaches_the_wire(self) -> None:
        b = self._bridge()
        b._on_continuum_state(
            {
                "hybrid_execution": {
                    "mode": "staged_hybrid",
                    "reason": "两个明确阶段",
                    "confidence": 0.95,
                    "context_snapshot": {"app_id": "wechat"},
                }
            }
        )
        d = b._render_payload("manifest")["hybrid_execution"]
        assert d["is_decided"] is True
        assert d["mode"] == "staged_hybrid"
        assert "context_snapshot" not in d

    async def test_d08b_hybrid_decision_clears_on_return_to_silent(self) -> None:
        """换一轮请求就换了目标应用，上一轮选的手法对它没有意义。"""

        async def _noop() -> None:
            return None

        b = self._bridge()
        b._broadcast_state = _noop  # type: ignore[method-assign]
        b._on_continuum_state({"hybrid_execution": {"mode": "parallel_race", "confidence": 0.9}})
        assert b._render_payload("manifest")["hybrid_execution"]["is_decided"] is True
        b._on_phase_silent({})
        assert b._render_payload("static")["hybrid_execution"]["is_decided"] is False

    def test_d08_world_model_slot_is_on_the_wire_and_honest(self) -> None:
        d = self._bridge()._render_payload("liminal")
        assert d["world_model"] == {
            "is_wired": False,
            "source": "unwired",
            "entity_count": 0,
            "entity_kinds": [],
        }

    def test_d09_payload_is_json_serialisable(self) -> None:
        import json

        b = self._bridge()
        b._on_continuum_state(
            {"local_chain": {"total_executions": 1, "canonical_chain_order": ["a"], "is_active": True}}
        )
        json.dumps(b._render_payload("manifest"))  # 元组没转 list 的话这里会炸


# ---------------------------------------------------------------------------
# F. 执行手法真的在被选
# ---------------------------------------------------------------------------


class TestGroupFHybridProducer:
    """``core/hybrid_execution_policy.py`` 此前**零生产调用方**。

    它的模块文档写着自己「被 HybridExecutionArbiter 消费」，而执行器里那一行是
    字面量 ``mode="sequential_degrade"`` —— 策略引擎从没被调用过。于是系统既没在
    选，也就无从说自己选了什么，第三态"用什么手法"没有任何数据来源。

    本组钉的是：现在真的在选，而且选出来的东西真的到了渲染契约。
    """

    @staticmethod
    def _session():
        from core.desktop_presence_runtime import RuntimeSession, TriState

        s = RuntimeSession("test")
        s.advance(TriState.LIMINAL)
        s.advance(TriState.MANIFEST)
        return s

    def test_f01_mode_is_no_longer_a_literal_in_the_executor(self) -> None:
        import inspect

        from core.hybrid_executor import HybridExecutionArbiter

        src = inspect.getsource(HybridExecutionArbiter.execute)
        assert 'mode="sequential_degrade"' not in src, "执行器又把模式写死了 —— 策略引擎再次变成摆设"
        assert "evaluate_hybrid_execution_mode" in src, "执行器没有调用策略引擎"

    async def test_f02_default_path_records_a_real_decision(self) -> None:
        from core.hybrid_executor import get_hybrid_arbiter
        from core.liminal_activity import bind_runtime_session, unbind_runtime_session

        s = self._session()
        tok = bind_runtime_session(s)
        try:
            try:
                await get_hybrid_arbiter().execute(
                    device_id="linux-1", app_id="unregistered-app", action="noop", windows_arbiter=False
                )
            except Exception:  # noqa: BLE001 — 执行本身失败与否不影响选型是否发生
                pass
        finally:
            unbind_runtime_session(tok)

        assert s.hybrid_execution is not None, "执行走完了却没有登记任何选型"
        v = HybridExecutionView.from_decision_dict(s.hybrid_execution)
        assert v.is_decided is True
        assert v.mode == "sequential_degrade"
        assert v.reason, "选了却说不出为什么 —— 那和写死没有区别"

    async def test_f03_pinned_level_reports_no_decision_rather_than_a_false_one(self) -> None:
        """调用方点名级别时，如实说"本轮没有发生模式选择"。

        那条路径是 ``levels = [force_level]`` —— 只跑这一级、根本不降级。现有取值域
        里没有一个能如实描述它：``local_preferred`` 的定义是"优先本地、失败再退远端
        VLM"，拿它标注一个不降级的执行就是写一条假的。宁可 undecided。
        """
        from core.hybrid_executor import ExecutionLevel, get_hybrid_arbiter
        from core.liminal_activity import bind_runtime_session, unbind_runtime_session

        s = self._session()
        tok = bind_runtime_session(s)
        try:
            try:
                await get_hybrid_arbiter().execute(
                    device_id="linux-1",
                    app_id="unregistered-app",
                    action="noop",
                    force_level=ExecutionLevel.GUI,
                    windows_arbiter=False,
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            unbind_runtime_session(tok)

        assert s.hybrid_execution is None, "点名级别时不该编一个模式出来"
        assert HybridExecutionView.from_decision_dict(s.hybrid_execution).is_decided is False

    def test_f03b_local_preferred_still_means_it_falls_back(self) -> None:
        """钉住上面那条判断所依赖的语义：``local_preferred`` 是**会**降级的。

        哪天这个模式的定义改成"只走本地、不降级"，上面拒绝用它标注 force_level
        的理由就不成立了 —— 那时该回来重新想，而不是让两处悄悄背离。
        """
        from core.hybrid_execution_policy import HybridExecutionMode

        assert HybridExecutionMode.local_preferred.is_degrade_chain is True

    async def test_f04_noting_outside_a_request_is_a_no_op_not_an_error(self) -> None:
        """直接调执行器、测试裸跑时没有生命周期可挂 —— 不该因此报错。"""
        from core.hybrid_executor import get_hybrid_arbiter

        try:
            await get_hybrid_arbiter().execute(
                device_id="linux-1", app_id="unregistered-app", action="noop", windows_arbiter=False
            )
        except Exception:  # noqa: BLE001 — 执行失败允许，登记不该抛
            pass

    def test_f05_note_returns_false_when_unbound(self) -> None:
        from core.liminal_activity import note_hybrid_execution

        assert note_hybrid_execution({"mode": "parallel_race"}) is False
        assert note_hybrid_execution(None) is False

    def test_f06_session_clears_the_decision_on_return_to_silent(self) -> None:
        from core.desktop_presence_runtime import TriState

        s = self._session()
        s.enter_hybrid_execution({"mode": "parallel_race"})
        assert s.hybrid_execution is not None
        s.advance(TriState.SILENT)
        assert s.hybrid_execution is None

    def test_f07_tick_payload_carries_it_only_when_present(self) -> None:
        """有值才带 —— 没带 ≠ 带了个空的。下游据此区分「这一拍没说」与「还没选」。"""
        import inspect

        from core.desktop_presence_runtime import RuntimeSession

        src = inspect.getsource(RuntimeSession._continuum_tick_loop)
        assert "if self.hybrid_execution is not None:" in src
        assert '_payload["hybrid_execution"] = self.hybrid_execution' in src


# ---------------------------------------------------------------------------
# E. 取值域与后端权威枚举同源
# ---------------------------------------------------------------------------


class TestGroupEVocabularyIsNotHandCopied:
    def test_e01_hybrid_modes_match_the_policy_enum(self) -> None:
        from core.hybrid_execution_policy import HybridExecutionMode

        assert set(HYBRID_EXECUTION_MODES) - {"none"} == {m.value for m in HybridExecutionMode}, (
            "渲染契约的执行手法取值域与 core.hybrid_execution_policy 分叉了 —— "
            "前端会拿到一个它的类型里根本没有的 mode。"
        )

    def test_e02_chain_kinds_cover_both_liminal_space_chains(self) -> None:
        assert set(CHAIN_KINDS) == {"local", "cross_device"}

    def test_e03_schema_exposes_every_new_vocabulary(self) -> None:
        from core.phase_contract import render_contract_schema

        sch = render_contract_schema()
        for key in (
            "chain_kinds",
            "hybrid_execution_modes",
            "world_model_sources",
            "transition_kinds",
            "transition_kind_of",
            "chain_fields",
            "hybrid_fields",
            "world_model_fields",
        ):
            assert key in sch, f"schema 少了 {key} —— gen_ts_types.py 会生成不出对应的 TS 类型"
