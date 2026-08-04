"""core/multimodal/frame_gate.py — 帧变化门控（采集层唯一实现）
================================================================

"这一帧和上一帧比，变了多少" 这件事此前有**两套**实现：

* ``ambient_attention_loop.FrameGate`` —— 感知指纹（PIL 下采样成 16x16 灰度，
  比较归一化平均像素差），准；
* ``ingest_runtime`` 桥接里的 base64 长度差 —— 便宜，但把"同尺寸不同内容"
  当成没变化，粗。

同一份数据两套判据，结论必然分叉。本模块把**准的那套**收到采集层，成为唯一
实现：桥接用它算变化度喂进常驻感知帧，注意力循环从帧上读，不再各算各的。

跨消费者节奏的正确性
--------------------
``change_score`` 表达的是"距**上一次采集**的变化"。消费者的节拍往往比采集慢
（常驻感知 200ms，注意力循环若干秒），如果消费者直接读 score，采集侧早已把
变化"消化"回 0，消费者就会**漏掉那次变化** —— 这不是理论风险，摄像头链路的
回归测试里已经实测到过。

故本模块额外维护一个**单调递增的变化序号** ``change_seq``：每检测到一次
足够大的变化就 +1。任何消费者只需记住"我上次看到的序号"，就能判断"从我上次
看之后有没有变过"，与两边的节拍快慢完全无关。
"""

from __future__ import annotations

import base64
from typing import Any, Optional

# 帧差阈值（0..1，归一化平均像素差）。与既有 ambient 默认保持一致。
DEFAULT_DIFF_THRESHOLD = 0.06


def perceptual_signature(frame_b64: str) -> Optional[Any]:
    """把一帧 base64 图像压成一个 16x16 灰度指纹（numpy 数组）。

    用 PIL 解码 + 下采样；不可用时返回 None（调用方退回字节级启发式）。
    """
    try:
        import io

        import numpy as np
        from PIL import Image

        raw = base64.b64decode(frame_b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((16, 16))
        return np.asarray(img, dtype="float32") / 255.0
    except Exception:  # noqa: BLE001 — PIL 缺失/解码失败
        return None


def byte_similarity(a: str, b: str) -> float:
    """字节级相似度兜底（PIL 不可用时）：采样若干字节位比较。0..1，越大越像。"""
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    len_ratio = min(la, lb) / max(la, lb)
    n = min(256, min(la, lb))
    step = max(1, min(la, lb) // n)
    same = sum(1 for i in range(0, min(la, lb), step) if a[i] == b[i])
    total = len(range(0, min(la, lb), step))
    byte_ratio = same / total if total else 0.0
    return 0.5 * len_ratio + 0.5 * byte_ratio


class FrameGate:
    """维护上一帧指纹，判断新帧是否"变化足够大到值得惊动模型"。"""

    def __init__(self, threshold: float = DEFAULT_DIFF_THRESHOLD) -> None:
        self.threshold = threshold
        self._prev_sig: Optional[Any] = None
        self._prev_b64: Optional[str] = None
        self.last_score: float = 0.0
        self.change_seq: int = 0

    def reset(self) -> None:
        """丢弃上一帧指纹，让下一帧被当作"第一帧"。

        用于跨越隐私边界（暂停→恢复）后：留着暂停前的指纹去比恢复后的新帧，
        等于泄露"被遮住那段时间里画面变了多少"。注意这会让恢复后的第一拍
        必然判定为"有变化"（第一帧的既定语义），这是刻意接受的代价。

        ``change_seq`` **不**回退——它是单调计数，消费者靠"变没变过"判断，
        回退会让消费者误以为倒退回了旧状态。
        """
        self._prev_sig = None
        self._prev_b64 = None
        self.last_score = 0.0

    def score(self, frame_b64: Optional[str]) -> float:
        """本帧相对上一帧的变化度（0..1）。第一帧记 1.0（"全新"）。

        同时推进内部状态：``last_score`` 与（超阈值时）``change_seq``。
        """
        if not frame_b64:
            self.last_score = 0.0
            return 0.0

        sig = perceptual_signature(frame_b64)
        if sig is not None:
            import numpy as np

            if self._prev_sig is None:
                self._prev_sig = sig
                self._prev_b64 = frame_b64
                self.last_score = 1.0
                self.change_seq += 1
                return 1.0
            diff = float(np.mean(np.abs(sig - self._prev_sig)))
            self._prev_sig = sig
            self._prev_b64 = frame_b64
            self.last_score = diff
            if diff > self.threshold:
                self.change_seq += 1
            return diff

        # 字节级兜底：把相似度换算成"变化度"，与指纹路径同一量纲语义。
        if self._prev_b64 is None:
            self._prev_b64 = frame_b64
            self.last_score = 1.0
            self.change_seq += 1
            return 1.0
        sim = byte_similarity(frame_b64, self._prev_b64)
        self._prev_b64 = frame_b64
        diff = 1.0 - sim
        self.last_score = diff
        if sim < 0.995:
            self.change_seq += 1
        return diff

    def changed(self, frame_b64: Optional[str]) -> bool:
        """新帧是否变化足够大（保持既有布尔语义，供既有调用方原样使用）。"""
        if not frame_b64:
            return False
        before = self.change_seq
        self.score(frame_b64)
        return self.change_seq != before
