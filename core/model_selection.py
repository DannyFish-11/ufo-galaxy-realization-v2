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


# 可选主脑清单不再在此硬编码 —— 统一派生自 core.model_catalog（唯一真相源）。
# 此前这里、ModelsTab.tsx、config.py 各存一份必须手动同步的清单，漏改即漂移。
# 现在三处全部从 catalog 派生。展示标签/模态说明也取自 catalog 的 ModelSpec。
def _choice_order() -> List[str]:
    try:
        from core.model_catalog import choice_order

        return choice_order()
    except Exception:  # noqa: BLE001 — catalog 不可用时的保守兜底
        return ["gemma4:e2b", "gemma4:e4b", "gemma4:12b", "openbmb/minicpm-o4.5"]


def _labels() -> Dict[str, Tuple[str, str]]:
    try:
        from core.model_catalog import get_model

        out: Dict[str, Tuple[str, str]] = {}
        for tag in _choice_order():
            spec = get_model(tag)
            if spec:
                out[tag] = (spec.name, spec.desc)
        return out
    except Exception:  # noqa: BLE001
        return {}


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
    """模型尺寸(MB)派生自 core.model_catalog（唯一真相源），失败时空表。"""
    try:
        from core.model_catalog import all_models

        return {s.tag: s.size_mb() for s in all_models()}
    except Exception:  # noqa: BLE001
        return {}


def _default_tag() -> str:
    """默认主脑派生自 core.model_catalog.default_model()（唯一真相源）。"""
    try:
        from core.model_catalog import default_model

        return default_model()
    except Exception as exc:  # noqa: BLE001
        # 这个字面量是唯一真相源 default_model() 的副本,只在真相源读不到时兜底。
        # 副本迟早会和真相源漂移(改了目录却忘了改这里),静默退回等于悄悄换了主脑。
        logger.warning("读取默认主脑失败(%s):退回内置副本 gemma4:12b,可能与模型目录不一致", exc)
        return "gemma4:12b"


def list_models() -> List[Tuple[str, Dict]]:
    """返回 (tag, {name, desc, size_mb}) 列表，按推荐优先级排序（派生自 catalog）。"""
    sizes = _brain_sizes()
    labels = _labels()
    out: List[Tuple[str, Dict]] = []
    for tag in _choice_order():
        if tag not in labels:
            continue
        name, desc = labels[tag]
        out.append((tag, {"name": name, "desc": desc, "size_mb": sizes.get(tag, 0)}))
    return out


def model_name(tag: str) -> str:
    return _labels().get(tag, (tag, ""))[0]


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
            summary = (
                f"GPU {getattr(g, 'name', '?')} " f"(显存 {getattr(g, 'total_vram_mb', 0)} MB) | 可加载 ≤ {max_mb} MB"
            )
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
    for tag in _choice_order():
        need = sizes.get(tag)
        if need and need <= max_model_size_mb:
            return tag
    return _SMALLEST_FALLBACK


def load_choice() -> str:
    """当前主脑 tag —— 收敛到 model_catalog 的统一记录(不再独立读 .galaxy_model)。"""
    try:
        from core.model_catalog import main_brain

        return main_brain()
    except Exception:  # noqa: BLE001 — catalog 不可用时兜底读旧文件(迁移期)
        try:
            if _CHOICE_FILE.exists():
                return _CHOICE_FILE.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
        return ""


def save_choice(tag: str) -> None:
    """持久化主脑 —— 收敛到 model_catalog 的统一记录(它写记录 + 派生 OLLAMA_MODEL)。

    不再独立写 .galaxy_model;model_catalog 是主脑写入的唯一门。
    """
    if not tag:
        return
    try:
        from core.model_catalog import save_main_brain

        save_main_brain(tag)
    except Exception:  # noqa: BLE001 — catalog 不可用时至少把运行时 env 设上
        os.environ["OLLAMA_MODEL"] = tag


def recommend_tier(has_gpu: Optional[bool] = None, max_mb: Optional[int] = None) -> str:
    """按硬件推荐档位：无独显→A；有显卡且够跑全模态单模型(MiniCPM-o 约 6GB)→B。"""
    if has_gpu is None or max_mb is None:
        _mb, _gpu, _ = get_compute_summary()
        max_mb = _mb if max_mb is None else max_mb
        has_gpu = _gpu if has_gpu is None else has_gpu
    if not has_gpu:
        return "A"
    # B 档 MiniCPM-o 4.5 约 6GB。
    if max_mb and max_mb >= 6000:
        return "B"
    return "A"


def interactive_select() -> str:
    """AB 两档选择（克隆界面 / 启动时）。返回最终生效的主脑 tag（"" = 跳过）。

    A 档 Gemma 系（单选，档内按硬件再挑一个）· B 档 MiniCPM-o 全模态（单）。
    选定后经 model_catalog.save_tier 持久化档位并联动 OLLAMA_MODEL。
    非交互终端返回推荐档位的主脑，不阻塞。
    """
    from core import cli_render as r
    from core import model_catalog as mc
    from core.ascii_art import Colors

    max_mb, has_gpu, hw = get_compute_summary()
    rec_tier = recommend_tier(has_gpu, max_mb)
    tiers = mc.all_tiers()

    def _resolve_brain(tier_key: str) -> str:
        """档内定主脑：single 档按硬件在档内挑；composite 取档内第一个本地对话模型。"""
        specs = mc.tier_models(tier_key)
        local = [s for s in specs if s.source == "local"]
        if not local:
            return ""
        tier = mc.get_tier(tier_key)
        if tier and tier.kind == "single":
            # 档内按硬件推荐：挑装得下的最强一个
            rec = recommend(max_mb, has_gpu)
            for s in local:
                if s.tag == rec:
                    return s.tag
            return local[0].tag
        return local[0].tag  # composite：对话主脑取第一个本地模型（如 MiniCPM-o）

    if not (sys.stdin and sys.stdin.isatty()):
        # 非交互：用推荐档，持久化并返回主脑
        brain = _resolve_brain(rec_tier)
        mc.save_tier(rec_tier, main_brain=brain)
        return brain

    def _c(t, color):
        return f"{color}{t}{Colors.ENDC}" if r._use_color() else t

    print()
    print("  " + _c("选择 AI 主脑档位", Colors.BOLD + Colors.CYAN) + _c("  (AB 两档 · 本地原生多模态)", Colors.DIM))
    r.rule()
    r.phase("硬件", hw, "info")
    r.phase("推荐", f"{rec_tier} 档  ←（按你的实际硬件）", "ok")
    print()
    keys = [t.key for t in tiers]
    for i, t in enumerate(tiers, 1):
        is_rec = t.key == rec_tier
        marker = _c("▸", Colors.GREEN) if is_rec else " "
        num = _c(f"[{i}]", Colors.BOLD if is_rec else Colors.DIM)
        io = mc.tier_effective_io(t.key)
        io_txt = f"看:{io.vision} 听:{io.audio_in} 说:{io.audio_out}"
        tail = _c("  ← 推荐", Colors.GREEN) if is_rec else ""
        print(f"  {marker} {num} {_c(t.label, Colors.BOLD if is_rec else Colors.ENDC)}{tail}")
        print(f"         {_c(t.desc, Colors.DIM)}")
        print(
            f"         {_c(io_txt, Colors.DIM)} · 模型: "
            + _c(", ".join(m.name for m in mc.tier_models(t.key)), Colors.DIM)
        )
    r.rule()
    print("  " + _c("回车=用推荐档 · 数字=选档 · s=跳过下载", Colors.DIM))
    while True:
        try:
            choice = input(f"  请选择档位 [1-{len(tiers)} / 回车 / s]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            brain = _resolve_brain(rec_tier)
            mc.save_tier(rec_tier, main_brain=brain)
            return brain
        if choice == "":
            brain = _resolve_brain(rec_tier)
            mc.save_tier(rec_tier, main_brain=brain)
            return brain
        if choice == "s":
            return ""
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                key = keys[idx]
                brain = _resolve_brain(key)
                mc.save_tier(key, main_brain=brain)
                return brain
        print("  " + _c("⚠ 无效输入，请重新选择（或直接回车用推荐档）。", Colors.YELLOW))


def background_pull(tag: str) -> None:
    """若本地 Ollama 没有该主脑模型，则后台 ollama pull（不阻塞启动）。"""
    import shutil
    import subprocess
    import threading

    if not tag:
        return
    if not shutil.which("ollama"):
        # 修复:之前这里直接 return,不打印任何东西——真机复现过用户反馈"看到
        # [尝试]任何 HuggingFace 下载模型,Ollama 上没找到模型就默认直接跳过了"，
        # 排查后发现根因就是这个静默 return:找不到 ollama 命令时,不光跳过了
        # `ollama pull`,连 HuggingFace 回退(download_and_import_to_ollama 需要
        # `ollama create` 才能把下载的 GGUF 导入成本地模型,同样依赖这个命令)
        # 也一起被跳过,但控制台【什么提示都没有】,用户只会觉得"什么都没发生"。
        # 这里改成至少打印一句清楚的原因,不再彻底沉默。
        print(
            "     未检测到 ollama 命令,跳过本地主脑模型拉取与 HuggingFace 回退"
            "(两者都需要 ollama 命令来导入/运行模型)。"
            "可先在「模型」tab 填一个云端 API Key 作为主力兜底，"
            "或安装 Ollama: https://ollama.com/download"
        )
        return

    def _pull() -> None:
        try:
            import httpx

            # ollama 地址解析收口到 core.ollama_endpoint 唯一属主(空值/缺协议头都兜底)。
            from core.ollama_endpoint import resolve_ollama_base_url

            base = resolve_ollama_base_url()
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
                    print(
                        f"  ⚠ Ollama 列表里有 {matched}，但 /api/show 核实不可用"
                        f"(status={show_r.status_code})——当作未安装，重新拉取。"
                    )
                except Exception as exc:
                    print(f"  ⚠ Ollama 列表里有 {matched}，但核实可用性失败({exc})——当作未安装，重新拉取。")
            print(f"  ▶ 正在后台拉取本地主脑模型 ollama pull {tag} …(不阻塞启动)")
            proc = subprocess.run(
                ["ollama", "pull", tag],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
            )
            if proc.returncode == 0:
                print(f"  ✓ 本地主脑模型已就绪:{tag}")
                return
            # 关键:不要静默吞掉失败。联网核实过(open-webui issue #23471 等多个
            # 独立来源一致印证):gemma4 系列需要较新 Ollama 客户端才能解析其
            # manifest,旧版会在 "pulling manifest" 就失败——这正是最常见根因。
            _err = (proc.stderr or proc.stdout or "").strip()[:300]
            print(f"  ⚠ 拉取 {tag} 失败 — {_err}")
            try:
                _ver = subprocess.run(
                    ["ollama", "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                ).stdout.strip()
                print(f"     当前 Ollama 版本:{_ver or '(未知)'}")
                _too_old = is_ollama_version_too_old(_ver)
                if _too_old is True:
                    print(
                        f"     ⚠ 你的 Ollama 版本明显低于 {root} 系列所需的最低版本"
                        f"(经核实需 ≥ {'.'.join(map(str, MIN_OLLAMA_VERSION_FOR_GEMMA4))}，"
                        f"建议直接升到最新版)。这几乎可以肯定就是拉取失败的原因。"
                    )
                    print(
                        f"     Windows 升级:winget upgrade Ollama.Ollama ,"
                        f"或从 https://ollama.com/download/windows 下载最新安装包直接覆盖安装"
                        f"(会保留已下载的模型)。升级后重跑 `ollama pull {tag}` 应该就能成功。"
                    )
                elif _too_old is False:
                    print(
                        "     Ollama 版本本身不算旧，拉取失败更可能是网络/registry 问题，"
                        "或该 tag 确实不在库里——继续尝试 HuggingFace 回退。"
                    )
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
                print("     HuggingFace 回退候选也都试过,未能导入成功。")

            print("     可先在「模型」tab 填一个云端 API Key(DeepSeek/通义/Claude…)作为主力兜底,")
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
# 同样派生自 catalog（模块导入期求值一次；catalog 是静态定义，够用）。
MODELS: Dict[str, Dict] = {tag: {"name": lbl[0], "modalities": lbl[1]} for tag, lbl in _labels().items()}
DEFAULT_MODEL = _default_tag()
