#!/usr/bin/env python3
"""生成确定性的测试 fixtures:白猫图片、红色汽车图片、1 秒 440Hz 音频。"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def make_white_cat(path: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), (60, 140, 60))  # 绿色背景
    d = ImageDraw.Draw(img)
    white = (250, 250, 250)
    d.ellipse([64, 110, 192, 220], fill=white)            # 身体
    d.ellipse([90, 50, 166, 126], fill=white)             # 头
    d.polygon([(95, 70), (110, 30), (125, 66)], fill=white)   # 左耳
    d.polygon([(131, 66), (146, 30), (161, 70)], fill=white)  # 右耳
    d.ellipse([108, 78, 118, 88], fill=(40, 40, 40))      # 左眼
    d.ellipse([138, 78, 148, 88], fill=(40, 40, 40))      # 右眼
    d.polygon([(124, 94), (132, 94), (128, 101)], fill=(230, 150, 150))  # 鼻
    d.arc([170, 130, 230, 210], start=270, end=90, fill=white, width=10)  # 尾巴
    img.save(path)


def make_red_car(path: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), (150, 150, 160))  # 灰色背景
    d = ImageDraw.Draw(img)
    red = (210, 30, 30)
    d.rectangle([40, 130, 216, 180], fill=red)            # 车身
    d.polygon([(80, 130), (110, 95), (170, 95), (190, 130)], fill=red)  # 车顶
    d.ellipse([60, 165, 100, 205], fill=(30, 30, 30))     # 前轮
    d.ellipse([160, 165, 200, 205], fill=(30, 30, 30))    # 后轮
    d.rectangle([115, 102, 163, 128], fill=(180, 220, 240))  # 车窗
    img.save(path)


def make_tone(path: Path, freq: float = 440.0, seconds: float = 1.0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            val = int(32767 * 0.4 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", val)
        w.writeframes(bytes(frames))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_white_cat(FIXTURES / "white_cat.png")
    make_red_car(FIXTURES / "red_car.png")
    make_tone(FIXTURES / "tone_440hz.wav")
    print(f"fixtures written to {FIXTURES}")


if __name__ == "__main__":
    main()
