"""tests/test_android_ui_snapshot_stage_c.py
================================================
Android 无障碍快照 → 统一控件契约（Stage C）。

要解决的问题
------------
两端各自都做完了，中间那根线不存在：Android 端 ``AccessibilityUiSnapshotProvider``
读树、剪枝、拍平，还修过节点未回收的真 bug；V2 端 ``UIGraph`` 契约里
``UISource.ANDROID_A11Y`` **声明了却零生产者**。设备一直在上报
``accessibility_ready: true``，而网关只拿它做设备选择评分（+5），
从没有任何链路把那棵树取回来。

本阶段补的就是那根线的 V2 端。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. POLICY_1 收到的快照只供"看得见"，不供覆盖设备裁决。
  A02. POLICY_2 搭既有上行，不新增消息类型。

Group B — 投影
  B01. 元素落成 ANDROID_A11Y 来源的节点。
  B02. LTRB → 左上角+宽高。
  B03. 类名 → 规范化 role；查不到落 view 而非 text。
  B04. text 为空时用 contentDescription 当标签。
  B05. EditText → editable。
  B06. 零面积框不作为坐标锚点。
  B07. 结构节点置信度为 1.0（它是系统对自身的陈述，不是对像素的推断）。
  B08. 蛇形/驼峰两种字段名都收。

Group C — 失败可区分
  C01. 非对象载荷。
  C02. 缺 elements。
  C03. 全部无效。
  C04. 三种说明彼此不同。

Group D — 存取
  D01. 收下后取得回。
  D02. 未上报过的设备说得出"没上报过"。
  D03. 过期快照不再作为当前界面交出。
  D04. 设备数有界。
  D05. 缺 device_id 拒收。
  D06. 坏载荷不抛异常（它跑在 WS 上行里）。
  D07. 统计可读。

Group E — 接线
  E01. 上行处理器会吸收该字段。
  E02. 字段默认不存在时整条链路不受影响。
  E03. ui_act 能用已存快照规划。
  E04. 但仍不派发（POLICY_1 未被本阶段削弱）。

Group F — 跨仓契约
  F01. Kotlin 线材的字段名与本侧投影器逐字对齐。

Group G — 可观测
  G01. /api/v1/ui/perception 说得出谁说了算、设备有没有在上报。
  G02. 因过期挡下的次数可读 —— 否则这条链路是不是在工作全靠猜。
"""

from __future__ import annotations

import pathlib
import re
import time

import pytest

from core.android_ui_snapshot import (
    ANDROID_CLASS_ROLE_MAP,
    SNAPSHOT_PAYLOAD_KEY,
    absorb_snapshot_payload,
    latest_graph_for,
    project_android_snapshot,
    snapshot_store_stats,
)
from core.schemas.ui_element import UISource


def _element(index=0, text="发送", desc="", cls="android.widget.Button", clickable=True, box=(1180, 2020, 1300, 2100)):
    left, top, right, bottom = box
    return {
        "index": index,
        "text": text,
        "contentDescription": desc,
        "className": cls,
        "clickable": clickable,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


def _snapshot(*elements):
    return {
        "packageName": "com.tencent.mm",
        "screenWidth": 1440,
        "screenHeight": 3200,
        "elements": list(elements) or [_element()],
    }


@pytest.fixture(autouse=True)
def _clean_store():
    import core.android_ui_snapshot as mod

    with mod._lock:
        mod._latest.clear()
        for key in mod._stats:
            mod._stats[key] = 0
    yield


class TestGroupAPolicies:
    def test_a01_seeing_is_not_deciding(self):
        from core.android_ui_snapshot import SNAPSHOT_IS_FOR_SEEING_POLICY

        text = SNAPSHOT_IS_FOR_SEEING_POLICY
        assert "POLICY_1" in text
        assert "never to decide with" in text

    def test_a02_rides_an_existing_uplink(self):
        from core.android_ui_snapshot import SNAPSHOT_RIDES_AN_EXISTING_UPLINK_POLICY

        text = SNAPSHOT_RIDES_AN_EXISTING_UPLINK_POLICY
        assert "POLICY_2" in text
        assert "No new message type" in text


class TestGroupBProjection:
    def test_b01_nodes_carry_the_a11y_source(self):
        graph, _ = project_android_snapshot(_snapshot(), device_id="d1")
        node = graph.find_by_label("发送")
        assert node is not None and node.source is UISource.ANDROID_A11Y

    def test_b02_ltrb_becomes_origin_and_size(self):
        graph, _ = project_android_snapshot(_snapshot(), device_id="d1")
        bounds = graph.find_by_label("发送").bounds
        assert (bounds.x, bounds.y, bounds.width, bounds.height) == (1180, 2020, 120, 80)
        assert bounds.center() == (1240, 2060)

    def test_b03_unknown_class_is_view_not_text(self):
        """说不上来是什么就别声称它是文字 —— 谎报成不可交互,模型就不会去点它。"""
        graph, _ = project_android_snapshot(
            _snapshot(_element(cls="com.example.FancyCustomThing", text="自绘")), device_id="d1"
        )
        assert graph.find_by_label("自绘").role == "view"
        assert ANDROID_CLASS_ROLE_MAP["button"] == "button"

    def test_b04_content_description_is_the_fallback_label(self):
        graph, _ = project_android_snapshot(_snapshot(_element(text="", desc="输入消息")), device_id="d1")
        assert graph.find_by_label("输入消息") is not None

    def test_b05_edittext_is_editable(self):
        graph, _ = project_android_snapshot(
            _snapshot(_element(text="", desc="输入消息", cls="android.widget.EditText")), device_id="d1"
        )
        assert graph.find_by_label("输入消息").editable is True

    def test_b06_zero_area_is_not_an_anchor(self):
        """零面积框看起来像有效坐标却点不中 —— 下游拿到它就不会再退回让模型看画面。"""
        graph, _ = project_android_snapshot(_snapshot(_element(text="坏的", box=(10, 10, 10, 10))), device_id="d1")
        node = graph.find_by_label("坏的")
        assert node is not None, "一个坏坐标不该让这个控件整个消失"
        assert node.bounds is None

    def test_b07_structural_nodes_are_certain(self):
        graph, _ = project_android_snapshot(_snapshot(), device_id="d1")
        assert graph.find_by_label("发送").confidence == 1.0

    def test_b08_accepts_snake_case_too(self):
        raw = _element(text="", desc="输入", cls="android.widget.EditText")
        raw["content_description"] = raw.pop("contentDescription")
        raw["class_name"] = raw.pop("className")
        payload = {"package_name": "x", "screen_width": 1, "screen_height": 2, "elements": [raw]}
        graph, _ = project_android_snapshot(payload, device_id="d1")
        assert graph.find_by_label("输入") is not None


class TestGroupCFailures:
    def test_c01_not_an_object(self):
        graph, note = project_android_snapshot("nope", device_id="d1")
        assert graph.root is None and "不是对象" in note

    def test_c02_missing_elements(self):
        graph, note = project_android_snapshot({"packageName": "x"}, device_id="d1")
        assert graph.root is None and "elements" in note

    def test_c03_all_invalid(self):
        graph, note = project_android_snapshot({"elements": ["x", 3]}, device_id="d1")
        assert graph.root is None and "全部跳过" in note

    def test_c04_notes_differ(self):
        notes = {
            project_android_snapshot("nope", device_id="d")[1],
            project_android_snapshot({}, device_id="d")[1],
            project_android_snapshot({"elements": ["x"]}, device_id="d")[1],
        }
        assert len(notes) == 3, "不同的失败给了同一句说明,等于没说"


class TestGroupDStore:
    def test_d01_absorb_then_read_back(self):
        assert absorb_snapshot_payload(_snapshot(), device_id="d1")[0] is True
        graph, note = latest_graph_for("d1")
        assert graph is not None and graph.find_by_label("发送") is not None
        assert "界面结构" in note

    def test_d02_unknown_device_says_so(self):
        graph, note = latest_graph_for("never-seen")
        assert graph is None and "尚未上报" in note

    def test_d03_stale_snapshot_is_declined(self, monkeypatch):
        """界面会变。把两分钟前的树当成现在的屏幕,调用方会规划一串点不中的动作。"""
        import core.android_ui_snapshot as mod

        absorb_snapshot_payload(_snapshot(), device_id="d1")
        with mod._lock:
            captured, graph = mod._latest["d1"]
            mod._latest["d1"] = (captured - mod._STALE_SECONDS - 1, graph)
        got, note = latest_graph_for("d1")
        assert got is None and "过期" in note

    def test_d04_device_cache_is_bounded(self):
        import core.android_ui_snapshot as mod

        for i in range(mod._MAX_DEVICES + 20):
            absorb_snapshot_payload(_snapshot(), device_id=f"d{i}")
            time.sleep(0)
        assert len(mod._latest) <= mod._MAX_DEVICES

    def test_d05_missing_device_id_is_refused(self):
        ok, note = absorb_snapshot_payload(_snapshot(), device_id="")
        assert ok is False and "device_id" in note

    def test_d06_bad_payload_never_raises(self):
        for payload in (None, 3, "x", {"elements": None}, {"elements": [{"left": "a"}]}):
            ok, note = absorb_snapshot_payload(payload, device_id="d1")
            assert ok is False and note

    def test_d07_stats_are_readable(self):
        absorb_snapshot_payload(_snapshot(), device_id="d1")
        absorb_snapshot_payload("bad", device_id="d1")
        latest_graph_for("d1")
        stats = snapshot_store_stats()
        assert stats["absorbed"] == 1
        assert stats["rejected"] == 1
        assert stats["served"] == 1


class TestGroupEWiring:
    def test_e01_uplink_handler_absorbs_the_field(self):
        import inspect

        from galaxy_gateway.websocket_handler import handle_device_perception_emission

        src = inspect.getsource(handle_device_perception_emission)
        assert SNAPSHOT_PAYLOAD_KEY in src
        assert "absorb_snapshot_payload" in src

    def test_e02_absent_field_changes_nothing(self):
        """字段默认不存在 —— 老设备的上行必须与改造前逐字节相同。"""
        import inspect

        from galaxy_gateway.websocket_handler import handle_device_perception_emission

        src = inspect.getsource(handle_device_perception_emission)
        assert f'payload.get("{SNAPSHOT_PAYLOAD_KEY}")' in src, "必须是取值判空,不能无条件调用"

    @pytest.mark.asyncio
    async def test_e03_ui_act_plans_from_a_stored_snapshot(self):
        from core.routes.ui_act import UIActRequest, ui_act

        absorb_snapshot_payload(_snapshot(), device_id="d1")
        out = await ui_act(UIActRequest(instruction="点发送", device_id="d1", platform="android", execute=False))
        assert out["success"] is True
        assert out["planned"]["label"] == "发送", "服务端已经看得见这一屏了"

    @pytest.mark.asyncio
    async def test_e04_still_does_not_dispatch_on_android(self):
        """看得见没有削弱归属:Android 仍归设备本地。"""
        from core.routes.ui_act import UIActRequest, ui_act

        absorb_snapshot_payload(_snapshot(), device_id="d1")
        out = await ui_act(UIActRequest(instruction="点发送", device_id="d1", platform="android", execute=True))
        assert out["dispatched"] is False
        assert "POLICY_1" in out["dispatch_declined"]


class TestGroupFCrossRepoContract:
    """字段名两边对不上时,表现是服务端静默收到一棵空树 —— 最难查的那种。"""

    def test_f01_kotlin_wire_fields_match_this_projector(self):
        kotlin = pathlib.Path("/home/user/ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt")
        if not kotlin.is_file():
            pytest.skip("android 仓不在本机,跳过跨仓字段对齐检查")
        text = kotlin.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"data class DeviceUiSnapshotPayload\((.*?)\n\}", text, re.S)
        assert block, "Kotlin 侧的线材载荷不见了 —— 这根线断了"
        body = block.group(1)
        for field in ("packageName", "screenWidth", "screenHeight", "elements"):
            assert field in body, f"Kotlin 载荷缺字段 {field}"
        for field in (
            "index",
            "text",
            "contentDescription",
            "className",
            "clickable",
            "left",
            "top",
            "right",
            "bottom",
        ):
            assert field in body, f"Kotlin 元素缺字段 {field}"
        assert SNAPSHOT_PAYLOAD_KEY in text, "Kotlin 侧没有把载荷挂到上行字段上"


class TestGroupGObservability:
    """不可见的链路等于不存在:传没传、被不被当成当前界面、挡下多少次,都得答得出。"""

    @pytest.mark.asyncio
    async def test_g01_perception_endpoint_reports_both(self):
        from core.routes.ui_act import ui_perception_state

        absorb_snapshot_payload(_snapshot(), device_id="d1")
        out = await ui_perception_state()
        assert out["authority"]["owners"]["android"] == "device"
        assert out["android_ui_snapshot"]["absorbed"] == 1
        assert out["android_ui_snapshot"]["devices"] == 1

    @pytest.mark.asyncio
    async def test_g02_stale_declines_are_counted(self, monkeypatch):
        import core.android_ui_snapshot as mod
        from core.routes.ui_act import ui_perception_state

        absorb_snapshot_payload(_snapshot(), device_id="d1")
        with mod._lock:
            captured, graph = mod._latest["d1"]
            mod._latest["d1"] = (captured - mod._STALE_SECONDS - 1, graph)
        latest_graph_for("d1")
        out = await ui_perception_state()
        assert out["android_ui_snapshot"]["stale_declined"] == 1
