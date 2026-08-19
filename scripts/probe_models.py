#!/usr/bin/env python3
"""scripts/probe_models.py — 在**你自己的机器上**问出来：装了什么、能调什么、填错了没

为什么是一个脚本而不是一条测试
==============================
CI 与开发沙箱都够不到 Ollama 与各家 API（出口被拦）。而这些问题的答案只在
**真正跑这套东西的那台机器上**：本地实际装了哪些模型、那把 key 到底能调什么、
``base_url`` 有没有改版。所以做成一条随时可跑的命令，输出贴回来即可据以改配置。

它只读
======
不装、不拉、不改任何配置。发现问题只报告 —— 改什么由人决定。

用法::

    python3 scripts/probe_models.py            # 本地 + 云端全查
    python3 scripts/probe_models.py --local    # 只查本地装了什么
    python3 scripts/probe_models.py --cloud    # 只查云端配置对不对
    python3 scripts/probe_models.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _local_section(as_json: bool) -> dict:
    from core.model_probe import probe_local_models

    outcome, facts = probe_local_models()
    payload = {
        "status": outcome.status,
        "detail": outcome.detail,
        "models": [
            {
                "tag": f.tag,
                "size_mb": f.size_mb,
                "parameter_size": f.parameter_size,
                "quantization": f.quantization,
                "context_length": f.context_length,
                "capabilities": list(f.capabilities),
                "healthy": f.healthy,
            }
            for f in facts
        ],
    }
    if as_json:
        return payload

    print("═══ 本地（Ollama）═══")
    if outcome.status == "unreachable":
        print(f"  ✗ 没问到：{outcome.detail}")
        print("    （Ollama 没起、或地址不对。这不代表你没装模型。）")
        return payload
    if outcome.status == "empty":
        print(f"  · {outcome.detail}")
        return payload
    print(f"  {'tag':<30}{'规模':>8}{'量化':>10}{'权重MB':>9}{'上下文':>10}  能力")
    for f in facts:
        flag = "" if f.healthy else "  ⚠ /api/show 打不开（残缺 manifest）"
        caps = ",".join(f.capabilities) or "-"
        print(
            f"  {f.tag:<30}{f.parameter_size:>8}{f.quantization:>10}"
            f"{f.size_mb:>9}{f.context_length:>10}  {caps}{flag}"
        )
    print()
    print("  ↑ 这几栏正是 core/model_catalog.py 一条记录要填的东西。")
    print("    唯独 runtime_mb（实测运行时显存）问不出来 —— 它要真加载一次才知道，")
    print("    而那一栏错了的后果是准入判'放得下'、加载到一半 OOM。填 0 会如实退回权重大小。")
    return payload


def _cloud_section(as_json: bool) -> dict:
    from core.model_probe import audit_provider_catalog, format_audit_report

    findings = audit_provider_catalog()
    payload = {"findings": [f.to_dict() for f in findings]}
    if as_json:
        return payload
    print("═══ 云端（配的那张表 vs 实际能调的）═══")
    print(format_audit_report(findings))
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="只读探测：本地装了什么 / 云端能调什么 / 配置对不对")
    ap.add_argument("--local", action="store_true", help="只查本地")
    ap.add_argument("--cloud", action="store_true", help="只查云端")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    both = not (args.local or args.cloud)
    out = {}
    if both or args.local:
        out["local"] = _local_section(args.json)
        if not args.json:
            print()
    if both or args.cloud:
        out["cloud"] = _cloud_section(args.json)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
