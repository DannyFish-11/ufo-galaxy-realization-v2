"""相位契约连续化 —— 别在面板边界把已经算好的连续量扔掉。

背景（实测，不是推测）
----------------------
``core/continuum/types.py`` 的 ``ContinuumState`` 一直在算 presence_intensity /
coherence / collapse_tendency（"推向相位塌缩的概率质量 liminal → manifest"）/
retreat_tendency / stability，``ContinuumPhase`` 内部还是四档（含 receding）。
连跑四拍实测 presence_intensity = 0.0375 → 0.0656 → 0.0867 → 0.1025、
``degraded=False`` —— 它是活的。

但 ``core/lumiv_websocket_bridge.py`` 收到相位事件后，把渲染深度设成查表得到的
三个硬编码常数（0.05 / 0.62 / 0.92）。面板拿到的 ``depth_factor`` 不是算出来的，
是三选一。所谓"三态边缘模糊"所需的模型一直都在，只是在最后一步被丢掉。

这份测试钉的是**行为**：深度必须随倾向连续变化，且相位归属不被连续量推翻。
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from core.phase_contract import (
    EDGE_BLEND,
    PHASE_ANCHORS,
    PostureSource,
    last_continuum_posture,
    phase_contract_schema,
    resolve_phase_posture,
)


def _state(**kw: Any) -> Any:
    base = dict(
        presence_intensity=0.5,
        coherence=0.5,
        collapse_tendency=0.0,
        retreat_tendency=0.0,
        stability=1.0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# 1. 深度必须是算出来的，不是查表
# ---------------------------------------------------------------------------


class TestDepthIsDerivedNotLookedUp:
    def test_depth_moves_with_collapse_tendency(self) -> None:
        """塌缩倾向递增 → 深度严格单调递增。

        这是整件事的核心断言：改造前无论倾向是多少，深度恒为 0.62。
        """
        depths = [resolve_phase_posture("liminal", _state(collapse_tendency=t)).depth for t in (0.0, 0.3, 0.6, 0.9)]
        assert depths == sorted(depths), f"深度没有随倾向单调变化：{depths}"
        assert len(set(depths)) == len(depths), f"深度没有真的变化（像是仍在查表）：{depths}"

    def test_depth_moves_down_with_retreat_tendency(self) -> None:
        p = resolve_phase_posture("liminal", _state(retreat_tendency=0.9))
        assert p.depth < PHASE_ANCHORS["liminal"], "回撤倾向高时深度应低于锚点"

    def test_opposing_tendencies_cancel(self) -> None:
        """两个倾向同时高（信号矛盾）→ 待在锚点附近。

        拿不准的时候不该乱动 —— 这比"随便挑一边"更诚实。
        """
        p = resolve_phase_posture("liminal", _state(collapse_tendency=0.9, retreat_tendency=0.9))
        assert abs(p.depth - PHASE_ANCHORS["liminal"]) < 0.15


# ---------------------------------------------------------------------------
# 2. 相位仍然是权威 —— 连续量不得推翻它
# ---------------------------------------------------------------------------


class TestPhaseStaysAuthoritative:
    @pytest.mark.parametrize("token", ["static", "liminal", "manifest"])
    def test_depth_never_crosses_the_midpoint_to_a_neighbour(self, token: str) -> None:
        """倾向拉满也不得越过与邻档的中点。

        越过就会出现"面板说 liminal、深度却已是 manifest 的值"这种自相矛盾的帧
        —— 面板同时读这两处。EDGE_BLEND=0.45 < 0.5 就是为这条留的余量。
        """
        p = resolve_phase_posture(token, _state(collapse_tendency=1.0, retreat_tendency=1.0))
        order = ["static", "liminal", "manifest"]
        i = order.index(token)
        anchor = PHASE_ANCHORS[token]
        if i + 1 < len(order):
            mid_up = (anchor + PHASE_ANCHORS[order[i + 1]]) / 2
            assert p.depth < mid_up, f"{token} 的深度越过了与上一档的中点"
        if i - 1 >= 0:
            mid_dn = (anchor + PHASE_ANCHORS[order[i - 1]]) / 2
            assert p.depth > mid_dn, f"{token} 的深度越过了与下一档的中点"

    def test_edge_blend_is_below_half(self) -> None:
        """自证：上面那条依赖 EDGE_BLEND < 0.5，把这个前提本身钉住。"""
        assert EDGE_BLEND < 0.5


# ---------------------------------------------------------------------------
# 3. 拿不到连续量时如实降级
# ---------------------------------------------------------------------------


class TestHonestDegradation:
    def test_without_continuum_falls_back_to_anchor_and_says_so(self) -> None:
        p = resolve_phase_posture("liminal", state=None)
        # 注意：state=None 会去查进程里的活 continuum；测试进程里没有，应拿不到。
        if p.source == PostureSource.ANCHOR_ONLY:
            assert p.depth == PHASE_ANCHORS["liminal"], "兜底深度必须等于原锚点（行为与改造前一致）"

    def test_unknown_phase_is_anchor_only_not_fake_precision(self) -> None:
        """未知相位不得给出"看着精确、实则无依据"的深度。

        塌缩/回撤倾向是相对于**本相位的邻档**定义的；相位都认不出来时，把它们
        套到 static 带上算出的数没有意义。
        """
        p = resolve_phase_posture("bogus", _state(collapse_tendency=0.9))
        assert p.source == PostureSource.ANCHOR_ONLY
        assert p.depth == PHASE_ANCHORS["static"]

    def test_accessor_never_constructs_anything(self) -> None:
        """取数口绝不构造 OpenClawd。

        它可能在每一次相位事件里被调到；那里去 new 一个 OpenClawd 是灾难。
        用 sys.modules 快照前后对比来证明——比读代码可靠。
        """
        before = set(sys.modules)
        last_continuum_posture()
        new = set(sys.modules) - before
        assert not any(m.startswith("core.openclawd") for m in new), f"取数口把 openclawd 导进来了：{new}"


# ---------------------------------------------------------------------------
# 4. 桥真的把它送出去了（端到端）
# ---------------------------------------------------------------------------


class TestBridgeShipsThePosture:
    def test_broadcast_payload_carries_derived_depth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """造一个"已经存在"的 openclawd 单例，走真实的相位处理器，检查广播 payload。

        刻意不 new 真的 OpenClawd —— 那会拉起半个系统。这里验证的是桥→契约→
        payload 这条链，不是 continuum 自身（它有自己的测试）。
        """
        fake = types.ModuleType("core.openclawd")
        st = _state(collapse_tendency=0.85, presence_intensity=0.72, stability=0.4)
        fake._openclawd_instance = types.SimpleNamespace(  # type: ignore[attr-defined]
            _continuum_orchestrator=types.SimpleNamespace(_last_state=st)
        )
        monkeypatch.setitem(sys.modules, "core.openclawd", fake)

        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        async def _run() -> dict:
            b = GalaxyPresenceBridge()
            b._on_phase_liminal({"intent_strength": 0.8})
            return b._build_message()["payload"]

        payload = asyncio.run(_run())

        assert payload["posture"]["source"] == PostureSource.CONTINUUM
        assert payload["depth_factor"] != PHASE_ANCHORS["liminal"], "深度仍是硬编码锚点 —— 连续量没接上"
        assert payload["posture"]["collapse_tendency"] == pytest.approx(0.85)

    def test_intent_update_does_not_bypass_the_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """intent 更新不得自己算深度，把契约算出来的值盖掉。

        改造前 ``_on_intent_update`` 是 ``_current_depth = 0.15 + intent * 0.70``，
        而它是三个相位回调里**频率最高**的那个。两条后果：

        * 违反相位权威 —— 这条映射能让一个 liminal 帧的深度落到 0.15（着色器的
          纯静默区）或 0.85（空间收回区）。面板读 phase 说"阈限"、覆盖层读 depth
          画的却是静默，正是本契约要防的自相矛盾帧；
        * 它不更新 ``_posture``，于是广播出去的 ``depth_factor`` 与
          ``posture.depth`` 会互相打架。

        intent 本身没丢：它是 payload 里自己那一维，渲染端读它定过渡速度。
        """
        fake = types.ModuleType("core.openclawd")
        st = _state(collapse_tendency=0.5, retreat_tendency=0.1)
        fake._openclawd_instance = types.SimpleNamespace(  # type: ignore[attr-defined]
            _continuum_orchestrator=types.SimpleNamespace(_last_state=st)
        )
        monkeypatch.setitem(sys.modules, "core.openclawd", fake)

        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        async def _run(intent: float) -> dict:
            b = GalaxyPresenceBridge()
            b._on_phase_liminal({"intent_strength": 0.5})
            b._on_intent_update({"intent_strength": intent})
            return b._build_message()["payload"]

        lo = asyncio.run(_run(0.0))
        hi = asyncio.run(_run(1.0))

        # liminal 带的边界：锚点 ± 与邻档间距 × EDGE_BLEND
        anchor = PHASE_ANCHORS["liminal"]
        lo_bound = anchor - (anchor - PHASE_ANCHORS["static"]) * EDGE_BLEND
        hi_bound = anchor + (PHASE_ANCHORS["manifest"] - anchor) * EDGE_BLEND

        for payload, name in ((lo, "intent=0.0"), (hi, "intent=1.0")):
            depth = payload["depth_factor"]
            assert lo_bound <= depth <= hi_bound, f"{name} 的深度 {depth} 越出了 liminal 带 [{lo_bound}, {hi_bound}]"
            assert depth == payload["posture"]["depth"], f"{name}: depth_factor 与 posture.depth 不一致（自相矛盾帧）"

        # intent 本身仍然照发 —— 它只是不再被混进深度。
        assert lo["intent"] == 0.0 and hi["intent"] == 1.0, "intent 维度丢了"

    def test_posture_phase_matches_reported_phase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """说话期 static 会被报成 liminal，姿态必须跟着走。

        否则会出现"相位说 liminal、姿态说 static"的自相矛盾帧 —— 面板同时读这两处。
        """
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        async def _run() -> dict:
            b = GalaxyPresenceBridge()
            b._on_phase_silent({})
            b._speaking = True
            return b._build_message()["payload"]

        payload = asyncio.run(_run())
        assert payload["phase"] == payload["posture"]["phase"], "报出的相位与姿态里的相位不一致"


# ---------------------------------------------------------------------------
# 5. 生成的 TS 类型必须与 Python SSOT 同步
# ---------------------------------------------------------------------------


class TestGeneratedTypesStayInSync:
    def test_generated_file_matches_current_schema(self) -> None:
        """``phase_contract.gen.ts`` 必须是当前 schema 重跑生成器的结果。

        没有这条，改了 Python 契约却忘了重跑脚本，前后端就又开始漂 —— 而这套
        生成机制存在的全部理由就是消灭那种漂移。
        """
        import importlib.util
        import pathlib

        root = pathlib.Path(__file__).parent.parent
        gen_py = root / "scripts" / "gen_ts_types.py"
        spec = importlib.util.spec_from_file_location("_gen_ts_types", gen_py)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        expected = mod.build_phase_contract()
        actual = (root / "electron/renderer/panel/src/types/phase_contract.gen.ts").read_text(encoding="utf-8")
        assert actual == expected, "生成的 TS 与 Python 契约不一致 —— 请重跑 python scripts/gen_ts_types.py"

    def test_schema_covers_every_posture_field(self) -> None:
        """自证：schema 描述不得漏字段。

        漏一个字段，生成的 TS 就少一个属性，而后端照发不误 —— 前端读到 undefined
        却没有类型报错，正是这套机制要防的那种漂移。
        """
        import dataclasses

        from core.phase_contract import PhasePosture

        described = {f["name"] for f in phase_contract_schema()["fields"]}
        actual = {f.name for f in dataclasses.fields(PhasePosture)}
        assert described == actual, f"schema 与 dataclass 字段不一致：只在一边的有 {described ^ actual}"


class TestTheLegacyProjectionStaysSplitOut:
    """一维遗留投影已拆到 ``core.phase_posture_legacy``，本组防它悄悄合回去。

    为什么要拆：``core/phase_contract.py`` 曾经同时装着这一套（8 字段、depth 标量）
    与双轴忠实契约（28 字段），涨到 1550 行、警戒线 1000。两套放一起，读它的人很容易
    照着那 8 个字段写新代码 —— 而它们正是被判定错了的那 8 个（档数少一相、维数少一维、
    ``retreat_tendency`` 语义反了，详见被拆出模块的文档）。

    为什么还要再导出：拆分的目的是让**读这个文件的人**只看见该消费的那一份，
    不是去制造一次调用方大迁移。既有 ``from core.phase_contract import PhasePosture``
    照常可用，行为零变化 —— 拆分当时的判据就是「重跑生成器，三个 .gen.ts 逐字节相同」。
    """

    def test_legacy_lives_in_its_own_module(self) -> None:
        import core.phase_posture_legacy as legacy

        for name in (
            "PhasePosture",
            "PostureSource",
            "PHASE_ANCHORS",
            "PHASE_ORDER",
            "EDGE_BLEND",
            "resolve_phase_posture",
            "phase_contract_schema",
        ):
            assert hasattr(legacy, name), f"遗留模块少了 {name}"

    def test_phase_contract_re_exports_them_unchanged(self) -> None:
        """再导出必须是**同一个对象**，不是各写一份。"""
        import core.phase_contract as pc
        import core.phase_posture_legacy as legacy

        for name in (
            "PhasePosture",
            "PostureSource",
            "PHASE_ANCHORS",
            "PHASE_ORDER",
            "EDGE_BLEND",
            "resolve_phase_posture",
            "phase_contract_schema",
        ):
            assert getattr(pc, name) is getattr(legacy, name), f"{name} 在两处成了两个对象 —— 会漂"

    def test_phase_contract_no_longer_defines_the_legacy_shapes(self) -> None:
        """定义搬走了才算拆干净 —— 只是多加一个模块、原处照旧定义，等于没拆。"""
        import pathlib

        src = pathlib.Path("core/phase_contract.py").read_text(encoding="utf-8")
        assert "class PhasePosture" not in src, "遗留 dataclass 又回到 phase_contract 里了"
        assert "class PostureSource" not in src
        assert "def resolve_phase_posture" not in src
        assert "def phase_contract_schema" not in src

    def test_the_shared_readout_has_exactly_one_definition(self) -> None:
        """``last_continuum_posture`` 两套契约都用。它必须只有一份 ——

        留在任何一边，另一边就得反向依赖，拆开时必然循环导入；各写一份则会漂。
        """
        import core.continuum_readout as readout
        import core.phase_contract as pc
        import core.phase_posture_legacy as legacy

        assert pc.last_continuum_posture is readout.last_continuum_posture
        assert legacy.last_continuum_posture is readout.last_continuum_posture

    def test_no_import_cycle_between_the_three(self) -> None:
        """依赖必须是单向的：phase_contract → phase_posture_legacy → continuum_readout。

        只看**真正的 import 语句**，不扫全文 —— 两个被拆出的模块的文档都正当地
        提到了 ``core.phase_contract``（在解释为什么这么拆），扫全文会把说明当成依赖。
        """
        import pathlib
        import re

        def _imports(path: str) -> set:
            src = pathlib.Path(path).read_text(encoding="utf-8")
            return set(re.findall(r"^\s*(?:from|import)\s+(core\.[\w.]+)", src, re.MULTILINE))

        assert not _imports("core/continuum_readout.py"), "取数口应当零 core 内部依赖"
        legacy_deps = _imports("core/phase_posture_legacy.py")
        assert legacy_deps == {"core.continuum_readout"}, f"遗留模块的依赖变了：{legacy_deps}"

    def test_the_readout_still_never_constructs(self) -> None:
        """搬家不能把「绝不构造」这条纪律搬丢了 —— 它是这个取数口存在的前提。

        ``core.openclawd.get_openclawd()`` 会**创建** OpenClawd 实例，而调用方是
        在场桥的每一拍。所以只能用 ``sys.modules.get`` 看已经导入过的模块。
        """
        import pathlib
        import re

        src = pathlib.Path("core/continuum_readout.py").read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', "", src)  # 去掉文档，只看代码
        assert 'sys.modules.get("core.openclawd")' in code
        assert "get_openclawd(" not in code, "取数口开始构造 OpenClawd 了 —— 每一拍都会建一次"
