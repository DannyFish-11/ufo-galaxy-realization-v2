#!/usr/bin/env python3
"""C 档(专家卸载)与 D 档(投机解码)现在差什么。

为什么单独有这一条命令
----------------------
这两档的就绪状态此前散在三处:``probe_models.py --draft`` 说草稿位、
``local_model_backends`` 说后端选哪条路、``llama_server`` 说二进制在不在。
要判断"我还差什么"得自己把三处拼起来 —— 而拼错的方向通常是**以为自己配好了**。

这个脚本不新造任何判据,只把那几处已有的判据问一遍,然后回答一句话:
**下一步该干什么。**

它是只读的:不下载、不加载模型、不起服务。

用法::

    python3 scripts/local_tier_doctor.py
    python3 scripts/local_tier_doctor.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _collect() -> Dict[str, Any]:
    """把各处已有的判据问一遍。任何一处问不到都如实记 ``None``,不猜。"""
    out: Dict[str, Any] = {}

    try:
        from core.llama_server import llama_server_binary, server_supported_flags

        binary = llama_server_binary()
        out["llama_server_binary"] = binary
        # 二进制不在时 server_supported_flags 返回空集合 —— 那是"问不到",
        # 与"问过了、这个构建没有这些旗标"是两件事,所以下面分开报。
        flags = sorted(server_supported_flags()) if binary else []
        out["llama_server_flags_probed"] = bool(binary)
        out["llama_server_has_n_cpu_moe"] = ("--n-cpu-moe" in flags) if binary else None
        out["llama_server_has_spec_type"] = ("--spec-type" in flags) if binary else None
    except Exception as exc:  # noqa: BLE001
        out["llama_server_error"] = repr(exc)

    try:
        from core.local_model_backends import moe_offload_path, moe_offload_supported

        out["moe_offload_path"] = moe_offload_path()
        out["moe_offload_supported"] = moe_offload_supported()
    except Exception as exc:  # noqa: BLE001
        out["moe_error"] = repr(exc)

    try:
        from core.speculative_draft import llama_binding_draft_support

        out["binding_draft_support"] = llama_binding_draft_support()
    except Exception as exc:  # noqa: BLE001
        out["draft_error"] = repr(exc)

    return out


def _next_steps(facts: Dict[str, Any]) -> List[str]:
    """还差什么。**没有要做的就返回空列表** —— 不硬凑建议。"""
    steps: List[str] = []

    if not facts.get("llama_server_binary"):
        steps.append(
            "装 llama.cpp 的 llama-server(或用 GALAXY_LLAMA_SERVER_BIN 指到你自建的那份)。\n"
            "      这一个二进制同时解开两档:C 档的 --n-cpu-moe 专家卸载、D 档的 --spec-type 草稿位。\n"
            "      llama-cpp-python 的进程内绑定**两个都不透出**,所以没有它这两档接不上。\n"
            "      从源码编译的话产物在 build/bin/,本脚本会自动找那儿,不用手动加 PATH。"
        )
    else:
        if facts.get("llama_server_has_n_cpu_moe") is False:
            steps.append(
                "找到了 llama-server,但这个构建的 --help 里没有 --n-cpu-moe —— C 档的专家卸载用不上。\n"
                "      换一个较新的构建。"
            )
        if facts.get("llama_server_has_spec_type") is False:
            steps.append(
                "找到了 llama-server,但这个构建没有 --spec-type —— D 档的草稿位用不上。\n" "      换一个较新的构建。"
            )

    steps.append(
        "跑投机解码的真机实测(这一步**只能在你的机器上做**,数字不能由别处代填):\n"
        "        python3 scripts/probe_models.py --draft                      # 先看现状\n"
        "        python3 scripts/probe_models.py --draft --draft-label baseline\n"
        "        python3 scripts/probe_models.py --draft --draft-label 4\n"
        "        python3 scripts/probe_models.py --draft --draft-save         # 把实测记进目录\n"
        "      在此之前,草稿位那一维是 unknown = 没人查过,而 unknown 不会被当成可用。"
    )
    return steps


def _render(facts: Dict[str, Any]) -> str:
    lines = ["═══ 本地档位体检(C 档专家卸载 / D 档投机解码)═══", ""]

    binary = facts.get("llama_server_binary")
    lines.append(f"  llama-server:            {binary or '没找到'}")
    if binary:
        lines.append(f"    --n-cpu-moe(C 档):   {'有' if facts.get('llama_server_has_n_cpu_moe') else '没有'}")
        lines.append(f"    --spec-type(D 档):   {'有' if facts.get('llama_server_has_spec_type') else '没有'}")
    else:
        lines.append("    ↑ 旗标没探(二进制不在)—— 这是**问不到**,不是「问过了没有」")

    lines.append(f"  专家卸载当前走哪条路:    {facts.get('moe_offload_path', '判不出来')}")
    lines.append(f"  绑定层透出草稿位参数:    {facts.get('binding_draft_support', '判不出来')}")
    lines.append("")

    steps = _next_steps(facts)
    if steps:
        lines.append("  下一步:")
        for i, step in enumerate(steps, 1):
            lines.append(f"    {i}. {step}")
    else:
        lines.append("  两档都已就绪。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="机器可读")
    args = parser.parse_args()

    facts = _collect()
    if args.json:
        print(json.dumps({"facts": facts, "next_steps": _next_steps(facts)}, ensure_ascii=False, indent=2))
    else:
        print(_render(facts))
    # 体检本身不判失败:它是用来看的,不是闸。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
