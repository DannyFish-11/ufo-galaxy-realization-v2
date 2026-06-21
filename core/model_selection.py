"""
core/model_selection.py — AI 主脑(本地模型)选择
=================================================

统一的"主脑模型"选择实现，供 main.py 与 launch_desktop.py 共用：

- MODELS：内置全部可选本地模型 —— Gemma 4 全系列(12B/E4B/E2B) + MiniCPM-o 4.5。
- recommend()：按【实际 GPU/CPU/显存】(core.hardware_compute_profiler)给出推荐。
- interactive_select()：克隆/首次启动时，显示推荐 + 列出全部，让用户手动选一个作为主脑。
- save_choice()/load_choice()：把选择持久化到 .galaxy_model，并写入 OLLAMA_MODEL 环境变量，
  让运行时路由(core.multi_llm_router)以它为默认"主脑"。
- resolve_main_brain()：解析最终主脑（已保存 > 环境变量 > 交互选择 > 硬件推荐）。

所有探测/IO 都容错，绝不抛出影响启动。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHOICE_FILE = PROJECT_ROOT / ".galaxy_model"

# ── 内置模型注册表（Ollama tag → 元数据）──────────────────────────────────
# required_mb：粗略的"建议显存/内存"门槛，用于按硬件推荐与排序。
MODELS: Dict[str, Dict] = {
    "gemma4:12b": {
        "name": "Google Gemma 4 12B",
        "family": "gemma4",
        "modalities": "文本 + 视觉 + 原生工具调用，128K 上下文",
        "size": "~8GB", "required_mb": 8000,
    },
    "openbmb/minicpm-o4.5": {
        "name": "MiniCPM-o 4.5 (9B)",
        "family": "minicpm-o",
        "modalities": "全模态：看 + 听 + 说，全双工实时交互",
        "size": "~6GB", "required_mb": 6000,
    },
    "gemma4:e4b": {
        "name": "Google Gemma 4 E4B",
        "family": "gemma4",
        "modalities": "文本 + 视觉，中等显存",
        "size": "~5GB", "required_mb": 4000,
    },
    "gemma4:e2b": {
        "name": "Google Gemma 4 E2B",
        "family": "gemma4",
        "modalities": "文本 + 视觉，小显存/轻量",
        "size": "~2GB", "required_mb": 2000,
    },
}

# 推荐优先级（从最强到最轻）：选第一个"装得下"的。
_PREFERENCE = ["gemma4:12b", "openbmb/minicpm-o4.5", "gemma4:e4b", "gemma4:e2b"]
DEFAULT_MODEL = "gemma4:12b"
_SMALLEST = "gemma4:e2b"


def list_models() -> List[Tuple[str, Dict]]:
    """返回 (tag, info) 列表，按推荐优先级排序（最强在前）。"""
    return [(t, MODELS[t]) for t in _PREFERENCE if t in MODELS]


def get_compute_summary() -> Tuple[int, str]:
    """返回 (max_model_size_mb, 硬件摘要文本)。探测失败时回退保守值。"""
    try:
        from core.hardware_compute_profiler import get_compute_profile_sync
        p = get_compute_profile_sync()
        max_mb = int(getattr(p, "max_model_size_mb", 0) or 0)
        gpus = getattr(p, "gpus", []) or []
        if gpus:
            g = gpus[0]
            summary = (f"GPU {getattr(g, 'name', '?')} "
                       f"(显存 {getattr(g, 'total_vram_mb', 0)} MB) | "
                       f"可加载 ≤ {max_mb} MB")
        else:
            summary = f"未检测到独立 GPU（CPU 模式）| 可加载 ≤ {max_mb} MB"
        return max_mb, summary
    except Exception as exc:  # noqa: BLE001
        return 0, f"硬件探测不可用（{exc}）—— 按保守默认推荐"


def recommend(max_model_size_mb: Optional[int] = None) -> str:
    """按可加载显存/内存给出推荐模型 tag。

    选推荐优先级里"第一个装得下"的；都装不下（极弱/纯 CPU）→ 最小模型。
    max_model_size_mb 为 None 时实时探测。
    """
    if max_model_size_mb is None:
        max_model_size_mb, _ = get_compute_summary()
    # 探测失败(0)时给保守推荐：MiniCPM-o（全模态、~6GB，多数有独显机器可跑），否则最小。
    if not max_model_size_mb:
        return "openbmb/minicpm-o4.5"
    for tag in _PREFERENCE:
        if MODELS[tag]["required_mb"] <= max_model_size_mb:
            return tag
    return _SMALLEST


def load_choice() -> str:
    """读取已持久化的主脑选择（.galaxy_model）。无则空串。"""
    try:
        if _CHOICE_FILE.exists():
            v = _CHOICE_FILE.read_text(encoding="utf-8").strip()
            return v if v in MODELS or v else v
    except Exception:  # noqa: BLE001
        pass
    return ""


def save_choice(tag: str) -> None:
    """持久化主脑选择并写入 OLLAMA_MODEL，让运行时以它为默认主脑。"""
    try:
        _CHOICE_FILE.write_text(tag, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if tag:
        os.environ["OLLAMA_MODEL"] = tag


def interactive_select() -> str:
    """显示硬件推荐 + 全部模型，让用户手动选一个作为主脑。返回所选 tag（"" = 跳过）。

    非交互(无 TTY)时不阻塞：直接返回推荐。
    """
    max_mb, hw = get_compute_summary()
    rec = recommend(max_mb)
    models = list_models()

    if not (sys.stdin and sys.stdin.isatty()):
        return rec  # 非交互：用推荐

    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   选择 AI 主脑模型（本地原生多模态）                      ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"  硬件：{hw}")
    print(f"  推荐：{MODELS[rec]['name']}  ←（按你的实际硬件）")
    print()
    for i, (tag, info) in enumerate(models, 1):
        mark = "  ← 推荐" if tag == rec else ""
        print(f"  [{i}] {info['name']}{mark}")
        print(f"      {info['modalities']}")
        print(f"      体积 {info['size']} · 建议显存 ≥ {info['required_mb']} MB")
    print("  [Enter] 用推荐    [s] 跳过（稍后手动 ollama pull）")
    print()

    try:
        choice = input("  请选择主脑 [1-%d / Enter / s]: " % len(models)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return rec
    if choice == "":
        return rec
    if choice == "s":
        return ""
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            return models[idx][0]
    print("  无效选择，使用推荐。")
    return rec


def resolve_main_brain(interactive: bool = True) -> str:
    """解析并持久化最终主脑模型 tag。

    优先级：环境变量 OLLAMA_MODEL（且在注册表内）> 已保存选择 > 交互选择 > 硬件推荐。
    返回选定 tag（可能为 ""，表示用户跳过）。
    """
    env_model = os.environ.get("OLLAMA_MODEL", "").strip()
    if env_model:
        save_choice(env_model)
        return env_model
    saved = load_choice()
    if saved:
        os.environ["OLLAMA_MODEL"] = saved
        return saved
    chosen = interactive_select() if interactive else recommend()
    if chosen:
        save_choice(chosen)
    return chosen
