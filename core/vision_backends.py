"""视觉后端登记表 —— 一处权威地说明「有哪些档、什么顺序、各自什么性质」。

原来是什么样
------------
``core/vision_pipeline.py`` 的降级链是**写死在 ``analyze()`` 里的 if 瀑布**::

    # Level 1: DeepSeek OCR 2
    if self.deepseek_api_key or self.local_vllm_url: ...
    # Level 2: Gemini
    if not result and self.gemini_api_key: ...
    # Level 3: Qwen3-VL via OpenRouter
    if not result and self.openrouter_api_key: ...
    # Level 4: Tesseract 离线降级
    if not result: ...

三个后果:

1. **加一档要改 ``analyze()`` 本体** —— 而不是登记一个后端。顺序、可用性判断、
   统计键三样东西散在函数体里各处,改一处漏一处。
2. **没人说得清"这一档的数据出不出设备"**。上面四档里前三档全是云端,第四档
   (Tesseract)虽然本地却**只认字、不懂控件**。也就是说:想要真正的界面理解,
   就**必须上云** —— 这与本项目"个人 AI、数据不出设备"的立场正面冲突,
   而代码里没有任何地方把这件事说出来。
3. **选了哪一档、为什么跳过前面的,事后查不到**。只有一个 ``engine_used``
   字符串,没有"试过谁、谁不可用、为什么"。

现在是什么样
------------
每一档是一条 :class:`VisionBackend` 登记,自己声明:

* ``local`` —— **数据出不出这台设备**。这是隐私判据,不是装饰字段;
* ``grounding`` —— 懂不懂控件(能定位可交互元素),还是只认字(OCR);
* ``available(pipeline)`` —— 这台机器上此刻能不能用;
* ``call(pipeline, image_b64, prompt)`` —— 真正干活的那一下。

顺序由 :data:`DEFAULT_ORDER` 一处定义,``GALAXY_VISION_BACKEND_ORDER`` 可覆盖。

**默认行为一个字没变**:原来的四档、原来的先后、原来的可用性判断,逐条照搬。
新增的本地 GUI 档排在最前,但它**只有在显式配置了本地端点时才可用** ——
没配就自动跳过,对现有部署零影响。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.VisionBackends")

#: 后端标识 —— 只在这里定义一次,统计键与日志都用它,不各写各的字符串。
BACKEND_LOCAL_GUI = "local_gui"
BACKEND_DEEPSEEK = "deepseek_ocr2"
BACKEND_GEMINI = "gemini"
BACKEND_QWEN_VL = "qwen3_vl"
BACKEND_TESSERACT = "tesseract"


@dataclass(frozen=True)
class VisionBackend:
    """一档视觉后端的登记。

    Attributes:
        name: 稳定标识(进统计、日志、留痕),不随文案变。
        label: 给人看的名字。
        local: 图像**是否只在本机处理**。云端档一律 False —— 截图是屏幕内容,
            这一位决定了它会不会离开这台设备,是隐私判据。
        grounding: 是否**理解控件**(能给出可交互元素与位置)。Tesseract 这类
            纯 OCR 是 False:它认得出字,认不出"那是个按钮"。
        stat_key: ``VisionPipeline._stats`` 里的计数键(沿用历史键名)。
        available: 这台机器上此刻能不能用。
        call: 真正发起识别;失败返回 None,由调用方继续降级。
    """

    name: str
    label: str
    local: bool
    grounding: bool
    stat_key: str
    available: Callable[[Any], bool]
    call: Callable[[Any, str, str], Awaitable[Optional[Dict]]]

    @property
    def privacy_note(self) -> str:
        """这一档对隐私意味着什么 —— 一句人话,面板与日志共用。"""
        if self.local:
            return "图像只在本机处理,不出设备" if self.grounding else "图像只在本机处理,但只认字、不懂控件"
        return "图像会发到云端识别"


#: 默认顺序。**本地优先** —— 隐私是这个项目的立场,不是可选项。
#:
#: 但要说清楚:本地 GUI 档排最前**不改变任何现有部署的行为**,因为它
#: ``available`` 的前提是显式配置了本地端点;没配就整档跳过,后面四档
#: 的先后与原来逐条一致。
DEFAULT_ORDER: List[str] = [
    BACKEND_LOCAL_GUI,
    BACKEND_DEEPSEEK,
    BACKEND_GEMINI,
    BACKEND_QWEN_VL,
    BACKEND_TESSERACT,
]


def resolve_order(raw: Optional[str] = None) -> List[str]:
    """解析后端顺序。``GALAXY_VISION_BACKEND_ORDER`` 用逗号分隔覆盖默认。

    只认识已登记的名字;不认识的**报一声再忽略**,不静默吞掉 —— 打错一个名字
    就少走一整档,静默的话没人会发现。漏写的档补在末尾(顺序可以改,但不能因为
    没写就把一档弄丢)。
    """
    text = raw if raw is not None else os.environ.get("GALAXY_VISION_BACKEND_ORDER", "")
    if not text.strip():
        return list(DEFAULT_ORDER)

    wanted: List[str] = []
    for item in text.split(","):
        key = item.strip()
        if not key:
            continue
        if key not in DEFAULT_ORDER:
            logger.warning(
                "GALAXY_VISION_BACKEND_ORDER 里的 %r 不是已登记的视觉后端,已忽略。可用: %s",
                key,
                ", ".join(DEFAULT_ORDER),
            )
            continue
        if key not in wanted:
            wanted.append(key)
    # 没写到的补在末尾 —— 顺序可以改,但不该因为漏写就丢掉一档。
    for key in DEFAULT_ORDER:
        if key not in wanted:
            wanted.append(key)
    return wanted


def ordered_backends(registry: Dict[str, VisionBackend], raw_order: Optional[str] = None) -> List[VisionBackend]:
    """按解析出来的顺序把登记表排好。"""
    return [registry[name] for name in resolve_order(raw_order) if name in registry]


__all__ = [
    "BACKEND_DEEPSEEK",
    "BACKEND_GEMINI",
    "BACKEND_LOCAL_GUI",
    "BACKEND_QWEN_VL",
    "BACKEND_TESSERACT",
    "DEFAULT_ORDER",
    "VisionBackend",
    "ordered_backends",
    "resolve_order",
]
