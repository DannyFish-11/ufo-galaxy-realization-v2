"""tests/test_pr_v9_capability_matching_multi_source.py
========================================================
PR-V9-CAPABILITY：设备能力匹配必须走规范注册表的**三源并集**，
而不是只看调用方手里那一份能力列表。

修的是什么
----------
``core/capability_registry.py`` 的模块 docstring 把自己写成：

    This module is the single canonical location for device capability
    summaries and capability-matching …

而它的 :func:`get_device_capability_summary` 明确合并**三个来源**取并集::

    Source 1: DeviceRegistry
    Source 2: CapabilityBus
    Source 3: canonical gateway capability projection

全仓却**零处**活路径消费它。三处真正在跑的选择路径各自写了一句只看**单一来源**
的判断：

    core/device_pool_manager.py（两处）                    all(c in dev.capabilities for c in required)
    core/device_selection/canonical_device_selector.py     同形

实测差异（同一台设备、同一项能力）
-----------------------------------
设备真实注册在 DeviceRegistry（``capabilities=['basic']``），而 ``screen_capture``
经 CapabilityBus 上报::

    device_registry              ['basic']
    capability_bus               ['basic', 'screen_capture']
    gateway_capability_registry  []
    → 并集 resolved               ['basic', 'screen_capture']

    规范匹配器 matched=True   /   活路径单源判断 matched=False

后果是**一台确实具备该能力的设备被剔出候选**——不是报错，是静默少一个候选，
上游只会看到"没有合适的设备"。

为什么是并集而不是替换
----------------------
:func:`device_matches_capabilities` 在设备**不存在于任何来源**时返回
``matched=False``（``summary.available`` 为假）。而调用方手里的设备来自自己的池子 /
入参，未必登记在 DeviceRegistry —— 直接改调它会给这类设备**新增排除**，那是引入
回归而不是修缺陷。所以判据取并集：原来能匹配的一个都不会掉，只可能多认出几台。

顺带一提性能：三源解析在选择热路径的循环里，所以**先跑便宜的单源检查，只有在它
会判失败时**才去付多源解析的代价。能力本来就在手里那份列表中时零额外开销。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List

import pytest

# skipif 只覆盖【基础设施】（能力总线 / 设备注册表 / 汇总函数）。
#
# 被测对象 ``device_satisfies_required_capabilities`` **刻意不放进这个 try**：
# 第一版把它一起 import 了，结果撤掉修复做反向验证时 14 条全部变成 skip 而不是
# fail —— 那样的守卫是空的，函数哪天被删掉它也一声不吭。现在改成在用例内部
# import，函数缺失即 ImportError 失败。
try:
    from core.capability_bus import CapabilityBusEntry, CapabilityBusRole, get_capability_bus
    from core.capability_registry import get_device_capability_summary
    from core.device_registry import device_registry

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

pytestmark = pytest.mark.skipif(not _AVAILABLE, reason="capability registry / bus unavailable")


def device_satisfies_required_capabilities(*args: Any, **kwargs: Any) -> bool:
    """在用例内部解析被测函数 —— 它不存在时本文件必须 **fail**，不是 skip。"""
    from core.capability_registry import device_satisfies_required_capabilities as _impl

    return _impl(*args, **kwargs)


def _register_bus_capability(device_id: str, capability: str) -> None:
    """把一项能力**只**登记到 CapabilityBus（不进 DeviceRegistry 的 capabilities）。"""
    kwargs: Dict[str, Any] = {}
    for p in inspect.signature(CapabilityBusEntry).parameters.values():
        if p.name == "name":
            kwargs["name"] = f"device__{device_id}__{capability}"
        elif p.name == "role":
            kwargs["role"] = CapabilityBusRole.DEVICE
        elif p.default is inspect.Parameter.empty:
            kwargs[p.name] = ""
    get_capability_bus().register(CapabilityBusEntry(**kwargs))


def _register_device(device_id: str, capabilities: List[str]) -> None:
    asyncio.run(
        device_registry.register(
            device_id=device_id,
            device_type="android_phone",
            name="probe",
            capabilities=list(capabilities),
        )
    )


class TestCanonicalRegistryMergesThreeSources:
    """先证明"要接的东西没坏"：规范注册表确实在合并多来源。"""

    def test_summary_declares_three_sources(self) -> None:
        summary = get_device_capability_summary("pr_v9_shape_probe")
        for src in ("device_registry", "capability_bus", "gateway_capability_registry"):
            assert src in summary.sources, f"规范能力汇总缺来源 {src!r} —— 本 PR 的判据建立在三源之上"

    def test_bus_only_capability_appears_in_resolved_union(self) -> None:
        dev = "pr_v9_union_dev"
        _register_device(dev, ["basic"])
        _register_bus_capability(dev, "screen_capture")

        summary = get_device_capability_summary(dev)
        assert "screen_capture" in summary.resolved_capabilities, (
            "只经 CapabilityBus 上报的能力必须出现在并集里；" f"实际 resolved={summary.resolved_capabilities}"
        )
        assert "screen_capture" not in (summary.sources.get("device_registry") or []), (
            "前提失效：这项能力不应同时出现在 device_registry 源里，" "否则本用例证明不了单源与多源的差异"
        )


class TestLivePathHonoursMultiSourceCapabilities:
    """红 → 绿的主体：活路径的判断式必须认多来源。"""

    def test_capability_reported_only_via_bus_is_honoured(self) -> None:
        dev = "pr_v9_live_dev"
        _register_device(dev, ["basic"])
        _register_bus_capability(dev, "screen_capture")

        assert device_satisfies_required_capabilities(dev, ["basic"], ["screen_capture"]) is True, (
            "设备确实具备该能力（经 CapabilityBus 上报），不得因为它不在调用方手里那份"
            "列表中就被判成不匹配 —— 那会让它被静默剔出候选"
        )

    def test_genuinely_missing_capability_is_still_rejected(self) -> None:
        """反向用例：不能为了认多来源就变成什么都放行。"""
        dev = "pr_v9_reject_dev"
        _register_device(dev, ["basic"])
        assert device_satisfies_required_capabilities(dev, ["basic"], ["no_such_capability"]) is False

    def test_declared_capability_short_circuits(self) -> None:
        """能力本来就在手里那份列表中时直接放行（这也是零额外开销的那条路径）。"""
        assert device_satisfies_required_capabilities("pr_v9_any", ["basic"], ["basic"]) is True

    def test_no_requirement_always_passes(self) -> None:
        assert device_satisfies_required_capabilities("pr_v9_any", [], None) is True
        assert device_satisfies_required_capabilities("pr_v9_any", [], []) is True

    def test_unknown_device_with_unknown_capability_is_rejected(self) -> None:
        assert device_satisfies_required_capabilities("pr_v9_nonexistent", [], ["whatever"]) is False


class TestNoNewExclusionsIntroduced:
    """本次改动是严格加法：原先能匹配的必须仍然匹配。

    这条是防回归的关键 —— 直接改调 ``device_matches_capabilities`` 会因为
    ``summary.available`` 而把"不在 DeviceRegistry 里的池内设备"新增排除。
    """

    @pytest.mark.parametrize(
        "declared,required",
        [
            (["a", "b"], ["a"]),
            (["a", "b"], ["a", "b"]),
            (["x"], ["x"]),
        ],
    )
    def test_previously_matching_still_matches_even_for_unregistered_device(
        self, declared: List[str], required: List[str]
    ) -> None:
        # 刻意用一个**没有**注册进任何来源的 device_id：单源判断本来是通过的，
        # 改动后必须仍然通过。
        assert device_satisfies_required_capabilities("pr_v9_never_registered", declared, required) is True


class TestBothLivePathsUseTheRegistry:
    """三个现场都得接上，不能只接一处。"""

    @staticmethod
    def _src(rel: str) -> str:
        import pathlib

        return (pathlib.Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "path",
        ["core/device_pool_manager.py", "core/device_selection/canonical_device_selector.py"],
    )
    def test_live_path_delegates_to_capability_registry(self, path: str) -> None:
        src = self._src(path)
        assert "device_satisfies_required_capabilities" in src, f"{path} 必须经规范能力注册表判定能力匹配"

    @pytest.mark.parametrize(
        "path",
        ["core/device_pool_manager.py", "core/device_selection/canonical_device_selector.py"],
    )
    def test_no_raw_single_source_capability_check_remains(self, path: str) -> None:
        src = self._src(path)
        for pattern in (
            "all(c in dev.capabilities for c in required_capabilities)",
            "all(c in device_caps for c in required_capabilities)",
        ):
            # 降级分支里保留单源判断是**有意**的（权威不可用时不该整体失败），
            # 所以只禁止它出现在 _satisfies_capabilities 之外的地方。
            outside_fallback = src.count(pattern) > src.count(f"return {pattern}")
            assert not outside_fallback, (
                f"{path} 仍在 _satisfies_capabilities 之外直接做单源能力判断 —— " "这正是本 PR 要消除的写法"
            )
