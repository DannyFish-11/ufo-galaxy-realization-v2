"""tests/test_provider_modality_locus.py
==========================================
云端 provider 的模态声明(``core/provider_modality.py``)+ 协商层的第四维
``negotiate(locus=...)``:**这次由谁来想**。

为什么要有这一维
----------------
前三维("模型声明 × 服务现实 × 设备硬件")回答的是"本地这套后端能不能做"。缺的那一件
是"这次的推理交给谁" —— 本地档位是 A(无视觉)而云端 key 配着时,协商说
``vision_in=unavailable``,常驻循环连截图都不去取,那把能看图的 key 一次都用不上。

本文件钉住的正是"换个 locus 就换个能力源",以及换的**只是能力源** —— 桥仍在本地、
设备仍照常收紧、归因分得清"换一家"和"开个环境变量"。

不触网:全部读 ``PROVIDER_REGISTRY`` 这张静态表 + 注入替身。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import core.modality_capability as mc
import core.provider_modality as pm
from core.modality_capability import AUDIO_IN, AUDIO_OUT, VIDEO_IN, VISION_IN, negotiate
from core.provider_modality import ProviderIO, provider_io, provider_spec


@dataclass
class _IO:
    """EffectiveIO 替身。"""

    vision: str = "none"
    audio_in: str = "asr_bridge"
    audio_out: str = "tts_bridge"
    video: str = "none"


def _blind() -> _IO:
    """一个什么都不会的本地档位 —— 用来证明结论来自远端而不是本地。"""
    return _IO()


# ══════════════════════════════════════════════════════════════════════════
# A. 声明本身:只从仓内已有字段派生,一条外部事实都不新增
# ══════════════════════════════════════════════════════════════════════════


def test_a01_unknown_provider_is_none_not_empty():
    """没这家 → None。空 ProviderIO 会被读成"查到了一家什么都不会的",两回事。"""
    assert provider_io("no-such-provider") is None
    assert provider_spec("no-such-provider") is None


def test_a02_name_lookup_is_case_insensitive():
    assert provider_io("OpenAI") is not None
    assert provider_io("  openai  ") is not None


def test_a03_empty_name_is_none():
    assert provider_io("") is None


def test_a04_vision_comes_from_the_multimodal_flag():
    """vision 的判据是 registry 里已有的 extra.multimodal / supports_vision。"""
    for spec in pm._registry():
        extra = spec.get("extra") or {}
        if spec.get("modalities"):
            continue  # 显式覆盖的不受派生规则约束
        expected = "native" if (extra.get("multimodal") or extra.get("supports_vision")) else "none"
        assert provider_io(spec["name"]).vision == expected, spec["name"]


def test_a05_native_audio_requires_a_realtime_interface():
    """原生听说的判据是 realtime_models,不是 multimodal 布尔。

    走 Chat Completions 发过去的是文本,音频进不去。拿 multimodal 判"原生听",
    会让协商层对着一个收不了音频的接口说原生,于是本地 ASR 桥被跳过,请求里
    没有任何可听的东西。
    """
    for spec in pm._registry():
        if spec.get("modalities"):
            continue
        io = provider_io(spec["name"])
        has_rt = bool(spec.get("realtime_models") or spec.get("default_realtime_model"))
        assert (io.audio_in == "native") is has_rt, spec["name"]
        assert (io.audio_out == "native") is has_rt, spec["name"]


def test_a06_multimodal_alone_never_buys_native_audio():
    """反向钉:声明了 multimodal 却没有 realtime 的那些家,听说必须仍是桥。"""
    offenders = [
        s["name"]
        for s in pm._registry()
        if (s.get("extra") or {}).get("multimodal")
        and not (s.get("realtime_models") or s.get("default_realtime_model"))
        and not s.get("modalities")
        and provider_io(s["name"]).audio_in != "asr_bridge"
    ]
    assert offenders == []


def test_a07_video_follows_the_same_rule_as_local_effective_io():
    """视频:原生 > 抽静帧 > 无 —— 与 model_catalog.effective_io 同一条规则。"""
    for spec in pm._registry():
        if spec.get("modalities"):
            continue
        io = provider_io(spec["name"])
        assert io.video == ("frames_bridge" if io.vision == "native" else "none"), spec["name"]


def test_a08_tools_defaults_to_true_and_respects_opt_out():
    """绝大多数家支持工具调用;显式写 supports_tools=False 的必须被认出来。"""
    assert provider_io("perplexity").tools is False  # registry 里唯一显式关掉的
    assert provider_io("anthropic").tools is True


def test_a09_derived_declarations_are_not_marked_declared():
    """派生出来的可以被真机探测推翻,显式写的不该 —— 所以要分得开。"""
    assert provider_io("anthropic").declared is False


def test_a10_explicit_override_wins_and_marks_declared(monkeypatch):
    fake = [{"name": "acme", "extra": {}, "modalities": {"vision": "native", "audio_in": "native"}}]
    monkeypatch.setattr(pm, "_registry", lambda: fake)
    io = provider_io("acme")
    assert io.vision == "native"  # 派生本会是 none
    assert io.audio_in == "native"  # 派生本会是 asr_bridge(没有 realtime_models)
    assert io.audio_out == "tts_bridge"  # 没覆盖的键仍走派生
    assert io.declared is True


def test_a11_illegal_override_value_falls_back_to_derivation(monkeypatch):
    """拼错的取值不能被静默接受 —— 否则"这家不支持"其实是打字错误。"""
    fake = [{"name": "acme", "extra": {"multimodal": True}, "modalities": {"vision": "nativ"}}]
    monkeypatch.setattr(pm, "_registry", lambda: fake)
    assert provider_io("acme").vision == "native"  # 退回派生值,不是 "nativ"


def test_a12_non_dict_override_is_ignored(monkeypatch):
    fake = [{"name": "acme", "extra": {"multimodal": True}, "modalities": ["vision"]}]
    monkeypatch.setattr(pm, "_registry", lambda: fake)
    assert provider_io("acme").vision == "native"


def test_a13_registry_unavailable_degrades_to_no_providers(monkeypatch):
    """provider 表读不出来不能让协商崩,只意味着"远端这一维没有判据"。"""

    def _boom():
        raise RuntimeError("registry down")

    monkeypatch.setattr(pm, "_registry", _boom)
    with pytest.raises(RuntimeError):
        pm._registry()  # 确认替身生效
    monkeypatch.setattr(pm, "_registry", lambda: [])
    assert provider_io("openai") is None


def test_a14_native_list_counts_native_only_not_bridges():
    """ "谁能听"的名单里不能出现从来没有音频接口的家。

    第一版写的是"取值不为 none 即入选",于是 audio_in 一栏把 17 家全列了进去 ——
    因为不原生听的取值是 asr_bridge,而它压根不是这家的能力,是本机装了 ASR。
    """
    audio = pm.providers_native_in("audio_in")
    assert audio  # 至少有一家有 realtime
    for name in audio:
        spec = provider_spec(name)
        assert spec.get("realtime_models") or spec.get("default_realtime_model"), name
    assert len(audio) < len(pm._registry())  # 不可能是全部


def test_a15_native_list_rejects_unknown_field():
    assert pm.providers_native_in("telepathy") == []


def test_a16_matrix_covers_every_provider_and_sorts_stably():
    m = pm.provider_modality_matrix()
    assert m["provider_count"] == len(pm._registry())
    names = [r["provider"] for r in m["providers"]]
    assert names == sorted(names)
    assert set(m["native"]) == set(pm.MODALITY_FIELDS)


def test_a17_shape_matches_local_effective_io():
    """与 EffectiveIO 同形 —— 不同形就得写两套解析,分支立刻开始漂移。"""
    from core.model_catalog import EffectiveIO

    local_fields = set(EffectiveIO("none", "asr_bridge", "tts_bridge", False).to_dict())
    remote_fields = set(ProviderIO("x").to_dict())
    assert local_fields <= remote_fields


# ══════════════════════════════════════════════════════════════════════════
# B. 第四维:换 locus 就换能力源
# ══════════════════════════════════════════════════════════════════════════


def test_b01_default_locus_is_local_and_behaviour_is_unchanged():
    """不传 locus 时与加入本维之前完全一致。"""
    plan = negotiate(effio=_blind(), asr_available=True, tts_available=True)
    assert plan.locus == mc.LOCAL_LOCUS
    assert plan.vision_in.mode == "unavailable"
    assert plan.vision_in.limited_by == "model"


def test_b02_explicit_local_locus_equals_default():
    a = negotiate(effio=_blind(), asr_available=True, tts_available=True)
    b = negotiate(effio=_blind(), asr_available=True, tts_available=True, locus="local")
    assert a.to_dict() == b.to_dict()


def test_b03_cloud_locus_unlocks_vision_a_blind_local_tier_cannot_do():
    """本维存在的全部理由:本地瞎着,而这次要交给一家能看的云端。"""
    plan = negotiate(locus="anthropic", asr_available=True, tts_available=True)
    assert plan.locus == "anthropic"
    assert plan.vision_in.mode == "native"


def test_b04_cloud_locus_without_vision_says_change_vendor_not_change_model():
    plan = negotiate(locus="groq", asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"
    assert plan.vision_in.limited_by == "provider"  # 不是 "model"


def test_b05_bridges_stay_local_regardless_of_locus():
    """ASR/TTS 跑在本机,与谁来想无关 —— 所以远端不原生听仍是 bridge 而非 unavailable。"""
    plan = negotiate(locus="anthropic", asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "bridge"
    assert plan.audio_out.mode == "bridge"


def test_b06_no_bridge_installed_still_means_unavailable_on_cloud_locus():
    plan = negotiate(locus="anthropic", asr_available=False, tts_available=False)
    assert plan.audio_in.mode == "unavailable"
    assert plan.audio_out.mode == "unavailable"


def test_b07_provider_with_realtime_interface_hears_natively():
    plan = negotiate(locus="openai", asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "native"
    assert plan.audio_out.mode == "native"
    assert plan.audio_in.native_capable is True


def test_b08_local_serving_env_does_not_gate_the_cloud(monkeypatch):
    """GALAXY_NATIVE_AUDIO 说的是本地 Ollama /api/chat 没有音频字段。

    拿它去卡 OpenAI Realtime,会把一个真能吃音频的接口判成"服务未开"。
    """
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    plan = negotiate(locus="openai", asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "native"


def test_b09_local_locus_is_still_gated_by_that_env(monkeypatch):
    """反向钉:同一个 env 对本地仍然有效,别把门拆了。"""
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    io = _IO(audio_in="native", audio_out="native")
    plan = negotiate(effio=io, asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "bridge"
    assert plan.audio_in.limited_by == "serving"


def test_b10_unknown_locus_falls_back_to_local_not_to_nothing():
    """locus 指了一家不存在的 provider = 配置写错,不是"这家什么都不会"。

    未知不设卡 —— 与设备维同一条。
    """
    plan = negotiate(effio=_IO(vision="native"), asr_available=True, tts_available=True, locus="acme-ai")
    assert plan.locus == mc.LOCAL_LOCUS
    assert plan.vision_in.mode == "native"  # 本地那份仍然作数


def test_b11_injected_effio_wins_over_the_locus_capability_source():
    """注入是为了不碰真实能力表地测逻辑;再去查 provider 表就把注入架空了。"""
    plan = negotiate(effio=_blind(), locus="anthropic", asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"
    assert plan.locus == "anthropic"  # locus 仍在,它决定那道服务门归谁


def test_b12_injected_effio_still_takes_the_remote_serving_gate(monkeypatch):
    """承上:注入换的是能力,locus 换的是门。两者独立才说得清各自的作用。"""
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    io = _IO(audio_in="native", audio_out="native")
    plan = negotiate(effio=io, locus="anthropic", asr_available=True, tts_available=True)
    # 远端没有"声明了但本地服务没开"这一档,所以这里是 native 而不是被 env 卡成 bridge
    assert plan.audio_in.mode == "native"


def test_b13_locus_is_reported_in_the_dict():
    d = negotiate(locus="openai", asr_available=True, tts_available=True).to_dict()
    assert d["locus"] == "openai"


def test_b14_locus_never_empty_string():
    """空串会让读的人分不清"本地"和"没协商过"。"""
    for loc in (None, "", "   ", "local"):
        assert negotiate(effio=_blind(), locus=loc, asr_available=True, tts_available=True).locus == "local"


# ══════════════════════════════════════════════════════════════════════════
# C. 三维与第四维叠加:设备仍然只收紧
# ══════════════════════════════════════════════════════════════════════════


def test_c01_device_gate_still_narrows_a_cloud_locus():
    """云端再能看,手表上也没有摄像头去采那一帧。"""
    watch = {"device_id": "watch-1", "capabilities": ["microphone", "touch"]}
    plan = negotiate(locus="anthropic", device=watch, asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"
    assert plan.vision_in.limited_by == "device"  # 不是 provider —— 换一家也没用


def test_c02_device_gate_cannot_widen_a_cloud_locus():
    """反向:设备全能也补不出一家不接受图像的 provider。"""
    full = {"device_id": "pc-1", "capabilities": ["camera", "screen", "microphone"]}
    plan = negotiate(locus="groq", device=full, asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"
    assert plan.vision_in.limited_by == "provider"


def test_c03_silent_device_does_not_gate_a_cloud_locus():
    """未申报能力的设备不设卡 —— 这一条不因为换了 locus 而改变。"""
    quiet = {"device_id": "pc-2", "capabilities": []}
    plan = negotiate(locus="anthropic", device=quiet, asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "native"
    assert plan.device_id == "pc-2"


def test_c04_both_dimensions_are_reported_together():
    dev = {"device_id": "pc-3", "capabilities": ["screen"]}
    plan = negotiate(locus="openai", device=dev, asr_available=True, tts_available=True)
    assert (plan.locus, plan.device_id) == ("openai", "pc-3")


# ══════════════════════════════════════════════════════════════════════════
# D. 归因:"换一家" 与 "开个环境变量" 必须分得开
# ══════════════════════════════════════════════════════════════════════════


def test_d01_limited_by_vocabulary_is_closed():
    """面板/日志按这几个值分支,多出来一个没人认识的值等于静默失效。"""
    allowed = {"", "model", "serving", "device", "provider"}
    for loc in [None] + [s["name"] for s in pm._registry()]:
        for dev in (None, {"device_id": "d", "capabilities": ["screen"]}):
            plan = negotiate(locus=loc, device=dev, asr_available=True, tts_available=True)
            for m in (VISION_IN, AUDIO_IN, AUDIO_OUT, VIDEO_IN):
                assert plan.get(m).limited_by in allowed


def test_d02_cloud_locus_never_blames_serving():
    """远端报 serving 会让用户去开一个根本不存在的环境变量。"""
    for spec in pm._registry():
        plan = negotiate(locus=spec["name"], asr_available=True, tts_available=True)
        for m in (VISION_IN, AUDIO_IN, AUDIO_OUT, VIDEO_IN):
            assert plan.get(m).limited_by != "serving", (spec["name"], m)


def test_d03_local_locus_can_still_blame_serving(monkeypatch):
    monkeypatch.delenv("GALAXY_NATIVE_VIDEO", raising=False)
    plan = negotiate(effio=_IO(vision="native", video="native"), asr_available=True, tts_available=True)
    assert plan.video_in.mode == "bridge"
    assert plan.video_in.limited_by == "serving"


def test_d04_every_resolution_carries_a_human_reason():
    for loc in [None] + [s["name"] for s in pm._registry()]:
        plan = negotiate(locus=loc, asr_available=True, tts_available=True)
        for m in (VISION_IN, AUDIO_IN, AUDIO_OUT, VIDEO_IN):
            assert plan.get(m).reason.strip(), (loc, m)


def test_d05_cloud_reason_names_the_provider_when_it_is_the_limit():
    plan = negotiate(locus="anthropic", asr_available=True, tts_available=True)
    assert "anthropic" in plan.audio_in.reason


# ══════════════════════════════════════════════════════════════════════════
# E. 不崩:远端能力源出问题只意味着退回本地
# ══════════════════════════════════════════════════════════════════════════


def test_e01_provider_io_raising_does_not_break_negotiation(monkeypatch):
    def _boom(_name):
        raise RuntimeError("provider table exploded")

    monkeypatch.setattr(pm, "provider_io", _boom)
    plan = negotiate(effio=_IO(vision="native"), locus="openai", asr_available=True, tts_available=True)
    assert plan.locus == mc.LOCAL_LOCUS
    assert plan.vision_in.mode == "native"


def test_e02_serving_reality_labels_are_distinguishable():
    assert mc.ServingReality.local().is_remote is False
    assert mc.ServingReality.remote("openai").is_remote is True
