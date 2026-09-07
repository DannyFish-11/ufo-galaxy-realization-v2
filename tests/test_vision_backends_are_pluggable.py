"""视觉后端:可插拔、有顺序、说得清数据出不出设备。

原来 ``core/vision_pipeline.analyze()`` 里是一条写死的 if 瀑布(Level 1..4)。
三个后果:加一档要改函数本体;"这一档的数据出不出设备"没有任何地方说得出来;
选了哪一档、为什么跳过前面的,事后查不到。

这组判据钉住改造后的三件事,以及**最要紧的那一条**:补上端侧 GUI 档之前,
"在本机"与"懂控件"在任何一档上都无法同时成立 —— 想要真正的界面理解就必须上云,
而这与本项目"数据不出设备"的立场正面冲突。
"""

import pytest

from core.vision_backends import (
    BACKEND_DEEPSEEK,
    BACKEND_GEMINI,
    BACKEND_LOCAL_GUI,
    BACKEND_QWEN_VL,
    BACKEND_TESSERACT,
    DEFAULT_ORDER,
    resolve_order,
)
from core.vision_pipeline import VisionPipeline


@pytest.fixture
def pipe(monkeypatch):
    for var in (
        "GALAXY_LOCAL_GUI_VLM_URL",
        "GALAXY_VISION_BACKEND_ORDER",
        "LOCAL_VLLM_URL",
        "DEEPSEEK_OCR2_API_KEY",
        "NOVITA_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return VisionPipeline()


class TestTheOrderIsOneAuthorityAndOverridable:
    def test_default_order_puts_the_on_device_backend_first(self):
        assert DEFAULT_ORDER[0] == BACKEND_LOCAL_GUI, "隐私是这个项目的立场,本地档该排最前"
        assert DEFAULT_ORDER[-1] == BACKEND_TESSERACT, "兜底档该在最后"

    def test_the_four_original_levels_keep_their_relative_order(self):
        """原来的四档先后一个字没变 —— 新增那一档只是插在最前面。"""
        original = [BACKEND_DEEPSEEK, BACKEND_GEMINI, BACKEND_QWEN_VL, BACKEND_TESSERACT]
        assert [n for n in DEFAULT_ORDER if n in original] == original

    def test_env_can_reorder(self):
        assert resolve_order("tesseract,gemini")[:2] == [BACKEND_TESSERACT, BACKEND_GEMINI]

    def test_a_backend_left_out_of_the_override_is_appended_not_dropped(self):
        """顺序可以改,但不该因为漏写就把一整档弄丢。"""
        assert set(resolve_order("gemini")) == set(DEFAULT_ORDER)

    def test_a_typo_is_reported_and_ignored_not_silently_swallowed(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            order = resolve_order("gemini,nonexistent-backend")
        assert "nonexistent-backend" in caplog.text, "打错名字必须吵一声"
        assert set(order) == set(DEFAULT_ORDER)

    @pytest.mark.parametrize("blank", ["", "   ", ",,,"])
    def test_blank_falls_back_to_default(self, blank):
        assert resolve_order(blank) == DEFAULT_ORDER


class TestEachBackendDeclaresWhatItReallyIs:
    def test_every_backend_is_registered(self, pipe):
        assert {b.name for b in pipe.backends()} == set(DEFAULT_ORDER)

    def test_cloud_backends_are_marked_as_leaving_the_device(self, pipe):
        by = {b.name: b for b in pipe.backends()}
        for name in (BACKEND_DEEPSEEK, BACKEND_GEMINI, BACKEND_QWEN_VL):
            assert by[name].local is False
            assert "云端" in by[name].privacy_note

    def test_tesseract_is_local_but_does_not_understand_controls(self, pipe):
        """这个 False 不是笔误:它认得出字,认不出"那是个按钮"。

        标成懂控件,就等于让上层以为界面理解一直有本地兜底 —— 并没有。
        """
        t = {b.name: b for b in pipe.backends()}[BACKEND_TESSERACT]
        assert t.local is True
        assert t.grounding is False

    def test_the_on_device_gui_backend_is_the_only_one_that_is_both(self, pipe):
        """**这条是这次改造的全部理由。**

        补它之前:云端三档懂控件但要把截图发出去,本地一档不出设备但只认字 ——
        "在本机"与"懂控件"凑不到一起。
        """
        both = [b.name for b in pipe.backends() if b.local and b.grounding]
        assert both == [BACKEND_LOCAL_GUI]

        others = [b for b in pipe.backends() if b.name != BACKEND_LOCAL_GUI]
        assert not any(b.local and b.grounding for b in others), "去掉端侧那档就不该有既本地又懂控件的"


class TestAvailabilityMatchesTheOldWaterfallExactly:
    """每一档的可用性判断都是从原来那条 if 瀑布逐条照搬的,不许走样。"""

    def test_nothing_configured_leaves_only_the_fallback(self, pipe):
        usable = [b.name for b in pipe.backends() if b.available(pipe)]
        assert usable == [BACKEND_TESSERACT]

    def test_tesseract_is_always_in_play(self, pipe):
        t = {b.name: b for b in pipe.backends()}[BACKEND_TESSERACT]
        assert t.available(pipe) is True

    def test_deepseek_accepts_either_its_key_or_a_local_vllm(self, pipe):
        by = {b.name: b for b in pipe.backends()}
        assert by[BACKEND_DEEPSEEK].available(pipe) is False
        pipe.local_vllm_url = "http://127.0.0.1:8000/v1"
        assert by[BACKEND_DEEPSEEK].available(pipe) is True

    def test_the_on_device_backend_is_skipped_when_not_configured(self, pipe):
        """没配就整档跳过 —— 这就是"对现有部署零影响"的全部含义。"""
        by = {b.name: b for b in pipe.backends()}
        assert by[BACKEND_LOCAL_GUI].available(pipe) is False
        pipe.local_gui_url = "http://127.0.0.1:9401/v1"
        assert by[BACKEND_LOCAL_GUI].available(pipe) is True

    @pytest.mark.parametrize(
        "attr,backend",
        [("gemini_api_key", BACKEND_GEMINI), ("openrouter_api_key", BACKEND_QWEN_VL)],
    )
    def test_key_gated_backends(self, pipe, attr, backend):
        by = {b.name: b for b in pipe.backends()}
        assert by[backend].available(pipe) is False
        setattr(pipe, attr, "sk-test")
        assert by[backend].available(pipe) is True


class TestDegradationLeavesATrace:
    """降级必须留痕 —— 而且"没配"与"配了但连不上"要分得开。"""

    def test_unavailable_and_failed_are_different_outcomes(self, pipe, monkeypatch):
        import asyncio

        pipe.local_gui_url = "http://127.0.0.1:1/v1"  # 配了,但连不上

        async def _boom(img, prompt):
            return None

        async def _tess(img):
            return None

        monkeypatch.setattr(pipe, "_call_local_gui", _boom)
        monkeypatch.setattr(pipe, "_call_tesseract_fallback", _tess)
        result = asyncio.run(pipe.understand(image_base64="Zm9v"))

        outcomes = {a["backend"]: a["outcome"] for a in result.attempts}
        assert outcomes[BACKEND_LOCAL_GUI] == "failed", "配了但连不上 = failed"
        assert outcomes[BACKEND_GEMINI] == "unavailable", "压根没配 = unavailable"
        # 这两件事的处理方式完全不同,混成一个空值就无从排查。
        assert outcomes[BACKEND_LOCAL_GUI] != outcomes[BACKEND_GEMINI]

    def test_every_backend_appears_in_the_trace(self, pipe, monkeypatch):
        import asyncio

        async def _tess(img):
            return None

        monkeypatch.setattr(pipe, "_call_tesseract_fallback", _tess)
        result = asyncio.run(pipe.understand(image_base64="Zm9v"))
        assert {a["backend"] for a in result.attempts} == set(DEFAULT_ORDER)
