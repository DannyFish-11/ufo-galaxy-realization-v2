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

import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ModelSelection")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHOICE_FILE = PROJECT_ROOT / ".galaxy_model"

# 可选主脑（顺序=推荐优先级，最强在前）。tag 必须存在于 LocalBrainManager 的目录里；
# 这里只放"展示用"的人类可读标签/模态说明，体积/尺寸一律向 LocalBrainManager 取。
_CHOICE_ORDER: List[str] = ["gemma4:12b", "openbmb/minicpm-o4.5", "gemma4:e4b", "gemma4:e2b"]
_LABELS: Dict[str, Tuple[str, str]] = {
    "gemma4:12b":            ("Google Gemma 4 12B", "文本 + 视觉 + 原生音频(听) + 工具调用，128K"),
    "openbmb/minicpm-o4.5":  ("MiniCPM-o 4.5 (9B)", "全模态：看 + 听 + 说，全双工(需显卡)"),
    "gemma4:e4b":            ("Google Gemma 4 E4B", "文本 + 视觉 + 原生音频(听)，中等显存"),
    "gemma4:e2b":            ("Google Gemma 4 E2B", "文本 + 视觉 + 原生音频(听)，小显存/轻量"),
}
_SMALLEST_FALLBACK = "gemma4:e2b"

# gemma4 系列需要较新的 Ollama 客户端才能解析其 manifest(联网核实：多个独立来源
# ——open-webui issue #23471《Gemma4 requires a newer version of Ollama》、社区
# 排障笔记、版本变更记录——一致指向"旧版 Ollama 拉不动 gemma4，需 ≥ 0.22，
# 官方在 0.30.x 系列里持续修 gemma4 相关 bug"。这里保守取 0.22 作为下限，
# 低于此版本时给出明确、可操作的升级指引，而不是笼统的"版本可能过旧"。
MIN_OLLAMA_VERSION_FOR_GEMMA4: Tuple[int, int, int] = (0, 22, 0)


def parse_ollama_version(version_output: str) -> Optional[Tuple[int, int, int]]:
    """从 `ollama --version` 输出(如 "ollama version is 0.14.1")解析出
    (major, minor, patch)；解析不出返回 None。"""
    import re
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", version_output or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_ollama_version_too_old(
    version_output: str,
    min_version: Tuple[int, int, int] = MIN_OLLAMA_VERSION_FOR_GEMMA4,
) -> Optional[bool]:
    """版本太旧返回 True；够新返回 False；解析不出版本号返回 None(未知，不下结论)。"""
    parsed = parse_ollama_version(version_output)
    if parsed is None:
        return None
    return parsed < min_version


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


def get_compute_summary() -> Tuple[int, bool, str]:
    """返回 (max_model_size_mb, has_gpu, 硬件摘要)。复用 core.hardware_compute_profiler。"""
    try:
        from core.hardware_compute_profiler import get_compute_profile_sync
        p = get_compute_profile_sync()
        max_mb = int(getattr(p, "max_model_size_mb", 0) or 0)
        gpus = getattr(p, "gpus", []) or []
        has_gpu = bool(gpus)
        if has_gpu:
            g = gpus[0]
            summary = (f"GPU {getattr(g, 'name', '?')} "
                       f"(显存 {getattr(g, 'total_vram_mb', 0)} MB) | 可加载 ≤ {max_mb} MB")
        else:
            summary = f"未检测到独立 GPU（CPU 模式）| 可加载 ≤ {max_mb} MB"
        return max_mb, has_gpu, summary
    except Exception as exc:  # noqa: BLE001
        return 0, False, f"硬件探测不可用（{exc}）—— 按保守默认推荐"


def recommend(max_model_size_mb: Optional[int] = None, has_gpu: Optional[bool] = None) -> str:
    """硬件感知推荐主脑模型。

    - 无独显(纯 CPU)：大模型 CPU 推理极慢 → 直接推最轻的 ``gemma4:e2b``(带视觉、最快)。
    - 有独显：推荐优先级里第一个"装得下"显存的；都装不下 → 最小；探测失败 → 全模态。
    """
    if max_model_size_mb is None or has_gpu is None:
        _mb, _gpu, _ = get_compute_summary()
        if max_model_size_mb is None:
            max_model_size_mb = _mb
        if has_gpu is None:
            has_gpu = _gpu
    # 纯 CPU：无论内存多大，都给轻量模型（大模型 CPU 推理体验极差）。
    if not has_gpu:
        return "gemma4:e2b"
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
    """显示硬件推荐 + 全部模型，让用户手动选主脑。返回 tag（"" = 跳过）。

    非交互终端(无 TTY)时不阻塞、不"偷偷"选：返回推荐，由调用方明确打印"已自动选用"。
    渲染走 core.cli_render（与启动界面同一套：对齐、细线、不画歪掉的中文框）。
    """
    from core import cli_render as r
    from core.ascii_art import Colors

    max_mb, has_gpu, hw = get_compute_summary()
    rec = recommend(max_mb, has_gpu)
    models = list_models()

    if not (sys.stdin and sys.stdin.isatty()):
        return rec  # 非交互：交给 main.py 明确说明"已自动选推荐"

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    print()
    print("  " + _c("选择 AI 主脑模型", Colors.BOLD + Colors.CYAN)
          + _c("  (本地原生多模态)", Colors.DIM))
    r.rule()
    r.phase("硬件", hw, "info")
    r.phase("推荐", f"{model_name(rec)}  ←（按你的实际硬件）", "ok")
    print()
    # 列出全部可选模型：序号 + 名称(对齐) + 建议显存；推荐项加 ▸ 与「← 推荐」。
    for i, (tag, info) in enumerate(models, 1):
        is_rec = (tag == rec)
        marker = _c("▸", Colors.GREEN) if is_rec else " "
        num = _c(f"[{i}]", Colors.BOLD if is_rec else Colors.DIM)
        name = r.pad_display(info["name"], 24)
        sz = _c(f"显存 ≥ {info['size_mb']} MB", Colors.DIM) if info["size_mb"] else ""
        tail = _c("  ← 推荐", Colors.GREEN) if is_rec else ""
        print(f"  {marker} {num} {name}{sz}{tail}")
        print(f"         {_c(info['desc'], Colors.DIM)}")
    r.rule()
    print("  " + _c("回车=用推荐 · 数字=手选 · s=跳过下载", Colors.DIM)
          + _c("   (之后可用 --select-model 重选)", Colors.DIM))
    # 循环直到拿到有效输入：避免"一闪而过"——只有明确回车/序号/s 才往下走。
    while True:
        try:
            choice = input(f"  请选择主脑 [1-{len(models)} / 回车 / s]: ").strip().lower()
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
        print("  " + _c("⚠ 无效输入，请重新选择（或直接回车用推荐）。", Colors.YELLOW))


def background_pull(tag: str) -> None:
    """若本地 Ollama 没有该主脑模型，则后台 ollama pull（不阻塞启动）。"""
    import shutil
    import subprocess
    import threading
    if not tag or not shutil.which("ollama"):
        return

    def _pull() -> None:
        try:
            import httpx
            base = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
            have: List[str] = []
            try:
                r = httpx.get(f"{base}/api/tags", timeout=3.0)
                if r.status_code == 200:
                    have = [m.get("name", "") for m in r.json().get("models", [])]
            except Exception:
                pass
            root = tag.split(":")[0]
            matched = next(
                (h for h in have if h == tag or h.startswith(tag + ":") or h.split(":")[0] == root),
                None,
            )
            if matched:
                # 关键:不能只信"名字出现在 /api/tags 里"就判定已装好——之前失败
                # (比如版本不兼容)的拉取偶尔会留下一个能列出名字、但打不开的
                # 残缺 manifest,若只看 /api/tags 就直接放行,会导致这个坏掉的
                # 条目【永久】拦住后续所有重试和 HuggingFace 回退(每次重启都
                # 误判"已安装"，实际每次对话都还是 404)。用 /api/show 核实一下
                # 它是不是真的能打开;打不开就当没装,继续走下面的拉取/回退。
                try:
                    show_r = httpx.post(f"{base}/api/show", json={"name": matched}, timeout=5.0)
                    if show_r.status_code == 200:
                        return  # 确实已装好且可用
                    print(f"  ⚠ Ollama 列表里有 {matched}，但 /api/show 核实不可用"
                          f"(status={show_r.status_code})——当作未安装，重新拉取。")
                except Exception as exc:
                    print(f"  ⚠ Ollama 列表里有 {matched}，但核实可用性失败({exc})——当作未安装，重新拉取。")
            print(f"  ▶  正在后台拉取本地主脑模型 ollama pull {tag} …(不阻塞启动)")
            proc = subprocess.run(["ollama", "pull", tag], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=3600)
            if proc.returncode == 0:
                print(f"  ✓ 本地主脑模型已就绪:{tag}")
                return
            # 关键:不要静默吞掉失败。联网核实过(open-webui issue #23471 等多个
            # 独立来源一致印证):gemma4 系列需要较新 Ollama 客户端才能解析其
            # manifest,旧版会在 "pulling manifest" 就失败——这正是最常见根因。
            _err = (proc.stderr or proc.stdout or "").strip()[:300]
            print(f"  ⚠ 拉取 {tag} 失败 — {_err}")
            try:
                _ver = subprocess.run(["ollama", "--version"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=5).stdout.strip()
                print(f"     当前 Ollama 版本:{_ver or '(未知)'}")
                _too_old = is_ollama_version_too_old(_ver)
                if _too_old is True:
                    print(f"     ⚠ 你的 Ollama 版本明显低于 {root} 系列所需的最低版本"
                          f"(经核实需 ≥ {'.'.join(map(str, MIN_OLLAMA_VERSION_FOR_GEMMA4))}，"
                          f"建议直接升到最新版)。这几乎可以肯定就是拉取失败的原因。")
                    print(f"     Windows 升级:winget upgrade Ollama.Ollama ,"
                          f"或从 https://ollama.com/download/windows 下载最新安装包直接覆盖安装"
                          f"(会保留已下载的模型)。升级后重跑 `ollama pull {tag}` 应该就能成功。")
                elif _too_old is False:
                    print(f"     Ollama 版本本身不算旧，拉取失败更可能是网络/registry 问题，"
                          f"或该 tag 确实不在库里——继续尝试 HuggingFace 回退。")
            except Exception:
                pass

            # 兜底:Ollama 库没有就直接从 HuggingFace 下载相关模型,再导入成本地
            # Ollama 自定义模型(复用 Ollama 现成的 serving 路径,下游无需改动)。
            # GALAXY_HF_OLLAMA_FALLBACK=0 可关闭。
            if os.environ.get("GALAXY_HF_OLLAMA_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off"):
                try:
                    from core.hf_ollama_import_fallback import download_and_import_to_ollama
                    local_tag = download_and_import_to_ollama(tag)
                except Exception as exc:  # noqa: BLE001
                    local_tag = None
                    logger.debug("HF 回退导入异常(非致命): %s", exc)
                if local_tag:
                    save_choice(local_tag)
                    print(f"  ✓ 本地主脑模型已就绪(HuggingFace 回退导入):{local_tag}")
                    return
                print(f"     HuggingFace 回退候选也都试过,未能导入成功。")

            print(f"     可先在「模型」tab 填一个云端 API Key(DeepSeek/通义/Claude…)作为主力兜底,")
            print(f"     或手动确认版本、升级 Ollama 后重试 `ollama pull {tag}`。")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ 本地主脑模型拉取异常:{tag} — {exc}")

    threading.Thread(target=_pull, name="GalaxyModelPull", daemon=True).start()


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
