"""
core/hf_ollama_import_fallback.py — Ollama 拉取失败时,从 HuggingFace 下载并导入
=================================================================================

背景
----
用户实测:``ollama pull gemma4:e2b`` 等在 "pulling manifest" 就失败——这几个
tag 不在用户能连到的 Ollama 库里(不论是版本太旧还是库里压根没有)。用户要求:
Ollama 没有的模型，默认直接从 Hugging Face 下载相关模型。

设计取舍
--------
既有的 ``core/huggingface_model_manager.py`` 能下载 GGUF/transformers 权重，但
下载下来的模型缺一个"谁来跑它"——``multi_llm_router`` 里的 ``hf_local`` provider
假设有个 OpenAI 兼容服务器监听在 ``http://localhost:16201/v1/hf``，但全仓库范围
内这个端点从未被实现过(纯 stub)。重新搭一个推理服务器(参数解析、并发、
上下文管理……)风险高、工作量大，且 Ollama 已经把这些都做对了。

所以这里选更稳的路径：把从 HF 下载来的 GGUF 文件，通过 ``ollama create`` 导入
成一个**本地自定义 Ollama 模型**，复用 Ollama 现成、已验证能跑的 serving 路径——
下游(路由/面板/tri-state)完全不用改一行，因为它就是个普通的本地 Ollama 模型。

关于候选 repo 是否真实存在
---------------------------
本模块运行环境（沙箱）出网被拦截，无法直接访问 huggingface.co 核实候选
repo ID。因此设计成"运行时校验"而非"硬编码相信"：对每个候选 repo，用
``HfApi().list_repo_files()`` 实际查询（在用户自己能联网的机器上执行），
查不到就换下一个候选，全部试完才失败——**正确性不依赖于这里猜的名字对不对，
只依赖于机制本身够健壮**。候选列表包含了一些较新/未必存在的猜测（如
"gemma-4" 系列，若真实存在会优先命中），以及训练数据里高置信度真实存在的
成熟视觉多模态模型（Gemma 3 / MiniCPM-V / Qwen2-VL 的社区 GGUF 量化版）作为
兜底，确保即使前面的猜测全部落空，也有较大概率成功导入一个能用的本地视觉
多模态模型。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.ModelSelection.HFFallback")

# ── 每个主脑档位的 HF GGUF 候选 repo（按优先级排列）──────────────────────
# 每档第一个是"如果 Ollama 库真有对应新模型，命中它"的乐观尝试；
# 后面是训练数据里高置信度真实存在、原生支持视觉的成熟开源模型的社区 GGUF
# 量化版，作为兜底——具体是否存在、是否真有 .gguf 文件，全部交给
# find_gguf_file() 在运行时用 HfApi 核实，猜错的候选会被自动跳过。
HF_GGUF_CANDIDATES: Dict[str, List[str]] = {
    "gemma4:12b": [
        "google/gemma-4-12b-it-GGUF",
        "bartowski/gemma-3-12b-it-GGUF",
        "bartowski/Qwen2-VL-7B-Instruct-GGUF",
        "bartowski/MiniCPM-V-2_6-GGUF",
    ],
    "openbmb/minicpm-o4.5": [
        "openbmb/MiniCPM-o-4_5-gguf",
        "openbmb/MiniCPM-o-2_6-gguf",
        "openbmb/MiniCPM-V-2_6-gguf",
        "bartowski/MiniCPM-V-2_6-GGUF",
    ],
    "gemma4:e4b": [
        "google/gemma-4-E4B-it-GGUF",
        "bartowski/gemma-3-4b-it-GGUF",
        "bartowski/Qwen2-VL-2B-Instruct-GGUF",
    ],
    "gemma4:e2b": [
        "google/gemma-4-e2b-it-GGUF",
        "bartowski/gemma-3-4b-it-GGUF",
        "vikhyatk/moondream2",
        "bartowski/Qwen2-VL-2B-Instruct-GGUF",
    ],
    # 双模型档的推理位。与上面同一套写法:先乐观试新名字,再落到训练数据里
    # 高置信度真实存在的同架构 MoE(Qwen3-30B-A3B 官方/社区 GGUF)。存不存在
    # 一律由 find_gguf_file() 运行时用 HfApi 核实,猜错的自动跳过。
    "qwen3.6:35b-a3b": [
        "Qwen/Qwen3.6-35B-A3B-GGUF",
        "unsloth/Qwen3.6-35B-A3B-GGUF",
        "Qwen/Qwen3-30B-A3B-GGUF",
        "unsloth/Qwen3-30B-A3B-GGUF",
        "bartowski/Qwen_Qwen3-30B-A3B-GGUF",
    ],
    # D 档推理位。官方 GGUF 优先(用户选定 v2 —— 它的发布说明明确修了 looping);
    # 再落到同一模型的初版,最后是它的底座 Qwen3.5-9B 系。与上面同一套写法:
    # 存不存在一律由 find_gguf_file() 运行时用 HfApi 核实,猜错的自动跳过。
    #
    # 注意 Ollama 上那个 richardyoung/qwythos-9b-abliterated 是**去审查改版**,
    # 与官方权重不是一个东西,故意不列进来 —— 回退不该悄悄把用户换成另一个模型。
    "qwythos-9b-v2": [
        "empero-ai/Qwythos-9B-v2-GGUF",
        "empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF",
        "Qwen/Qwen3.5-9B-GGUF",
        "bartowski/Qwen_Qwen3.5-9B-GGUF",
    ],
}

# CPU/轻量机器的默认下载体积预算（MB）；超过的候选文件直接跳过，避免下载几十 GB。
DEFAULT_SIZE_BUDGET_MB = 6000


def _size_budget_for(tag: str) -> int:
    """这个 tag 该给多大的下载预算(MB)。

    固定 6000 是给"轻量视觉主脑"定的。对大权重型号,它的后果**不是**下载失败——
    实测(真实调用 :func:`find_gguf_file`,注入一个多量化档的 repo 清单):

    .. code-block:: text

        repo 里有 Q2_K(11G) / Q4_K_M(18G) / Q8_0(32G)
        预算 6000  -> 选中 Q2_K.gguf      ← 全部超预算,走"选最小的"分支
        预算 19800 -> 选中 Q4_K_M.gguf    ← Q4 在预算内,prefer_quant 生效

    也就是说它会**静默降到最小的量化档**,而且那条分支绕过了 ``prefer_quant``。
    下载成功、导入成功、什么都不报错 —— 用户拿到的只是一个被过度量化、质量
    明显更差的模型,而他配的是另一个。比直接失败更难查。

    目录里登记过权重大小的型号就按它自己的大小放行(再留 10% 余量给量化档位
    差异);没登记的维持原默认。
    """
    try:
        from core.model_catalog import get_model  # noqa: PLC0415

        spec = get_model(tag)
        weight_mb = spec.size_mb() if spec is not None else 0
    except Exception:  # noqa: BLE001
        weight_mb = 0
    return max(DEFAULT_SIZE_BUDGET_MB, int(weight_mb * 1.1)) if weight_mb else DEFAULT_SIZE_BUDGET_MB


def _default_list_repo_files(repo_id: str) -> List[str]:
    from huggingface_hub import HfApi

    return HfApi().list_repo_files(repo_id)


def _default_file_sizes(repo_id: str, filenames: List[str]) -> Dict[str, int]:
    """返回 {filename: size_bytes}；查不到的文件不出现在结果里（不阻断流程）。"""
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo_id, files_metadata=True)
        sizes = {}
        for f in getattr(info, "siblings", None) or []:
            if f.rfilename in filenames and getattr(f, "size", None):
                sizes[f.rfilename] = f.size
        return sizes
    except Exception:
        return {}


def find_gguf_file(
    repo_id: str,
    *,
    prefer_quant: str = "q4",
    size_budget_mb: int = DEFAULT_SIZE_BUDGET_MB,
    list_repo_files: Callable[[str], List[str]] = _default_list_repo_files,
    get_file_sizes: Callable[[str, List[str]], Dict[str, int]] = _default_file_sizes,
) -> Optional[str]:
    """在给定 repo 里找一个体积预算内、优先匹配量化档位的 .gguf 文件名。

    repo 不存在 / 无 .gguf 文件 / 网络异常都返回 None（调用方据此换下一个候选），
    绝不抛出——这是"运行时校验候选是否真实存在"的核心探针。
    """
    try:
        files = list_repo_files(repo_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("HF fallback: repo 不可用 %s (%s)", repo_id, exc)
        return None

    gguf_files = [f for f in files if f.lower().endswith(".gguf")]
    if not gguf_files:
        return None

    sizes = get_file_sizes(repo_id, gguf_files)

    def _within_budget(fname: str) -> bool:
        sz = sizes.get(fname)
        return sz is None or sz <= size_budget_mb * 1024 * 1024

    candidates = [f for f in gguf_files if _within_budget(f)]
    if not candidates:
        # 全部文件都超预算——仍然选体积最小的一个,好过完全放弃。
        if sizes:
            return min(gguf_files, key=lambda f: sizes.get(f, float("inf")))
        return None

    preferred = [f for f in candidates if prefer_quant.lower() in f.lower()]
    return (preferred or candidates)[0]


def download_and_import_to_ollama(
    tag: str,
    *,
    local_model_name: Optional[str] = None,
    candidates: Optional[List[str]] = None,
    # 0 = 按 tag 自己的权重大小推(见 _size_budget_for);显式传值一律尊重。
    size_budget_mb: int = 0,
    find_gguf_file_fn: Callable[..., Optional[str]] = find_gguf_file,
    hf_hub_download_fn: Optional[Callable[..., str]] = None,
    ollama_create_fn: Optional[Callable[[str, str], bool]] = None,
) -> Optional[str]:
    """Ollama 库里没有 ``tag`` 时的兜底：从 HuggingFace 下载 GGUF 权重,
    通过 ``ollama create`` 导入成本地自定义模型。

    按 HF_GGUF_CANDIDATES[tag] 顺序尝试每个候选 repo；第一个"确实存在、有
    .gguf 文件、下载成功、ollama create 成功"的候选即采用，返回新的本地
    Ollama 模型名(供调用方 ``save_choice()``/设 ``OLLAMA_MODEL`` 用)。

    全部候选失败则返回 None（调用方保留既有的"提示用云端 Key 兜底"逻辑）。
    容错：任何单个候选的异常都只跳过该候选，不影响其余候选/不向上抛出。
    """
    if not shutil.which("ollama"):
        return None

    cand_list = candidates if candidates is not None else HF_GGUF_CANDIDATES.get(tag, [])
    if not cand_list:
        return None

    size_budget_mb = size_budget_mb or _size_budget_for(tag)

    local_name = local_model_name or ("galaxy-" + tag.replace("/", "-").replace(":", "-") + "-hf")

    if hf_hub_download_fn is None:

        def hf_hub_download_fn(repo_id: str, filename: str, local_dir: str) -> str:  # type: ignore[no-redef]
            from huggingface_hub import hf_hub_download

            return hf_hub_download(
                repo_id=repo_id, filename=filename, local_dir=local_dir, local_dir_use_symlinks=False
            )

    if ollama_create_fn is None:

        def ollama_create_fn(name: str, gguf_path: str) -> bool:  # type: ignore[no-redef]
            return _ollama_create(name, gguf_path)

    # 关键修复:之前"候选无匹配/不存在"只走 logger.info()——这个 app 的启动横幅
    # 全部走 print()/WARNING 级日志，INFO 默认不显示在控制台。真机复现过:全部
    # 候选都因 repo 不存在/无 .gguf 而跳过时，用户在控制台【什么都看不到】，
    # 只当"HF 回退好像没跑"。这里把每个候选的尝试与结果都用 print() 打出来，
    # 不管成败——下次真机复现，日志本身就能看出到底试了哪些 repo、每个为什么
    # 没成，而不必再靠猜测候选名字对不对。
    tried: List[str] = []
    for repo_id in cand_list:
        try:
            gguf_filename = find_gguf_file_fn(repo_id, size_budget_mb=size_budget_mb)
            if not gguf_filename:
                print(
                    f"     · HuggingFace 候选 {repo_id}:未找到匹配的 .gguf 文件(repo 不存在，或没有 GGUF 量化版)，跳过"
                )
                tried.append(repo_id)
                continue

            print(f"  ▶  Ollama 无 {tag}，尝试从 HuggingFace 回退下载:{repo_id} / {gguf_filename} …")
            gguf_path = hf_hub_download_fn(repo_id, gguf_filename, gguf_cache_dir(repo_id))

            print(f"  ▶  下载完成，正在导入 Ollama:ollama create {local_name} …")
            if ollama_create_fn(local_name, gguf_path):
                print(f"  ✓ 已从 HuggingFace({repo_id})导入本地模型:{local_name}")
                return local_name
            else:
                print(f"     · HuggingFace 候选 {repo_id}:下载成功但 `ollama create` 导入失败，换下一个候选")
                tried.append(repo_id)
        except Exception as exc:  # noqa: BLE001
            print(f"     · HuggingFace 候选 {repo_id}:失败({exc})，换下一个候选")
            tried.append(repo_id)
            continue

    if tried:
        print(f"     全部 {len(tried)} 个 HuggingFace 候选均未成功:{', '.join(tried)}")
    return None


def _ollama_create(name: str, gguf_path: str) -> bool:
    """写最小 Modelfile 并执行 ``ollama create <name> -f <modelfile>``。"""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".modelfile", delete=False, encoding="utf-8") as f:
            f.write(f"FROM {gguf_path}\n")
            modelfile_path = f.name
        proc = subprocess.run(
            ["ollama", "create", name, "-f", modelfile_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        return proc.returncode == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("ollama create 异常: %s", exc)
        return False
    finally:
        try:
            os.unlink(modelfile_path)
        except Exception:
            pass


def gguf_cache_dir(repo_id: str) -> str:
    """某个 repo 的 GGUF 落盘目录 —— 下载路径**只此一处**，别处不许再拼。

    ``download_and_import_to_ollama`` 和 :func:`download_gguf` 必须落到同一棵树，
    否则同一个权重会被下两遍(18 GB 一份)，而且清理脚本只认得其中一棵。
    """
    return os.path.join(str(Path.home() / ".galaxy" / "hf_gguf_cache"), repo_id.replace("/", "__"))


def download_gguf(
    tag: str,
    *,
    candidates: Optional[List[str]] = None,
    size_budget_mb: int = 0,
    find_gguf_file_fn: Callable[..., Optional[str]] = find_gguf_file,
    hf_hub_download_fn: Optional[Callable[..., str]] = None,
) -> Optional[str]:
    """只把 GGUF **下到本地**，返回文件路径；不导入 Ollama、不需要 ollama 命令。

    为什么要和 :func:`download_and_import_to_ollama` 分开
    ====================================================
    那一个的终点是 ``ollama create``，因此开头就 ``if not shutil.which("ollama"):
    return None``。可 C 档推理位根本不走 Ollama —— 它要么被 llama-cpp-python 直接
    加载，要么喂给 ``llama-server``，两条路要的都只是**一个 GGUF 文件路径**。用那个
    函数的话，一台没装 Ollama 的机器会在第一行就静默返回 None，而它其实完全下得动。

    候选表、体积预算、量化档偏好三条判据全部复用同一处（``HF_GGUF_CANDIDATES`` /
    :func:`_size_budget_for` / :func:`find_gguf_file`），不另起一套。
    """
    cand_list = candidates if candidates is not None else HF_GGUF_CANDIDATES.get(tag, [])
    if not cand_list:
        return None
    size_budget_mb = size_budget_mb or _size_budget_for(tag)

    if hf_hub_download_fn is None:

        def hf_hub_download_fn(repo_id: str, filename: str, local_dir: str) -> str:  # type: ignore[no-redef]
            from huggingface_hub import hf_hub_download

            return hf_hub_download(
                repo_id=repo_id, filename=filename, local_dir=local_dir, local_dir_use_symlinks=False
            )

    tried: List[str] = []
    for repo_id in cand_list:
        try:
            gguf_filename = find_gguf_file_fn(repo_id, size_budget_mb=size_budget_mb)
            if not gguf_filename:
                print(f"     · HuggingFace 候选 {repo_id}:未找到匹配的 .gguf 文件，跳过")
                tried.append(repo_id)
                continue
            print(f"  ▶  下载 {tag} 权重:{repo_id} / {gguf_filename}(预算 {size_budget_mb} MB)…")
            path = hf_hub_download_fn(repo_id, gguf_filename, gguf_cache_dir(repo_id))
            print(f"  ✓ 已落盘:{path}")
            return path
        except Exception as exc:  # noqa: BLE001
            print(f"     · HuggingFace 候选 {repo_id}:失败({exc})，换下一个候选")
            tried.append(repo_id)
            continue
    if tried:
        print(f"     全部 {len(tried)} 个 HuggingFace 候选均未成功:{', '.join(tried)}")
    return None
