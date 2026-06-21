"""
core/model_selection.py — AI 主脑选择（构建于 Phase 5「AI 大脑」之上）
=====================================================================

不重复定义模型目录：**模型清单与尺寸全部取自现有的
``core.local_brain_manager.LocalBrainManager``**（RECOMMENDED_MODELS /
MODEL_SIZE_ESTIMATE_MB —— 单一真相来源）。本模块只在其之上补三件事：

1. recommend()        —— 按【实际 GPU/CPU 显存】(core.hardware_compute_profiler)给推荐；
2. interactive_select() —— 显示推荐 + 列出全部，让用户手动选一个作主脑；
3. save/load_choice() —— 持久化 .galaxy_model 并写 OLLAMA_MODEL，驱动运行时主脑。

供 main.py（Phase 0.5）与 launch_desktop.py 共用。所有探测/IO 容错，绝不影响启动。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHOICE_FILE = PROJECT_ROOT / ".galaxy_model"

# 可选主脑（顺序=推荐优先级，最强在前）。tag 必须存在于 LocalBrainManager 的目录里；
# 这里只放"展示用"的人类可读标签/模态说明，体积/尺寸一律向 LocalBrainManager 取。
_CHOICE_ORDER: List[str] = ["gemma4:12b", "openbmb/minicpm-o4.5", "gemma4:e4b", "gemma4:e2b"]
_LABELS: Dict[str, Tuple[str, str]] = {
    "gemma4:12b":            ("Google Gemma 4 12B", "文本 + 视觉 + 原生工具调用，128K 上下文"),
    "openbmb/minicpm-o4.5":  ("MiniCPM-o 4.5 (9B)", "全模态：看 + 听 + 说，全双工实时交互"),
    "gemma4:e4b":            ("Google Gemma 4 E4B", "文本 + 视觉，中等显存"),
    "gemma4:e2b":            ("Google Gemma 4 E2B", "文本 + 视觉，小显存/轻量"),
}
_SMALLEST_FALLBACK = "gemma4:e2b"


def _brain_sizes() -> Dict[str, int]:
    """模型尺寸(MB)取自现有 LocalBrainManager（单一真相来源），失败时空表。"""
    try:
        from core.local_brain_manager import LocalBrainManager
        return dict(LocalBrainManager.MODEL_SIZE_ESTIMATE_MB)
    except Exception:  # noqa: BLE001
        return {}


def _default_tag() -> str:
    """默认主脑取自 LocalBrainManager.RECOMMENDED_MODELS['default']。"""
    try:
        from core.local_brain_manager import LocalBrainManager
        return LocalBrainManager.RECOMMENDED_MODELS.get("default", "gemma4:12b")
    except Exception:  # noqa: BLE001
        return "gemma4:12b"


def list_models() -> List[Tuple[str, Dict]]:
    """返回 (tag, {name, desc, size_mb}) 列表，按推荐优先级排序。"""
    sizes = _brain_sizes()
    out: List[Tuple[str, Dict]] = []
    for tag in _CHOICE_ORDER:
        if tag not in _LABELS:
            continue
        name, desc = _LABELS[tag]
        out.append((tag, {"name": name, "desc": desc, "size_mb": sizes.get(tag, 0)}))
    return out


def model_name(tag: str) -> str:
    return _LABELS.get(tag, (tag, ""))[0]


def get_compute_summary() -> Tuple[int, str]:
    """返回 (max_model_size_mb, 硬件摘要)。复用 core.hardware_compute_profiler。"""
    try:
        from core.hardware_compute_profiler import get_compute_profile_sync
        p = get_compute_profile_sync()
        max_mb = int(getattr(p, "max_model_size_mb", 0) or 0)
        gpus = getattr(p, "gpus", []) or []
        if gpus:
            g = gpus[0]
            summary = (f"GPU {getattr(g, 'name', '?')} "
                       f"(显存 {getattr(g, 'total_vram_mb', 0)} MB) | 可加载 ≤ {max_mb} MB")
        else:
            summary = f"未检测到独立 GPU（CPU 模式）| 可加载 ≤ {max_mb} MB"
        return max_mb, summary
    except Exception as exc:  # noqa: BLE001
        return 0, f"硬件探测不可用（{exc}）—— 按保守默认推荐"


def recommend(max_model_size_mb: Optional[int] = None) -> str:
    """按可加载显存给推荐：推荐优先级里第一个"装得下"的；都装不下→最小；探测失败→全模态。"""
    if max_model_size_mb is None:
        max_model_size_mb, _ = get_compute_summary()
    sizes = _brain_sizes()
    if not max_model_size_mb:
        return "openbmb/minicpm-o4.5"
    for tag in _CHOICE_ORDER:
        need = sizes.get(tag)
        if need and need <= max_model_size_mb:
            return tag
    return _SMALLEST_FALLBACK


def load_choice() -> str:
    try:
        if _CHOICE_FILE.exists():
            return _CHOICE_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def save_choice(tag: str) -> None:
    """持久化选择并写 OLLAMA_MODEL，让运行时(multi_llm_router/LocalBrainManager)以它为主脑。"""
    try:
        _CHOICE_FILE.write_text(tag, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if tag:
        os.environ["OLLAMA_MODEL"] = tag


def interactive_select() -> str:
    """显示硬件推荐 + 全部模型，让用户手动选主脑。返回 tag（"" = 跳过）。非 TTY 用推荐。"""
    max_mb, hw = get_compute_summary()
    rec = recommend(max_mb)
    models = list_models()

    if not (sys.stdin and sys.stdin.isatty()):
        return rec

    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   选择 AI 主脑模型（本地原生多模态）                      ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"  硬件：{hw}")
    print(f"  推荐：{model_name(rec)}  ←（按你的实际硬件）")
    print()
    for i, (tag, info) in enumerate(models, 1):
        mark = "  ← 推荐" if tag == rec else ""
        sz = f"建议显存 ≥ {info['size_mb']} MB" if info["size_mb"] else ""
        print(f"  [{i}] {info['name']}{mark}")
        print(f"      {info['desc']}    {sz}")
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
    """解析并持久化最终主脑：环境 OLLAMA_MODEL > 已保存 > 交互选择 > 硬件推荐。"""
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


# ── 向后兼容：main.py / launch_desktop 仍以 MODELS[tag]["name"] 取展示名 ──
MODELS: Dict[str, Dict] = {
    tag: {"name": _LABELS[tag][0], "modalities": _LABELS[tag][1]}
    for tag in _CHOICE_ORDER if tag in _LABELS
}
DEFAULT_MODEL = _default_tag()
