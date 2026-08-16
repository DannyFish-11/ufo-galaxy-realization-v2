"""tests/test_perception_grounding_stage_a.py
================================================
界面定位的权威归属（Stage A）。

要解决的问题
------------
「这一步点哪个控件」在仓库里有三份各自独立的实现：V2 的 ``ui_grounding``
（只有 Windows UIA 一个生产者）、V2 的 ``vision_pipeline``（自成一套形状）、
以及 Android 设备本地的 ``GroundingArbiter``（完整、有裁决矩阵与 JVM 单测）。
三者互不相识，而契约里 ``UISource.ANDROID_A11Y`` / ``VISION`` / ``OCR``
三个来源**声明了却零生产者**。

在这种状态下先把 a11y 树接上来是错的：没有归属约定，结果只会是第四份实现。
所以本阶段只做一件事——把判断规则写进代码，并让活路径真的去问它。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. AUTHORITY 声明自己不读、不算、不决定。
  A02. POLICY_1 每个平台恰有一个归属方。
  A03. POLICY_2 模型回复只能用于「选哪个」。
  A04. POLICY_3 服务端看得见 ≠ 可以覆盖设备裁决。

Group B — Ownership table
  B01. Android / WearOS 归设备。
  B02. 桌面三家归服务端。
  B03. 未知平台落到默认（服务端），不是无人负责。
  B04. 平台别名折叠到同一个答案。
  B05. 归属函数永不返回 None。

Group C — server_may_decide
  C01. 服务端归属 → 允许。
  C02. 设备归属 → 不允许，且理由指向 POLICY_1。
  C03. 理由恒非空——空理由分不清「政策不允许」与「能力缺失」。

Group D — 对外自述
  D01. describe 可 JSON 序列化。
  D02. 不带平台时给出全表。
  D03. 带平台时补上该平台的结论。

Group E — 活路径真的在问它
  E01. ui_act 响应里带 grounding_authority。
  E02. 设备归属的平台只规划、不派发。
  E03. 拒绝派发必须说出理由，不是静默不做。
  E04. 桌面平台不受影响（零行为变化）。
"""

from __future__ import annotations

import json

import pytest

from core.perception_grounding import (
    DEFAULT_OWNER,
    PLATFORM_GROUNDING_OWNER,
    GroundingOwner,
    describe_grounding_authority,
    grounding_owner_for,
    normalize_platform,
    server_may_decide,
)


class TestGroupAPolicies:
    def test_a01_authority_disclaims_deciding(self):
        from core.perception_grounding import PERCEPTION_GROUNDING_IS_AUTHORITY

        text = PERCEPTION_GROUNDING_IS_AUTHORITY
        assert "AUTHORITY" in text
        assert "reads no screen" in text
        assert "dispatches no action" in text

    def test_a02_policy_1_one_owner_per_platform(self):
        from core.perception_grounding import GROUNDING_HAS_ONE_OWNER_PER_PLATFORM_POLICY

        text = GROUNDING_HAS_ONE_OWNER_PER_PLATFORM_POLICY
        assert "POLICY_1" in text
        assert "exactly ONE owner" in text
        assert "second arbitration" in text

    def test_a03_policy_2_model_selects_only(self):
        from core.perception_grounding import MODEL_SELECTS_NEVER_SUPPLIES_POLICY

        text = MODEL_SELECTS_NEVER_SUPPLIES_POLICY
        assert "POLICY_2" in text
        assert "WHICH element" in text
        assert "never for" in text

    def test_a04_policy_3_seeing_is_not_deciding(self):
        from core.perception_grounding import SERVER_VIEW_NEVER_OVERRIDES_DEVICE_POLICY

        text = SERVER_VIEW_NEVER_OVERRIDES_DEVICE_POLICY
        assert "POLICY_3" in text
        assert "for SEEING, never for deciding" in text


class TestGroupBOwnership:
    @pytest.mark.parametrize("platform", ["android", "wearos"])
    def test_b01_mobile_is_device_owned(self, platform):
        assert grounding_owner_for(platform) is GroundingOwner.DEVICE

    @pytest.mark.parametrize("platform", ["windows", "linux", "macos"])
    def test_b02_desktop_is_server_owned(self, platform):
        assert grounding_owner_for(platform) is GroundingOwner.SERVER

    def test_b03_unknown_falls_to_a_named_default(self):
        """未登记的平台必须有人负责 —— 答'不知道'等于没人决定。"""
        assert grounding_owner_for("some_future_os") is DEFAULT_OWNER
        assert DEFAULT_OWNER is GroundingOwner.SERVER

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Android", "android"),
            ("ANDROID_PHONE", "android"),
            ("wear_os", "wearos"),
            ("Win32", "windows"),
            ("Darwin", "macos"),
            ("  browser ", "web"),
        ],
    )
    def test_b04_aliases_fold_to_one_answer(self, raw, expected):
        assert normalize_platform(raw) == expected
        assert grounding_owner_for(raw) is PLATFORM_GROUNDING_OWNER[expected]

    def test_b05_never_returns_none(self):
        for value in ("", "   ", "??", "android"):
            assert isinstance(grounding_owner_for(value), GroundingOwner)


class TestGroupCMayDecide:
    def test_c01_server_owned_is_allowed(self):
        allowed, reason = server_may_decide("windows")
        assert allowed is True
        assert reason

    def test_c02_device_owned_is_refused_with_policy_reference(self):
        allowed, reason = server_may_decide("android")
        assert allowed is False
        assert "POLICY_1" in reason
        assert "GroundingArbiter" in reason

    def test_c03_reason_is_never_empty(self):
        """空理由会让「政策不允许」与「能力缺失」看起来一样,而两者的修法不同。"""
        for platform in ("android", "windows", "totally_unknown", ""):
            _, reason = server_may_decide(platform)
            assert reason.strip(), f"{platform!r} 的判断没有给出理由"


class TestGroupDSelfDescription:
    def test_d01_json_safe(self):
        json.dumps(describe_grounding_authority("android"))

    def test_d02_without_platform_lists_the_whole_table(self):
        payload = describe_grounding_authority()
        assert payload["owners"]["android"] == "device"
        assert payload["owners"]["windows"] == "server"
        assert payload["default_owner"] == DEFAULT_OWNER.value
        assert "platform" not in payload

    def test_d03_with_platform_adds_the_verdict(self):
        payload = describe_grounding_authority("Android")
        assert payload["platform"] == "android"
        assert payload["owner"] == "device"
        assert payload["server_may_decide"] is False
        assert payload["reason"]


class TestGroupELivePath:
    """判据只有被活路径问到才算生效 —— 否则它就是一段写得很好的注释。"""

    @staticmethod
    def _graph():
        from core.schemas.ui_element import UIBounds, UIElementNode, UIGraph, UISource

        root = UIElementNode(
            role="root",
            children=[
                UIElementNode(
                    role="button",
                    label="发送",
                    clickable=True,
                    bounds=UIBounds(x=1180, y=2020, width=120, height=80),
                )
            ],
        )
        return UIGraph(root=root, source=UISource.UIA, device_id="d1").model_dump(mode="json")

    @pytest.mark.asyncio
    async def test_e01_response_states_who_owns_this_platform(self):
        from core.routes.ui_act import UIActRequest, ui_act

        out = await ui_act(
            UIActRequest(instruction="点发送", ui_graph=self._graph(), platform="windows", execute=False)
        )
        assert out["success"] is True
        assert out["grounding_authority"]["owner"] == "server"

    @pytest.mark.asyncio
    async def test_e02_device_owned_platform_plans_but_does_not_dispatch(self):
        from core.routes.ui_act import UIActRequest, ui_act

        out = await ui_act(UIActRequest(instruction="点发送", ui_graph=self._graph(), platform="android", execute=True))
        assert out["dispatched"] is False
        assert out["planned"]["label"] == "发送", "拒绝派发不等于拒绝规划"

    @pytest.mark.asyncio
    async def test_e03_refusal_is_spoken_not_silent(self):
        from core.routes.ui_act import UIActRequest, ui_act

        out = await ui_act(UIActRequest(instruction="点发送", ui_graph=self._graph(), platform="android", execute=True))
        assert "dispatch_declined" in out, "静默不派发与派发失败在现场分不开"
        assert "POLICY_1" in out["dispatch_declined"]

    @pytest.mark.asyncio
    async def test_e04_desktop_path_is_unchanged(self):
        """默认档位零行为变化:不带 platform 的老调用方一律照旧。"""
        from core.routes.ui_act import UIActRequest, ui_act

        out = await ui_act(UIActRequest(instruction="点发送", ui_graph=self._graph(), execute=False))
        assert out["success"] is True
        assert "dispatch_declined" not in out
