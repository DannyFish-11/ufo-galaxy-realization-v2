#!/usr/bin/env python3
"""检测本机 GPU/内存并给出 BUILD_SPEC §0.3 档位建议。

用法:
    python scripts/detect_hardware.py           # 打印报告
    python scripts/detect_hardware.py --write A # 人类确认后把档位写入 config.yaml

档位写入必须由人类显式传入 --write <tier>(停点纪律:不自动定档)。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def detect_nvidia() -> list[tuple[str, int]]:
    """返回 [(gpu 名, 显存 MiB)];无 nvidia-smi 或无卡时为空。"""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        name, mem = line.rsplit(",", 1)
        gpus.append((name.strip(), int(mem.strip())))
    return gpus


def detect_ram_gb() -> float:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        m = re.search(r"MemTotal:\s+(\d+) kB", meminfo.read_text())
        if m:
            return int(m.group(1)) / 1024 / 1024
    return 0.0


def recommend(vram_gb: float, ram_gb: float) -> str:
    if vram_gb >= 40:
        return "A"
    if vram_gb >= 16:
        return "B"
    if vram_gb >= 8 or (vram_gb == 0 and ram_gb >= 8):  # 统一内存/纯 CPU 小模型
        return "C"
    return "none"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", metavar="TIER", choices=["A", "B", "C"],
                        help="人类确认后写入 config.yaml 的档位")
    args = parser.parse_args()

    gpus = detect_nvidia()
    ram = detect_ram_gb()
    vram = sum(m for _, m in gpus) / 1024 if gpus else 0.0

    print("== 硬件检测报告 ==")
    if gpus:
        for name, mem in gpus:
            print(f"GPU: {name}  {mem/1024:.1f} GB")
    else:
        print("GPU: 未检测到 NVIDIA GPU")
    print(f"RAM: {ram:.1f} GB")
    rec = recommend(vram, ram)
    if rec == "none":
        print("建议:硬件不足以启动任何档位 —— 停点:向人类报告并等待决策(BUILD_SPEC M1)")
    else:
        print(f"建议档位: {rec}(A≥40GB 显存 / B 16-24GB / C 8-16GB 统一内存)")
    print("提示: 确认档位后运行 python scripts/detect_hardware.py --write <TIER>")

    if args.write:
        text = CONFIG.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^(\s*tier:)\s*\S+", rf"\1 {args.write}", text, count=1)
        CONFIG.write_text(new, encoding="utf-8")
        print(f"已写入 config.yaml: hardware.tier = {args.write}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
