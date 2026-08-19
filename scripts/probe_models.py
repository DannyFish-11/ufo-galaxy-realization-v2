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

投机解码(草稿位)::

    python3 scripts/probe_models.py --draft                 # 看声明 + 这台机器接不接得上
    # 接得上才有下面两趟。llama-server 的草稿位旗标是**启动参数**,一个进程里切不了,
    # 所以要人重起一次服务,并且**由人告诉这个脚本这一趟是哪个配置**:
    python3 scripts/probe_models.py --draft --draft-label baseline   # 不带旗标起的那趟
    python3 scripts/probe_models.py --draft --draft-label 4          # --spec-draft-n-max 4 那趟
    python3 scripts/probe_models.py --draft --draft-save             # 两趟都有了 → 落盘,据此启用
    python3 scripts/probe_models.py --draft --draft-sweep            # 进程内一把扫完(需绑定透出参数)

**默认永远是关。** 公开实测里同一件事既有 +2.69x 也有净 -44.6%,方向取决于机器
不取决于代码;而块大小取默认 15 恰恰是常见的错误答案(同机器上取 4 才 +27%)。
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


def _draft_section(as_json: bool, *, label: str = "", save: bool = False, sweep: bool = False) -> dict:
    from core.draft_benchmark import (
        BenchRun,
        benchmark_draft,
        format_bench_report,
        measure_endpoint,
        verdict_from_labels,
    )
    from core.local_model_backends import moe_offload_path, moe_offload_supported
    from core.model_catalog import active_tags, load_tier
    from core.speculative_draft import (
        draft_spec_of,
        llama_binding_draft_support,
        load_labelled_runs,
        load_measurement,
        save_labelled_run,
        save_measurement,
    )

    tier = load_tier()
    binding, found = llama_binding_draft_support()
    tags = [t for t in active_tags(tier) if draft_spec_of(t).is_settled]
    payload: dict = {
        "tier": tier,
        "binding": binding,
        "binding_params": list(found),
        "moe_offload_supported": moe_offload_supported(),
        "moe_offload_path": moe_offload_path(),
        "models": [],
    }

    for tag in tags:
        spec = draft_spec_of(tag)
        runs = load_labelled_runs(tag)
        entry = {
            "tag": tag,
            "declared": spec.to_dict(),
            "labelled_runs": runs,
            "measurement": load_measurement(tag).to_dict(),
        }
        payload["models"].append(entry)

    # 量一趟(人声明这一趟是哪个配置)
    if label:
        base_url = os.environ.get("GALAXY_LOCAL_OPENAI_URL", "").strip()
        target = tags[-1] if tags else ""
        if not base_url:
            payload["measure_error"] = "没有 GALAXY_LOCAL_OPENAI_URL —— 量的是那个 OpenAI 兼容服务,得先告诉脚本它在哪"
        elif not target:
            payload["measure_error"] = f"{tier} 档在岗的型号里没有一个声明过草稿位"
        else:
            run = measure_endpoint(base_url, target)
            save_labelled_run(target, label, {"tokens": run.tokens, "seconds": run.seconds, "error": run.error})
            payload["measured"] = {"tag": target, "label": label, "tok_s": run.tok_s, "error": run.error}

    # 进程内一把扫完 —— 只有绑定真的透出参数时才走得通。走不通会如实判
    # unsupported 并给出唯一可用的那条路,而不是塞旗标碰运气。
    if sweep:
        payload["sweep"] = []
        for tag in tags:
            m, runs = benchmark_draft(tag)
            payload["sweep"].append({"tag": tag, "measurement": m.to_dict(), "report": format_bench_report(m, runs)})
            if save and m.verdict in ("faster", "slower"):
                save_measurement(m)

    # 合结论(只在两趟都有时才有意义)
    for entry in payload["models"]:
        raw = load_labelled_runs(entry["tag"])
        if not raw:
            continue
        labelled = {
            k: BenchRun(0, int(v.get("tokens") or 0), float(v.get("seconds") or 0.0), str(v.get("error") or ""))
            for k, v in raw.items()
        }
        verdict = verdict_from_labels(entry["tag"], labelled)
        entry["verdict"] = verdict.to_dict()
        if save and verdict.verdict in ("faster", "slower"):
            save_measurement(verdict)
            entry["saved"] = True

    if as_json:
        return payload

    print("═══ 投机解码（草稿位）═══")
    print(f"  当前档位: {tier}")
    print(f"  llama-cpp-python 透出草稿位参数: {binding}" + (f"  {list(found)}" if found else ""))
    if binding != "supported":
        print("    ↑ 这不是「慢」，是【接不上】。与 --n-cpu-moe 是同一个洞：")
        print(f"      （参考：专家卸载当前走哪条路 = {moe_offload_path()}）")
        print("      补救办法相同 —— 装一个 llama.cpp 的 llama-server（或用 GALAXY_LLAMA_SERVER_BIN")
        print("      指到你自己编的那份）。装上之后不需要再配什么：后端选择会自动改走它，")
        print("      服务由本进程起、地址自动导出。")
    if not payload["models"]:
        print(f"  {tier} 档在岗的型号里，没有一个填过草稿位声明（都是 unknown = 没人查过）。")
        return payload
    for entry in payload["models"]:
        d = entry["declared"]
        print(f"\n  {entry['tag']}")
        print(f"    声明: {d['mechanism']}" + (f"  spec_type={d['spec_type']}" if d["spec_type"] else ""))
        if d["note"]:
            print(f"    备注: {d['note']}")
        print(f"    额外权重: {'要外挂一份' if d['needs_external_checkpoint'] else '不用（草稿在目标模型自己身上）'}")
        runs = entry["labelled_runs"]
        if runs:
            print(f"    已量过的趟次: {', '.join(sorted(runs))}")
        v = entry.get("verdict")
        if v:
            print(
                f"    结论: {v['verdict']}  {v['speedup']:.2f}×  n_max={v['n_max']}  → "
                f"{'启用' if v['should_enable'] else '不启用'}"
            )
            if entry.get("saved"):
                print("    （已落盘，下次加载会据此启用/关闭）")
        else:
            print("    结论: untested —— 那不是「没问题」，是【没验成】。")
    for sw in payload.get("sweep", []):
        print()
        print(sw["report"])
    if "measure_error" in payload:
        print(f"\n  ✗ 这一趟没量成：{payload['measure_error']}")
    elif "measured" in payload:
        m = payload["measured"]
        print(
            f"\n  已量: {m['tag']}  标签={m['label']}  {m['tok_s']:.1f} tok/s"
            + (f"  错误={m['error']}" if m["error"] else "")
        )
        print("    （标签是**你声明的** —— 服务不报它自己是怎么起的。别把同一个配置量两遍。）")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="只读探测：本地装了什么 / 云端能调什么 / 配置对不对")
    ap.add_argument("--local", action="store_true", help="只查本地")
    ap.add_argument("--cloud", action="store_true", help="只查云端")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--draft", action="store_true", help="投机解码草稿位：声明 / 绑定能力 / 实测")
    ap.add_argument(
        "--draft-label",
        default="",
        metavar="baseline|N",
        help="量当前正在跑的那个服务一次，并由你声明这一趟是哪个配置",
    )
    ap.add_argument("--draft-save", action="store_true", help="两趟都有了 → 把结论落盘（这一步会改变运行时行为）")
    ap.add_argument("--draft-sweep", action="store_true", help="进程内基线+扫块大小一把跑完（需绑定透出草稿位参数）")
    args = ap.parse_args()

    if args.draft or args.draft_label or args.draft_save or args.draft_sweep:
        out = {"draft": _draft_section(args.json, label=args.draft_label, save=args.draft_save, sweep=args.draft_sweep)}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

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
