#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/setup_reasoning_slot.py — 把 C 档的**推理位**真正架起来

这个脚本补的是"从克隆到使用"链条上唯一还断着的一环。之前的状态是：

* 目录里登记了推理位（``qwen3.6:35b-a3b``，18 GB 权重 / 7.3 GB 驻留）；
* 选档界面能选 C 档，选完还会告诉你"这一位跑不起来"；
* **但没有任何一处告诉你、或者帮你，把它弄起来。** 缺口文案里那句
  "改用 llama-server --n-cpu-moe N，再用 GALAXY_LOCAL_OPENAI_URL 接进来"
  对着一个刚克隆完仓库的人等于没说 —— N 是多少？权重从哪来？URL 填什么？

为什么推理位必须走 llama-server 而不是进程内加载
================================================
7.3 GB 那个驻留量**完全建立在专家卸载生效上**（18 GB 权重里专家占大头，每 token
只激活约 3B，把专家留在内存、注意力留显存）。而实测：

.. code-block:: text

    llama_cpp 0.3.34（PyPI 最新）
      n_cpu_moe       在? False
      override_tensor 在? False

底层 ``llama_model_params`` 里是有 ``tensor_buft_overrides`` 的，但高层 ``Llama``
包装没把它透出来 —— 也就是说**进程内这条路做不到这次卸载**。llama.cpp 的
``llama-server`` 二进制支持 ``--n-cpu-moe``，所以推理位走"外部 server + OpenAI
兼容接口"这条路，由 ``GALAXY_LOCAL_OPENAI_URL`` 接进路由。

判据一律不在本文件里重造
========================
* 推理位是谁、要多大 → ``core.model_catalog``
* 专家卸载在不在 → ``core.local_model_backends.moe_offload_supported``
  （**进程内**那一条单独问 ``binding_moe_offload_supported``；哪条路生效问
  ``moe_offload_path``）
* llama-server 在哪、这个构建支持哪些旗标、命令行怎么拼 → ``core.llama_server``
* ``--n-cpu-moe N`` 的 N → ``core.compute_scheduler.ComputeScheduler._split_moe``
  （和真正加载时用的是同一条计算，不是另算一遍）
* 权重从哪个 repo 下、下哪个量化档 → ``core.hf_ollama_import_fallback``

**不下载 llama-server 二进制。** 本仓已明令不做 ``curl | sh`` 式的远程脚本执行，
下载并执行一个预编译二进制是同一类事。这里只负责找到它、并在找不到时给出准确的
获取方式，由用户自己装。

用法
----
    python scripts/setup_reasoning_slot.py              # 体检 + 给出可执行的下一步
    python scripts/setup_reasoning_slot.py --download   # 顺带把 GGUF 权重下下来
    python scripts/setup_reasoning_slot.py --write-env  # 把 GALAXY_LOCAL_OPENAI_* 写进 .env
    python scripts/setup_reasoning_slot.py --start      # 直接把 llama-server 拉起来
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

#: llama-server 默认监听端口。和 core/multi_llm_router.py 的 local_openai provider 对接。
DEFAULT_PORT = 18080

_C = {"INFO": "\033[0;34m", "OK": "\033[0;32m", "WARN": "\033[1;33m", "ERR": "\033[0;31m", "NC": "\033[0m"}


def _log(level: str, msg: str) -> None:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        print(f"[{level}] {msg}", flush=True)
    else:
        print(f"{_C.get(level, '')}[{level}]{_C['NC']} {msg}", flush=True)


def reasoning_slot() -> Tuple[str, int, int]:
    """(推理位 tag, 权重 MB, 声称的驻留 MB) —— 全部取自目录，本文件不登记模型。"""
    from core.model_catalog import SLOT_REASONING, get_model, model_for_role

    tag = model_for_role(SLOT_REASONING, "C")
    spec = get_model(tag) if tag else None
    if spec is None:
        return "", 0, 0
    return spec.tag, spec.size_mb(), spec.runtime_mb()


def find_llama_server() -> str:
    """llama-server 可执行文件路径；找不到返回 ""。

    **判据在 ``core.llama_server``,本文件只调用。** 原来这里自己找一遍(env → PATH
    三个候选名),后来运行时那一侧也要找,于是同一条规则有了两份 —— 而这正是本仓库
    最不容许的那种重复:两份会在"认不认 ``server`` 这个名字"上分叉,表现是脚本说
    找到了、运行时说没有。
    """
    from core.llama_server import llama_server_binary

    return llama_server_binary() or ""


def compute_n_cpu_moe(weight_mb: int) -> Optional[int]:
    """按**本机实测**显存/内存算 ``--n-cpu-moe`` 的 N；拆不动返回 None。

    走 ``ComputeScheduler.moe_split_from_profile``，也就是进程内加载时用的同一条路
    （连"从画像的哪两个字段读显存/内存"都是同一处）—— 命令行上给出的 N 和调度器心里
    那个 N 必须是同一个数，否则显存账两处对不上。

    这里最初是自己读画像的，读成了 ``gpus[0].total_vram_mb`` 和顶层
    ``available_ram_mb``：前者是总显存不是可用显存，后者在画像顶层**根本不存在**
    （真在 ``profile.cpu`` 上）。恒得 0 的内存让判据 3 恒不通过，于是无论什么硬件都
    报"拆不动"。取数的判据因此收进了调度器，这里只调用。
    """
    try:
        from core.compute_scheduler import ComputeScheduler

        return ComputeScheduler().moe_split_from_profile(weight_mb)
    except Exception as exc:  # noqa: BLE001
        _log("WARN", f"拆分层数算不出({exc})——命令里会留 N 占位，需按显存自行填")
        return None


def build_command(binary: str, gguf_path: str, n_cpu_moe: Optional[int], port: int) -> List[str]:
    """拼出可直接执行的 llama-server 命令行。

    **组装在 ``core.llama_server.build_server_args``,本文件只调用。** 与
    :func:`find_llama_server` 同一条理由;而且那一份还多做两件这里做不到的事:

    * 先看这个构建的 ``--help`` 里到底有没有那个旗标 —— 拼一条它不认识的旗标,
      要么服务起不来,要么被吞掉,而"被吞掉"正是专家卸载那个洞活了很久的方式;
    * 顺带把**草稿位**(``--spec-type``)一起拼上 —— 推理位声明了机制且真机实测
      为正时才拼,见 ``core.speculative_draft``。
    """
    from core.llama_server import build_server_args
    from core.speculative_draft import draft_spec_of, is_enabled, load_measurement

    tag, _w, _r = reasoning_slot()
    spec = draft_spec_of(tag)
    enabled = bool(tag) and is_enabled(tag)
    plan = build_server_args(
        model_path=gguf_path,
        port=port,
        alias=tag,
        n_gpu_layers=999,
        n_cpu_moe=int(n_cpu_moe or 0),
        draft_spec_type=spec.spec_type if enabled else "",
        draft_n_max=load_measurement(tag).n_max if enabled else 0,
        binary=binary,
    )
    for note in plan.notes:
        _log("WARN", note)
    return list(plan.argv)


def env_block(tag: str, port: int) -> Dict[str, str]:
    """接进路由要写的四个键 —— 键名与 ``core/routes/config_schema_registry.py`` 同源。"""
    return {
        "GALAXY_LOCAL_OPENAI_URL": f"http://127.0.0.1:{port}/v1",
        "GALAXY_LOCAL_OPENAI_MODEL": tag,
        # 声明"这个 server 供的是哪一位"——路由按槽位解析时靠它把请求投准。
        "GALAXY_LOCAL_OPENAI_SERVES": tag,
    }


def write_env(pairs: Dict[str, str], env_file: Path) -> None:
    """把键值合并进 .env：已存在的键**就地改**，不存在的追加。绝不重排、不丢注释。"""
    lines: List[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
    remaining = dict(pairs)
    out: List[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    if remaining:
        out.append("")
        out.append("# C 档推理位（llama-server + 专家卸载）—— scripts/setup_reasoning_slot.py 生成")
        out.extend(f"{k}={v}" for k, v in remaining.items())
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    _log("OK", f"已写入 {env_file}")


def main() -> int:
    ap = argparse.ArgumentParser(description="架起 C 档推理位（llama-server + 专家卸载）")
    ap.add_argument("--download", action="store_true", help="没有 GGUF 就从 HuggingFace 下（约 18 GB）")
    ap.add_argument("--write-env", action="store_true", help="把 GALAXY_LOCAL_OPENAI_* 写进 .env")
    ap.add_argument("--start", action="store_true", help="直接把 llama-server 拉起来（前台运行）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("GALAXY_LOCAL_OPENAI_PORT", DEFAULT_PORT)))
    args = ap.parse_args()

    tag, weight_mb, runtime_mb = reasoning_slot()
    if not tag:
        _log("ERR", "目录里没有 C 档推理位 —— 这个脚本没事可做")
        return 1
    print()
    _log("INFO", f"推理位: {tag}  权重 {weight_mb} MB → 声称驻留 {runtime_mb} MB（靠专家卸载）")

    # 1. 进程内到底行不行？行的话根本不需要这个脚本。
    try:
        from core.local_model_backends import binding_moe_offload_supported

        in_process_ok = binding_moe_offload_supported()
    except Exception:  # noqa: BLE001
        in_process_ok = False
    if in_process_ok:
        _log("OK", "装着的 llama-cpp-python 支持专家卸载 —— 推理位可直接进程内加载，无需 llama-server")
        _log("INFO", "接着往下走只是为了另起一个 server；一般用不到，直接启动主程序即可")
    # 哪条路在扛这件事 —— 合成一个布尔的话，排障的人不知道该去装库还是去装二进制。
    try:
        from core.local_model_backends import moe_offload_path

        _PATH_ZH = {"binding": "进程内（llama-cpp-python）", "server": "llama-server 子进程", "none": "两条都不行"}
        _log("INFO", f"专家卸载当前走: {_PATH_ZH.get(moe_offload_path(), moe_offload_path())}")
    except Exception as exc:  # noqa: BLE001
        _log("WARN", f"专家卸载路径问不出来: {exc}")

    # 2. 权重
    from core.hf_ollama_import_fallback import download_gguf

    gguf = _existing_gguf(tag)
    if gguf:
        _log("OK", f"已有权重: {gguf}")
    elif args.download:
        gguf = download_gguf(tag) or ""
        if not gguf:
            _log("ERR", "权重下载失败 —— 上面列了试过的每个候选 repo 和失败原因")
            return 1
    else:
        _log("WARN", f"本地没有 {tag} 的 GGUF。加 --download 下载（约 {weight_mb} MB）")

    # 3. 二进制
    binary = find_llama_server()
    if binary:
        _log("OK", f"llama-server: {binary}")
    else:
        _log("WARN", "PATH 上没有 llama-server —— 这个脚本**不会**替你下载并执行二进制")
        print(
            "        自行获取（任选其一）：\n"
            "          · 源码编译： git clone https://github.com/ggml-org/llama.cpp\n"
            "                       cmake -B build -DGGML_CUDA=ON && cmake --build build -j --target llama-server\n"
            "          · 包管理器： brew install llama.cpp   /   你的发行版对应包\n"
            "          · 官方 release 的预编译包（自行核对校验和后解压）\n"
            "        装好后若不在 PATH 上，用 GALAXY_LLAMA_SERVER_BIN=/绝对/路径 指过来。"
        )

    # 4. 拆分层数 + 完整命令
    n = compute_n_cpu_moe(weight_mb)
    if n:
        _log("OK", f"按本机实测显存/内存算出 --n-cpu-moe {n}（与调度器同一条计算）")
    else:
        _log("WARN", "本机拆不动（显存装不下共享层，或内存兜不住被卸的专家）—— 见下方说明")
    cmd = build_command(binary or "llama-server", gguf or f"<{tag} 的 .gguf 路径>", n, args.port)
    print()
    _log("INFO", "启动推理位：")
    print("        " + " ".join(cmd))

    # 5. 接进路由
    pairs = env_block(tag, args.port)
    print()
    _log("INFO", "接进路由（三个键；面板「设置」里也能填）：")
    for k, v in pairs.items():
        print(f"        {k}={v}")
    if args.write_env:
        write_env(pairs, PROJECT_ROOT / ".env")

    # 6. 真拉起来
    if args.start:
        if not binary:
            _log("ERR", "没有 llama-server，--start 无从谈起")
            return 1
        if not gguf:
            _log("ERR", "没有权重，--start 无从谈起（先跑一次 --download）")
            return 1
        _log("INFO", "启动中（Ctrl-C 停止）…")
        return subprocess.call(cmd)
    print()
    _log("OK", "体检完毕。上面两步做完，再启动主程序，推理位就在岗了。")
    return 0


def _existing_gguf(tag: str) -> str:
    """在下载缓存里找这个 tag 已经下好的 GGUF；没有返回 ""。

    只扫 :func:`core.hf_ollama_import_fallback.gguf_cache_dir` 那棵树下、该 tag 的
    候选 repo 目录 —— 不做全盘搜索（那是 ``core/routes/models.py`` 的有界扫描要
    解决的另一个问题，这里没有必要引入同样的风险）。
    """
    try:
        from core.hf_ollama_import_fallback import HF_GGUF_CANDIDATES, gguf_cache_dir
    except Exception:  # noqa: BLE001
        return ""
    for repo_id in HF_GGUF_CANDIDATES.get(tag, []):
        d = Path(gguf_cache_dir(repo_id))
        if not d.is_dir():
            continue
        found = sorted(d.rglob("*.gguf"))
        if found:
            return str(found[0])
    return ""


if __name__ == "__main__":
    sys.exit(main())
