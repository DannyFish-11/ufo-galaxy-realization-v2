"""
模型目录 GPU 适配诚实评估 —— 契约测试
=====================================

背景:目录里 requires_gpu 此前只是描述文字,运行时无人消费 ——
用户在无显卡机器上选了"需显卡"档位,系统静默用 CPU 硬爬
(首 token 数秒到数十秒),没有任何诚实告警。

本套件钉住 /api/v1/models/catalog 的诚实语义:
1. 响应带 hardware 块(真实探测,不假装)。
2. gpu_fit 覆盖全部本地模型;requires_gpu=False 恒为 ok。
3. 无 GPU 时 requires_gpu 模型必须标 no_gpu(不许假装能跑)。
4. 探测失败时不阻塞目录,但 hardware.has_gpu 为 None + probe_error
   (如实说明"未评估",而不是编造结果)。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestCatalogGpuFit:
    def test_hardware_block_present(self):
        from core.routes.models import get_catalog

        snap = _run(get_catalog())
        assert "hardware" in snap
        assert "gpu_fit" in snap

    def test_gpu_fit_covers_all_local_models(self):
        from core.model_catalog import choice_order, get_model
        from core.routes.models import get_catalog

        snap = _run(get_catalog())
        if snap["hardware"].get("has_gpu") is None:
            return  # 探测失败路径由下面的测试钉
        local_tags = {t for t in choice_order() if (get_model(t) and get_model(t).source == "local")}
        assert set(snap["gpu_fit"]) == local_tags

    def test_non_gpu_models_always_ok(self):
        from core.model_catalog import get_model
        from core.routes.models import get_catalog

        snap = _run(get_catalog())
        for tag, fit in snap.get("gpu_fit", {}).items():
            if not get_model(tag).requires_gpu:
                assert fit == "ok", f"{tag} 不需显卡却被标 {fit}"

    def test_no_gpu_machine_flags_gpu_models(self):
        """无 GPU 时,requires_gpu 模型必须如实标 no_gpu。"""
        from core.model_catalog import get_model
        from core.routes.models import get_catalog

        snap = _run(get_catalog())
        hw = snap["hardware"]
        if hw.get("has_gpu") is not False:
            return  # 本机有 GPU / 探测失败时此断言不适用
        for tag, fit in snap["gpu_fit"].items():
            if get_model(tag).requires_gpu:
                assert fit == "no_gpu", f"{tag} 需显卡且本机无 GPU,却被标 {fit}(假装能跑)"

    def test_probe_failure_is_honest_not_fabricated(self):
        """探测器炸了 → has_gpu=None + probe_error,不编造评估。"""
        from core.routes import models as models_route

        with patch(
            "core.hardware_compute_profiler.get_hardware_profiler",
            side_effect=RuntimeError("probe exploded"),
        ):
            snap = _run(models_route.get_catalog())
        assert snap["hardware"]["has_gpu"] is None
        assert "probe_error" in snap["hardware"]
        assert snap["gpu_fit"] == {}
