"""
core.tts — 语音合成 (Text-to-Speech)
=====================================
基于 edge-tts 的免费语音合成引擎，支持中文和多种声音。

主要组件:
    EdgeTTSEngine — Edge TTS 语音合成引擎

使用示例::

    import asyncio
    from core.tts import EdgeTTSEngine

    async def main():
        tts = EdgeTTSEngine(voice="zh-CN-XiaoxiaoNeural")
        mp3_path = await tts.synthesize("你好，世界！")
        print(f"Generated: {mp3_path}")

    asyncio.run(main())
"""

from .edge_tts_engine import EdgeTTSEngine

__all__ = ["EdgeTTSEngine"]
