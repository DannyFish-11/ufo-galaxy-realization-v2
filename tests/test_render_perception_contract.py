"""第一态的主体：原生多模态摄入上线到渲染契约。

要解决什么
==========
第一态的定义**本身就是感知**。``TriStatePhase.SILENT`` 的原文：

    The system is always alive in silent; it is receiving inputs (audio,
    visual, touch, text) from its native modalities and building ambient context.

而在这一层之前，``RenderPosture`` 里**一个感知字段都没有**。感知状态走的是另一条
平行的、无类型的分支 ``payload.ambient``：面板手写类型读了它，覆盖层一次都没读过。
也就是说，第一态的视觉主体在渲染端没有数据来源。

两个结构性决定
==============
1. **不走 200ms tick**。那条 tick 在 SILENT 里是停的（``_on_advance_tick``），
   而感知最需要在场的那一相正是它不跑的那一相。改走只读拉取，纪律与
   ``last_continuum_posture`` 相同：绝不构造，只看已经存在的。
2. **逐模态五档，不是布尔**。布尔会把「没有这条通路」「有但闭着」「有但这一拍静了」
   压成同一个 false —— 那正是深度轴犯过的错。

覆盖矩阵
========
A. 五档语义：每一档都由一个真实场景产生，且彼此可区分
B. 反自激励：朗读期的麦克风是 suppressed，且只作用于麦克风
C. 只读纪律：不构造、不导入重模块、异常不外泄
D. unwired 与「都静着」可区分
E. 桥端到端 + 第一态不被裁剪
F. 取值域与后端权威枚举同源
"""

from __future__ import annotations

import time

import pytest

from core.phase_contract import (
    AMBIENT_ACTIONS,
    MODALITY_STATES,
    PERCEPTION_MODALITIES,
    VIEW_SOURCES,
    WORLD_MODEL_SOURCES,
    ModalityView,
    PerceptionView,
    resolve_perception_view,
    resolve_render_posture,
)


@pytest.fixture
def store():
    """真的桌面感知库，用完复位 —— 它是进程内单例，脏了会污染别的用例。"""
    from core.perception.desktop_perception_store import get_desktop_perception_store

    s = get_desktop_perception_store()
    prev_ttl = s.ttl_sec
    yield s
    s.resume("test-teardown")
    s.ttl_sec = prev_ttl


#: ``DesktopPerceptionStore.status()`` 的槽位名（与契约的模态名不同：麦克风那槽叫 audio）。
_SLOTS = ("screen", "camera", "audio", "system_audio")


def _status(*, paused: bool = False, **slots) -> dict:
    """合成一份 ``status()``。

    **为什么用合成而不是真单例**：``*_received`` 是进程级累计，且 ``pause()`` 也不清它。
    同一次 pytest 里别的用例（``test_camera_reaches_continuous_perception`` 等）会往
    同一个单例推帧，于是"这条通路从没来过东西"这类断言会随**测试顺序**而变 ——
    那正是这份契约要消灭的那种不确定性，不该由它自己的测试引入。

    形状与真库的一致性由 :meth:`TestGroupFVocabulary.test_f05_synthetic_status_matches_the_real_shape`
    钉住：真库改字段名，那里会红，而不是让这些用例静默地全部测在空气上。

    Args:
        paused: 隐私急停。
        **slots: 每槽给 ``"live"`` / ``"idle"`` / 省略（= 从没来过）。
    """
    out: dict = {"ttl_sec": 10.0, "privacy": {"paused": paused}}
    for slot in _SLOTS:
        mode = slots.get(slot)
        out[f"{slot}_received"] = 0 if mode is None else 3
        out[f"{slot}_fresh"] = mode == "live"
        out[f"{slot}_age_sec"] = None if mode is None else (0.4 if mode == "live" else 99.0)
    return out


def _states(view: PerceptionView) -> dict:
    return {m.modality: m.state for m in view.modalities}


# ---------------------------------------------------------------------------
# A. 五档语义
# ---------------------------------------------------------------------------


class TestGroupAFiveStates:
    """每一档都由一个真实场景产生。布尔做不到的正是这一组。

    这一组走**合成 status**（见 :func:`_status`）：判定本身是纯函数，用真单例只会
    引入测试顺序依赖 —— ``*_received`` 是进程级累计，别的用例往同一个单例推过帧，
    "从没来过东西"就不再成立。形状与真库的一致性由 F 组守着。
    """

    def test_a01_never_pushed_is_unavailable(self) -> None:
        assert _states(resolve_perception_view(_status(screen="live")))["camera"] == "unavailable"

    def test_a02_fresh_signal_is_live(self) -> None:
        v = resolve_perception_view(_status(screen="live"))
        assert _states(v)["screen"] == "live"
        assert v.is_sensing is True

    def test_a03_stale_signal_is_idle_not_unavailable(self) -> None:
        """**这一条是整组的要点。**

        「通路通、只是这一拍静了」与「根本没有这条通路」是两件事，而布尔会把它们
        压成同一个 false。渲染上前者该柔和呼吸（它在），后者该不亮（它不在）。
        """
        v = resolve_perception_view(_status(screen="idle"))
        assert _states(v)["screen"] == "idle"
        assert _states(v)["camera"] == "unavailable"
        assert v.is_sensing is False

    def test_a04_privacy_pause_is_paused_not_unavailable(self) -> None:
        v = resolve_perception_view(_status(screen="live", paused=True))
        assert _states(v)["screen"] == "paused"
        assert v.privacy_paused is True
        assert v.is_sensing is False

    def test_a05_pause_does_not_invent_an_eye_that_never_existed(self) -> None:
        """暂停对一条根本不存在的通路没有意义 —— 报 paused 会让渲染端画出一只
        「闭着的眼睛」，而那里从来就没有眼睛。"""
        v = resolve_perception_view(_status(screen="live", paused=True))
        assert _states(v)["camera"] == "unavailable"

    def test_a06_a_channel_that_ran_before_stays_idle_not_unavailable(self) -> None:
        """暂停会清空缓存但**不清** ``*_received``，所以恢复后是 idle（通路通、
        暂时没数据）而不是退回 unavailable。这一条钉的就是那个语义差。"""
        assert _states(resolve_perception_view(_status(screen="idle")))["screen"] == "idle"

    def test_a07_all_five_states_are_reachable(self) -> None:
        """取值域里没有一档是摆设。"""
        seen = {
            _states(resolve_perception_view(_status()))["camera"],
            _states(resolve_perception_view(_status(screen="live")))["screen"],
            _states(resolve_perception_view(_status(screen="idle")))["screen"],
            _states(resolve_perception_view(_status(audio="live"), speaking=True))["microphone"],
            _states(resolve_perception_view(_status(screen="live", paused=True)))["screen"],
        }
        assert seen == set(MODALITY_STATES)

    def test_a08_modalities_are_always_four_in_order(self) -> None:
        """恒定四条 —— 渲染端不该遍历一个长度会变的数组。"""
        v = resolve_perception_view(_status())
        assert tuple(m.modality for m in v.modalities) == PERCEPTION_MODALITIES

    def test_a09_age_none_differs_from_age_zero(self) -> None:
        """``None``（从没有过信号）与一个数（有过）是两件事。"""
        v = resolve_perception_view(_status(screen="live"))
        by = {m.modality: m.signal_age_s for m in v.modalities}
        assert by["camera"] is None
        assert by["screen"] is not None and by["screen"] >= 0.0


# ---------------------------------------------------------------------------
# B. 反自激励
# ---------------------------------------------------------------------------


class TestGroupBAntiSelfExcitation:
    """朗读时麦克风采到的是 AI 自己的声音。

    自发注意力循环**刻意忽略**那段音频 —— 不然它会把自己说的话转写成用户输入
    喂回下一拍，无限自言自语。这一组钉的是：那条约束以**状态**的形式送到渲染端，
    而不是留成渲染端要记的规矩。规矩会被忘记，状态不会。
    """

    def test_b01_microphone_is_suppressed_while_speaking(self) -> None:
        st = _status(audio="live")
        assert _states(resolve_perception_view(st))["microphone"] == "live"
        assert _states(resolve_perception_view(st, speaking=True))["microphone"] == "suppressed"

    def test_b02_suppression_touches_only_the_microphone(self) -> None:
        """TTS 不影响屏幕，也不影响系统声 —— 系统声回答的是「用户此刻在听什么」。"""
        got = _states(resolve_perception_view(_status(screen="live", system_audio="live"), speaking=True))
        assert got["screen"] == "live"
        assert got["system_audio"] == "live"

    def test_b03_suppressed_is_not_the_same_as_absent(self) -> None:
        """「被屏蔽」该短暂闭合，「没有」该不亮 —— 两种画法。"""
        assert _states(resolve_perception_view(_status(audio="live"), speaking=True))["microphone"] != "unavailable"

    def test_b04_pause_outranks_suppression(self) -> None:
        """用户按停了，就不该再表现成「只是暂时闭嘴」。"""
        got = _states(resolve_perception_view(_status(audio="live", paused=True), speaking=True))
        assert got["microphone"] == "paused"


# ---------------------------------------------------------------------------
# C. 只读纪律
# ---------------------------------------------------------------------------


class TestGroupCReadOnlyDiscipline:
    def test_c01_fetcher_never_constructs_the_store(self, monkeypatch) -> None:
        """``get_desktop_perception_store()`` 会**创建**单例。在广播的每一拍里
        调它是错的 —— 与 ``last_continuum_posture`` 对 ``get_openclawd()`` 同理。"""
        import sys

        import core.phase_contract as pc

        monkeypatch.setitem(sys.modules, "core.perception.desktop_perception_store", None)
        assert pc.last_perception_status() is None

    def test_c02_missing_singleton_yields_none_not_an_exception(self, monkeypatch) -> None:
        import core.perception.desktop_perception_store as mod
        import core.phase_contract as pc

        monkeypatch.setattr(mod.DesktopPerceptionStore, "_instance", None, raising=False)
        assert pc.last_perception_status() is None

    def test_c03_a_broken_store_degrades_instead_of_breaking_the_broadcast(self, monkeypatch) -> None:
        import core.perception.desktop_perception_store as mod
        import core.phase_contract as pc

        class _Boom:
            def status(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(mod.DesktopPerceptionStore, "_instance", _Boom(), raising=False)
        assert pc.last_perception_status() is None
        assert resolve_perception_view().source == "unwired"

    def test_c04_contract_module_stays_light(self) -> None:
        """本模块被每一次相位事件调用；导入感知库约 71ms，不能进模块顶层。"""
        import pathlib

        src = pathlib.Path("core/phase_contract.py").read_text(encoding="utf-8")
        head = src.split("PHASE_ANCHORS", 1)[0]
        assert "import core.perception" not in head
        assert "from core.perception" not in head


# ---------------------------------------------------------------------------
# D. unwired 可区分
# ---------------------------------------------------------------------------


class TestGroupDUnwiredIsDistinguishable:
    def test_d01_unwired_is_not_four_idle_modalities(self) -> None:
        u = PerceptionView.unwired()
        assert u.source == "unwired"
        assert all(m.state == "unavailable" for m in u.modalities)
        assert u.is_sensing is False

    def test_d02_store_present_but_silent_is_live_not_unwired(self, store) -> None:
        """「进程里没有感知库」与「库在、四条都静着」是两件事。"""
        v = resolve_perception_view(store.status())
        assert v.source == "live"
        assert v.is_sensing is False

    def test_d03_view_sources_is_one_definition_not_two(self) -> None:
        """世界模型与感知共用同一份取值域 —— 抄一份就多一个会漂的定义。"""
        assert WORLD_MODEL_SOURCES is VIEW_SOURCES

    def test_d04_bogus_ambient_action_is_dropped(self) -> None:
        v = resolve_perception_view({"privacy": {"paused": False}}, ambient_action="teleport")
        assert v.ambient_action == "none"

    def test_d05_rationale_is_truncated_not_unbounded(self) -> None:
        v = resolve_perception_view({"privacy": {"paused": False}}, ambient_rationale="x" * 5000)
        assert len(v.ambient_rationale) <= 200


# ---------------------------------------------------------------------------
# E. 桥端到端
# ---------------------------------------------------------------------------


class TestGroupEBridgeWire:
    @staticmethod
    def _bridge():
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        return GalaxyPresenceBridge()

    def test_e01_perception_is_on_the_wire(self, store) -> None:
        store.update_frame("Zm9v", source="screen")
        d = self._bridge()._render_payload("static")["perception"]
        assert d["source"] == "live"
        assert {m["modality"] for m in d["modalities"]} == set(PERCEPTION_MODALITIES)

    def test_e02_first_state_is_not_cropped(self, store) -> None:
        """第一态恰恰是它最要紧的一相 —— 200ms tick 在那里是停的，所以这一层
        必须走只读拉取。若它被按相位裁掉，等于修了个寂寞。"""
        store.update_frame("Zm9v", source="screen")
        b = self._bridge()
        for token in ("static", "liminal", "manifest"):
            assert b._render_payload(token)["perception"]["is_sensing"] is True

    def test_e03_bridge_speaking_flag_drives_suppression(self, store) -> None:
        store.update_audio("YmFy")
        b = self._bridge()
        mic = lambda d: next(m for m in d["perception"]["modalities"] if m["modality"] == "microphone")["state"]
        assert mic(b._render_payload("static")) == "live"
        b._speaking = True
        assert mic(b._render_payload("static")) == "suppressed"

    async def test_e04_ambient_decision_reaches_the_view(self, store) -> None:
        """必须是 async：``_on_ambient_decision`` 会 ``create_task`` 去广播，
        没有事件循环直接抛。广播换成空协程 —— 本条钉的是决策进没进视图。"""

        async def _noop() -> None:
            return None

        b = self._bridge()
        b._broadcast_state = _noop  # type: ignore[method-assign]
        b._on_ambient_decision({"action": "silent", "rationale": "画面没变，不打扰"})
        d = b._render_payload("static")["perception"]
        assert d["ambient_action"] == "silent"
        assert "不打扰" in d["ambient_rationale"]

    def test_e05_payload_is_json_serialisable(self, store) -> None:
        import json

        store.update_frame("Zm9v", source="screen")
        json.dumps(self._bridge()._render_payload("static"))

    def test_e06_anchor_only_fallback_still_carries_perception(self, store, monkeypatch) -> None:
        """兜底姿态最常出现的场合恰恰是主轴 silent —— 也就是第一态。
        在那里把感知抹成空，等于在最需要它的时候永远是空的。

        必须显式把 continuum 拿掉来逼出兜底分支：``source`` 取决于这个进程里有没有
        活的 ``ContinuumState``，那是**全局状态**。直接断言它会随测试顺序而变 ——
        本条最初就是这么写的，本机单跑绿、CI 全量跑红（别的用例已经把 OpenClawd
        建起来了，于是这里拿到 ``continuum``）。
        """
        import core.phase_contract as pc

        store.update_frame("Zm9v", source="screen")
        monkeypatch.setattr(pc, "last_continuum_posture", lambda: None)
        p = pc.resolve_render_posture("silent")
        assert p.source == "anchor_only"
        assert p.perception.is_sensing is True


# ---------------------------------------------------------------------------
# F. 取值域同源
# ---------------------------------------------------------------------------


class TestGroupFVocabulary:
    def test_f01_ambient_actions_match_the_loop_enum(self) -> None:
        from core.ambient_attention_loop import AmbientAction

        assert set(AMBIENT_ACTIONS) - {"none"} == {a.value for a in AmbientAction}

    def test_f02_modalities_cover_every_store_slot(self) -> None:
        """感知库是四槽分离的（麦克风与系统声刻意不混流）。契约漏一槽 =
        渲染端永远看不见那一路。"""
        from core.perception.desktop_perception_store import get_desktop_perception_store

        status = get_desktop_perception_store().status()
        slots = {k.rsplit("_received", 1)[0] for k in status if k.endswith("_received")}
        assert slots == {"screen", "camera", "audio", "system_audio"}
        assert len(PERCEPTION_MODALITIES) == len(slots)

    def test_f03_schema_exposes_the_new_vocabulary(self) -> None:
        from core.phase_contract import render_contract_schema

        sch = render_contract_schema()
        for key in (
            "perception_modalities",
            "modality_states",
            "ambient_actions",
            "modality_fields",
            "perception_fields",
        ):
            assert key in sch, f"schema 少了 {key} —— 生成器出不了对应的 TS 类型"

    def test_f04_unavailable_factory_rejects_a_bogus_modality(self) -> None:
        assert ModalityView.unavailable("wormhole").modality in PERCEPTION_MODALITIES

    def test_f05_synthetic_status_matches_the_real_shape(self) -> None:
        """A/B 两组走合成 status —— 这一条保证那份合成不会与真库悄悄分叉。

        没有它，真库改一个字段名，那两组会**照样全绿**，因为它们测的是一份
        自说自话的字典。那比没有测试更糟。
        """
        from core.perception.desktop_perception_store import get_desktop_perception_store

        real = set(get_desktop_perception_store().status())
        fake = set(_status(screen="live"))
        missing = {k for k in real if k.endswith(("_received", "_fresh", "_age_sec"))} - fake
        assert not missing, f"合成 status 少了真库有的键：{sorted(missing)}"
        assert "privacy" in fake and "privacy" in real
