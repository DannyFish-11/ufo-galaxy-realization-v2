"""模态协商的第三维:设备 —— 契约测试
========================================

协商此前只算两维:"模型声明"×"服务现实"。两维都过就宣布可用 —— 但真正要在**哪台
设备**上做,它不知道。手表没有摄像头,协商照样说 vision_in=native,于是常驻注意力
循环去要一帧图像,永远要不到,链路在别处超时,日志里写的是"取帧超时",没有一处
会说"这台设备根本没有摄像头"。

这里验两件事,而且第二件比第一件更要紧:

1. 设备确实缺硬件时,协商如实降为 unavailable,并把 ``limited_by`` 标成 ``device``
   (而不是让调用方去正则匹配那句中文来区分"换模型能用"和"换设备才能用")。
2. **未知不设卡**:设备没报能力、报的词不在模态词汇里、device_id 查不到、UDM 挂了
   —— 全都必须不改变协商结果。能力表是各注册方自行填的,把"没写"当成"没有"会
   凭空关掉一堆本来能用的东西,而且同样无从归因。
"""

from __future__ import annotations

import pytest


class _FullOmniModel:
    """一个声明了全部原生模态的档位。"""

    vision = "native"
    audio_in = "native"
    audio_out = "native"
    video = "native"


@pytest.fixture()
def omni(monkeypatch):
    """全模态模型 + 服务已开 + 桥齐全 —— 两维全绿,只剩设备维能改变结果。"""
    monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
    monkeypatch.setenv("GALAXY_NATIVE_VIDEO", "1")
    return _FullOmniModel()


def _negotiate(omni, device):
    from core.modality_capability import negotiate

    return negotiate(effio=omni, device=device, asr_available=True, tts_available=True)


class TestDeviceGating:
    def test_watch_without_camera_loses_vision_and_video(self, omni):
        """手表:有麦克风有喇叭,没有摄像头。听说照旧,看必须关掉。"""
        watch = {"device_id": "watch-1", "capabilities": ["microphone", "speaker"]}
        plan = _negotiate(omni, watch)

        assert plan.audio_in.mode == "native"
        assert plan.audio_out.mode == "native"
        assert plan.vision_in.mode == "unavailable"
        assert plan.video_in.mode == "unavailable"

    def test_reason_attributes_the_limit_to_the_device(self, omni):
        watch = {"device_id": "watch-1", "capabilities": ["microphone", "speaker"]}
        vision = _negotiate(omni, watch).vision_in

        assert vision.limited_by == "device", "必须能机器可读地区分是设备限制"
        assert "watch-1" in vision.reason
        # 模型本身是有视觉的 —— 这个事实不能被设备门控抹掉,否则"换台设备就能用"
        # 这个信息就丢了。
        assert vision.native_capable is True

    def test_phone_with_full_hardware_is_unaffected(self, omni):
        phone = {"device_id": "phone-1", "capabilities": ["camera", "microphone", "speaker", "screen"]}
        plan = _negotiate(omni, phone)

        assert all(
            plan.get(m).mode == "native" for m in ("vision_in", "audio_in", "audio_out", "video_in")
        ), plan.to_dict()

    def test_headless_device_loses_audio(self, omni):
        """只有屏幕、没有麦克风喇叭的设备(比如一块信息屏)。"""
        panel = {"device_id": "panel-1", "capabilities": ["screen"]}
        plan = _negotiate(omni, panel)

        assert plan.vision_in.mode == "native"
        assert plan.audio_in.mode == "unavailable"
        assert plan.audio_out.mode == "unavailable"

    def test_gate_only_narrows_never_widens(self, monkeypatch):
        """设备再全能,也不能把模型/服务判死的模态救活。"""
        from core.modality_capability import negotiate

        class _TextOnly:
            vision = "none"
            audio_in = "asr_bridge"
            audio_out = "tts_bridge"
            video = "none"

        loaded = {"device_id": "phone-1", "capabilities": ["camera", "microphone", "speaker", "screen"]}
        plan = negotiate(effio=_TextOnly(), device=loaded, asr_available=False, tts_available=False)

        assert plan.vision_in.mode == "unavailable"
        assert plan.vision_in.limited_by == "model", "这是模型没有视觉,不该被记成设备的问题"
        assert plan.audio_in.mode == "unavailable"

    def test_device_id_is_carried_on_the_plan(self, omni):
        plan = _negotiate(omni, {"device_id": "watch-1", "capabilities": ["microphone"]})
        assert plan.to_dict()["device_id"] == "watch-1"

    def test_capability_synonyms_are_accepted(self, omni):
        """各注册方用词不统一。判"没有"就要关掉一个模态,不能因为写法不同就误判。"""
        dev = {"device_id": "d", "capabilities": ["mic", "screen_capture"]}
        plan = _negotiate(omni, dev)

        assert plan.audio_in.mode == "native", "mic 就是 microphone"
        assert plan.vision_in.mode == "native", "screen_capture 也能取到画面"

    def test_capabilities_are_case_insensitive(self, omni):
        dev = {"device_id": "d", "capabilities": ["MICROPHONE", " Camera "]}
        plan = _negotiate(omni, dev)
        assert plan.audio_in.mode == "native"
        assert plan.vision_in.mode == "native"


class TestUnknownMeansNoGating:
    """未知不设卡 —— 这一组比上一组更要紧:它守的是"不要凭空关掉能用的东西"。"""

    def test_no_device_behaves_exactly_as_before(self, omni):
        from core.modality_capability import negotiate

        without = negotiate(effio=omni, asr_available=True, tts_available=True).to_dict()
        with_none = negotiate(effio=omni, device=None, asr_available=True, tts_available=True).to_dict()
        assert without == with_none

    def test_device_reporting_nothing_is_not_gated(self, omni):
        """能力表空 = 没人填过,不等于这台设备什么都没有。"""
        plan = _negotiate(omni, {"device_id": "mystery", "capabilities": []})
        assert all(plan.get(m).mode == "native" for m in ("vision_in", "audio_in", "audio_out", "video_in"))

    def test_device_speaking_a_different_vocabulary_is_not_gated(self, omni):
        """报的全是别的维度的能力(键鼠/自动化),说明它压根没在讲模态这件事。"""
        plan = _negotiate(omni, {"device_id": "d", "capabilities": ["keyboard", "touch", "ui_automation"]})
        assert all(plan.get(m).mode == "native" for m in ("vision_in", "audio_in", "audio_out", "video_in"))

    def test_unknown_device_id_is_not_gated(self, omni, monkeypatch):
        """查不到设备 ≠ 设备没有摄像头。"""
        import core.modality_capability as mod

        monkeypatch.setattr(mod, "_lookup_device", lambda did: None)
        plan = _negotiate(omni, "device-that-does-not-exist")
        assert plan.vision_in.mode == "native"

    def test_udm_failure_is_not_gating(self, omni, monkeypatch):
        """设备源挂了就不做门控 —— 不能因为查不到就把用户的模态全关了。"""
        import core.unified.device_manager as udm

        def _boom():
            raise RuntimeError("UDM down")

        monkeypatch.setattr(udm, "get_unified_device_manager", _boom)
        plan = _negotiate(omni, "some-device")
        assert plan.vision_in.mode == "native"


class TestGateObject:
    def test_from_unified_device_object(self):
        """真的 UnifiedDevice 对象(不是 dict)也要能读。"""
        from core.modality_capability import DeviceModalityGate
        from core.unified.models import UnifiedDevice

        dev = UnifiedDevice(device_id="w1", capabilities=["microphone"])
        gate = DeviceModalityGate.from_device(dev)

        assert gate.device_id == "w1"
        assert gate.allows("audio_in") is True
        assert gate.allows("vision_in") is False

    def test_lookup_by_device_id(self, monkeypatch):
        import core.modality_capability as mod
        from core.modality_capability import DeviceModalityGate
        from core.unified.models import UnifiedDevice

        monkeypatch.setattr(
            mod,
            "_lookup_device",
            lambda did: UnifiedDevice(device_id=did, capabilities=["camera", "microphone"]),
        )
        gate = DeviceModalityGate.from_device("w2")
        assert gate.device_id == "w2"
        assert gate.allows("vision_in") is True

    def test_snapshot_flags_whether_gating_is_active(self):
        from core.modality_capability import DeviceModalityGate

        silent = DeviceModalityGate.from_device({"device_id": "a", "capabilities": ["keyboard"]})
        speaking = DeviceModalityGate.from_device({"device_id": "b", "capabilities": ["camera"]})

        assert silent.to_dict()["gating_active"] is False
        assert speaking.to_dict()["gating_active"] is True
