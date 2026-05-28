"""
core.asr — 自动语音识别 (Automatic Speech Recognition)
=======================================================
基于 faster-whisper 的本地ASR引擎，支持CPU/GPU自动选择。

主要组件:
    WhisperASR — 本地语音识别引擎 (faster-whisper)

使用示例::

    from core.asr import WhisperASR
    import numpy as np

    asr = WhisperASR(model_size="small")
    audio = np.random.randn(16000).astype(np.float32)  # 1秒音频
    text = asr.transcribe(audio, sample_rate=16000, language="zh")
"""

from .whisper_asr import WhisperASR

__all__ = ["WhisperASR"]
