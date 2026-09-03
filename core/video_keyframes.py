"""视频 → 模型：把一段画面抽成带时间戳的关键帧序列。

为什么不是「把视频原样发给模型」：这条链路上没有 ffmpeg，路由后面的视觉模型
也没有一个吃视频容器 —— 全都只收静止图。所以「支持视频」的唯一诚实实现，就是
在这里抽帧，而不是假装能带视频、到下游再悄悄丢掉。

为什么帧要带 offset：一堆无序静止图只能回答「屏幕上有什么」，带时间偏移的有序
序列才能回答「发生了什么」—— 动画卡在哪一步、报错是在点击前还是点击后。这正是
此前整条链路缺失的那一维：感知库每来一帧就覆盖上一帧，历史当场消失。

纯函数模块，无第三方依赖（不用 numpy —— 抽帧是取下标，不是数值计算）。

放在 ``core/`` 而不是 ``core/multimodal/``：后者的 ``__init__`` 会连带拉起
audio_capture / webrtc / vad 一整套重依赖，而本模块要在**每一次带图对话**的消息
组装路径上被调用。让一次格式化去 import aiortc 和 numpy 是纯粹的负债。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

#: 单段视频最多送多少帧。视觉模型按图计费且上下文有限，8 帧足以表达一段短交互，
#: 再多是线性烧钱而信息增量递减。
MAX_KEYFRAMES = 8


def sample_keyframes(frames: Sequence[Any], *, max_frames: int = MAX_KEYFRAMES) -> List[Any]:
    """均匀抽帧，**首尾必留**。

    首尾必留是因为「之前长什么样 / 现在长什么样」是这类问题的答案本体；均匀抽中间
    是为了不假设变化发生在哪一段（按变化分数挑会漏掉缓慢连续的变化，比如进度条）。
    """
    if max_frames <= 0:
        return []
    n = len(frames)
    if n <= max_frames:
        return list(frames)
    if max_frames == 1:
        return [frames[-1]]  # 只能带一帧时带最新的那帧,而不是最旧的
    # 在 [0, n-1] 上取 max_frames 个等距点,两端闭合 → 首尾必中
    idxs = [round(i * (n - 1) / (max_frames - 1)) for i in range(max_frames)]
    seen: set = set()
    out: List[Any] = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            out.append(frames[i])
    return out


def _frame_label(video: Any, index: int, total: int, offset_ms: int) -> str:
    src = getattr(video, "source", None) or "video"
    return f"[{src} 关键帧 {index}/{total} t=+{offset_ms / 1000:.1f}s]"


def build_video_content_parts(video: Any, *, max_frames: int = MAX_KEYFRAMES) -> List[Dict[str, Any]]:
    """把一段 MultiModalVideo 铺成 OpenAI content parts：文字标注 + 图，交替。

    每帧前面的那行文字不是装饰 —— content 数组里的图彼此没有顺序语义，模型看到的
    只是「几张图」。把 ``t=+1.2s`` 写进相邻的 text part，时间轴才真的传达出去。
    """
    frames = list(getattr(video, "frames", None) or [])
    picked = sample_keyframes(frames, max_frames=max_frames)
    parts: List[Dict[str, Any]] = []
    total = len(picked)
    for i, fr in enumerate(picked, start=1):
        data = getattr(fr, "data", "") or ""
        if not data:
            continue
        mime = getattr(fr, "mime", "image/jpeg") or "image/jpeg"
        offset = int(getattr(fr, "offset_ms", 0) or 0)
        url = data if data.startswith("data:") else f"data:{mime};base64,{data}"
        parts.append({"type": "text", "text": _frame_label(video, i, total, offset)})
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts
