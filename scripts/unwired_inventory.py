#!/usr/bin/env python3
"""scripts/unwired_inventory.py — 「未接线 / 不可达」的代码到底是些什么东西。

``check_wiring.py`` 回答「有没有**新增**的未接线能力」，``check_reachability.py`` 回答「哪些模块
从真实入口走不到」。两者都只给名单。所有者要的是**先弄清楚是什么，再决定删还是接**
（2026-09-28），所以这里把同一批名单按事实分类：

- 形态：类方法 / 模块函数；
- 旁证：只有测试在引用（写了、测了、没接）/ 全仓连测试都没引用；
- 名字表明的角色：动作/变更、事件回调、计算/构造、只读查询、判定谓词、序列化、测试复位钩子；
- 所在子系统；
- 所在模块本身是否可达。

**分类只是按名字与引用关系做的初筛，不是处置结论。** 每一条是删是接，仍要逐条看。

逐条看过的结果在 ``config/unwired_placement.json``：安卓部分以外的每个函数该放在哪里（接到哪个调用点、
挂到哪个端点、被什么取代所以该删、只是测试钩子、框架回调、随对象走、还是产品决定）。这里把它渲染进文档，
``--check`` 核对它与当前清单一一对得上。

用法
----
  python scripts/unwired_inventory.py                 # 打印摘要
  python scripts/unwired_inventory.py --write         # 刷新 docs/UNWIRED_CODE_INVENTORY.md 的生成段
  python scripts/unwired_inventory.py --json          # 机器可读
  python scripts/unwired_inventory.py --check         # 放置表是否覆盖全部非安卓条目、有没有过期条目
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_reachability  # noqa: E402
import check_wiring  # noqa: E402

DOC_PATH = REPO_ROOT / "docs" / "UNWIRED_CODE_INVENTORY.md"
BEGIN = "<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->"
END = "<!-- END GENERATED -->"
PLACEMENT_PATH = REPO_ROOT / "config" / "unwired_placement.json"

# 去处类别（顺序即文档里的顺序）。放置表里只允许这几种。
PLACEMENTS = (
    ("wire", "接上", "该有人调它：写明调用点（文件、第几行附近、在做什么的时候）"),
    ("surface", "挂出来", "该有人读它：写明挂到哪个端点 / 面板 / 诊断输出"),
    ("delete", "删掉", "已被别的实现取代或根本没有用途：写明被什么取代"),
    ("object", "随对象走", "对象上的判定 / 查询 / 扩展点：对象被用到那一处时自然会用，单独接没有意义"),
    ("testhook", "测试钩子", "只为测试或断言存在（复位、注入、不变量断言），不该进生产路径"),
    ("framework", "框架回调", "由第三方框架按名字回调（zeroconf、asyncio），清单误报"),
    ("product", "产品决定", "接不接是功能取舍，不是技术问题：等所有者定"),
)
PLACEMENT_KEYS = tuple(k for k, _l, _d in PLACEMENTS)
# 所有者安排暂缓的部分，不要求有去处。
DEFERRED_THEMES = ("android",)

# 顺序即优先级：先命中的类别生效。
ROLES = (
    ("测试复位钩子", r"^(reset|clear)(_|$)|_for_tests?$|_for_testing$"),
    ("序列化/转换", r"^(to|from|as)_\w+$|_to_(dict|json|payload|record|node_update|platform|contract)$"),
    ("事件回调", r"^on_\w+$|_received$"),
    (
        "判定谓词",
        r"^(is|has|can|should|was|needs|requires|allows|affects|blocks|visits)_\w+$|^retriable$|"
        r"_(enabled|reachable|registered)$|^spoke_anything$",
    ),
    (
        "只读查询",
        r"^(get|list|find|lookup|query|read|retrieve|iter|all|count|snapshot|summary|describe|inspect|current|latest|"
        r"recent|last|"
        r"next|top|nodes|devices|entries|edges|sources|gaps)_|_(snapshot|summary|count|stats|label|description|terms|"
        r"catalog|entries|sources|subsystems|ms|minute|model|artifacts|of|name|handle|timeline_replay|signals|"
        r"assignment|workers|counters)$|^counters$",
    ),
    (
        "计算/构造",
        r"^(build|make|create|compose|derive|compute|classify|evaluate|assess|resolve|select|choose|rank|score|plan|"
        r"map|decide|govern|normalize|decompose|interpret|project|infer|explain|order|filter|suggest|determine|"
        r"estimate|fallback|trust|guard|block|require|think|comprehend|aggregate|handoff|redact|render|print|"
        r"extract|equivalent|generate|device|result|envelope|chat|finalise|finalize)(_|$)",
    ),
    (
        "动作/变更",
        r"^(record|register|unregister|deregister|set|update|apply|mark|attach|detach|bind|ingest|absorb|emit|"
        r"publish|notify|dispatch|execute|run|start|stop|submit|enqueue|dequeue|advance|transition|close|open|"
        r"promote|revoke|grant|enforce|validate|verify|check|assert|ensure|sync|flush|persist|save|load|restore|"
        r"replay|migrate|merge|install|remove|delete|add|push|pop|handle|process|invoke|trigger|cancel|retry|"
        r"coordinate|route|audit|assimilate|seed|download|receive|send|export|import|reload|hot|enable|disable|"
        r"connect|discover|cache|inject|couple|decouple|begin|complete|suppress|recover|resume|reconnect|relay|"
        r"write|expire|evict|sweep|force|release|subscribe|unsubscribe|track|probe|proxy|allocate|autoscale|"
        r"activate|trip|drop|increment|warn|forget|udm|store|unload|parallel|switch|initialize|reinitialize|"
        r"index|generalize|mine|take|wait|associate|auto|negotiate|detect|simulate|refresh|guarded|safe|test|"
        r"child|error)(_|$)",
    ),
)


# 按**用途**分组(路径规则,先命中先生效)。与上面按名字的角色是两根轴:角色说「这个函数是查询还是动作」,
# 用途说「它属于系统的哪一块」。文档里对每一组的人话解释在生成段之外,由人维护。
THEMES = [
    ("nodes", "节点服务里的方法", [r"^nodes/"]),
    (
        "android",
        "安卓协作的契约、治理与对账层",
        [
            r"android",
            r"^core/attached_runtime_",
            r"^core/ugcp_",
            r"^core/takeover_tracking",
            r"^core/v2_android",
            r"^core/delegated_runtime",
            r"^core/delegated_flow_post",
            r"^core/delegated_flow_entity",
            r"^core/conversation_continuity_truth",
            r"^core/offline_replay_ordering",
            r"^core/inflight_task_continuity",
            r"^core/pr3_session",
            r"^core/pr4_operator",
            r"^core/cross_repo_protocol",
            r"^core/full_system_baseline",
            r"wearos",
            r"^core/mesh/android_",
        ],
    ),
    (
        "persist",
        "持久化、重启恢复与断点续跑",
        [
            r"^core/delegated_flow_(persistence|recovery|decision)",
            r"^core/flow_continuity",
            r"^core/continuation_rebind",
            r"^core/hybrid_orchestration_continuity",
            r"^core/replay_",
            r"^core/task_envelope_lifecycle",
            r"^core/mesh/mesh_session_lifecycle",
            r"^core/recovery_truth_surface",
            r"^core/task_graph_runtime",
            r"^core/task_lifecycle\.py",
        ],
    ),
    (
        "observe",
        "指标、可观测与审计记录",
        [
            r"slo_metrics",
            r"^core/resilience/metrics",
            r"observability",
            r"telemetry",
            r"^core/decision_timeline",
            r"^core/audit_event_semantics",
            r"^core/control_plane/audit_ledger",
            r"orchestration_review_surface",
            r"routing_explanation",
            r"^core/device_activation_registry",
            r"^core/task_cost_ledger",
            r"^core/protocol_drift_registry",
            r"^core/log_redaction",
        ],
    ),
    (
        "govern",
        "架构治理：权威声明、边界断言与自检",
        [
            r"truth",
            r"authority",
            r"^core/compat_",
            r"^core/outward_",
            r"^core/mainline_convergence",
            r"^core/runtime_invariant",
            r"boundary",
            r"^core/release_governance",
            r"^core/governance_validation",
            r"^core/capability_tier",
            r"governance",
            r"^core/node_lifecycle_governor",
            r"^core/production_baseline",
            r"harness",
            r"^core/runtime_closure_audit",
            r"^core/runtime_readiness",
            r"^core/audit_layer/",
            r"^core/repo_layout_registry",
            r"^core/ui_surface_authority",
            r"^core/multi_subject_closure",
            r"^core/unified_action_lifecycle",
            r"^core/subject_facing_foreground",
            r"^core/system_orchestrator",
            r"^core/unified_execution_governance",
            r"^core/unified_dispatch_readiness",
            r"^core/multi_device_control_integrity",
            r"^core/health_evidence_policy",
            r"^core/acl\.py",
        ],
    ),
    (
        "mesh",
        "多设备编组、协同网络与拓扑",
        [
            r"^core/mesh",
            r"^core/device_formation/",
            r"^core/presence/",
            r"^core/multi_device_",
            r"^core/constellation",
            r"swarm",
            r"^core/orchestration/global_arbiter",
            r"^core/cross_device_",
            r"^core/network_",
            r"^core/capability_network",
            r"^core/proxy_relay",
            r"^core/device_worker_convergence",
        ],
    ),
    (
        "device",
        "设备与节点：注册、发现、连接、通信、传输",
        [
            r"^core/device_",
            r"^core/node_",
            r"^core/nodes/",
            r"^core/lan_discovery",
            r"^core/connection_manager",
            r"^core/tailscale",
            r"^core/adapters/",
            r"^core/aip_transport",
            r"^core/peer_trust",
            r"^core/target_device",
            r"^core/nats_bus",
            r"^galaxy_gateway/",
        ],
    ),
    (
        "route",
        "能力、模型与执行路由",
        [
            r"^core/capabilit",
            r"^core/unified/capability",
            r"router",
            r"routing",
            r"^core/model_",
            r"^core/huggingface",
            r"^core/hf_endpoint",
            r"^core/local_brain",
            r"^core/compute_scheduler",
            r"^core/concurrency_manager",
            r"^core/native_modal",
            r"^core/modality_bridge",
            r"^core/degraded_operation",
            r"^core/hybrid_execution_policy",
            r"^core/remote_execution",
            r"^core/gateway_capability",
            r"^core/runtime/",
            r"^core/command_router",
            r"^core/execution_spine",
            r"^core/fusion_entry",
            r"^core/canonical_task_dispatch",
            r"^core/unified/llm_router",
            r"^core/execution/",
        ],
    ),
    (
        "agent",
        "智能体、认知与记忆",
        [
            r"^core/agent",
            r"^core/ai_intent",
            r"^core/cognitive/",
            r"^core/continuum/",
            r"^core/feedback_loop",
            r"^core/user_preference",
            r"^core/task_memory",
            r"^core/openclawd",
            r"^core/orchestration/",
            r"^core/grounded_planner",
            r"^core/react_progress",
            r"^core/dag_evolver",
            r"^core/focus_stack",
            r"^core/persona/",
            r"^core/vector_backend",
            r"^core/vision_pipeline",
            r"^core/generative_ui",
            r"^core/digital_twin",
            r"^core/microsoft_ufo",
            r"^core/galaxy_main_loop",
            r"^core/safe_executor",
            r"^core/e2e_orchestrator",
            r"^core/interaction/",
            r"^core/session_",
            r"^core/canonical_session_axis",
            r"^core/canonical_ownership",
        ],
    ),
    (
        "presence",
        "语音、桌面在场与感知",
        [
            r"speech",
            r"^core/tts/",
            r"^core/voice",
            r"^core/duplex",
            r"^core/output/",
            r"^core/desktop_",
            r"^core/perception/",
            r"^core/multimodal/",
            r"^core/interruptibility",
            r"^core/phase_contract",
            r"^core/state_event_bus",
            r"^core/fast_loop",
        ],
    ),
    ("platform", "配置、启动、安全、扩展与通用基础件", [r"^core/", r"^launcher/"]),
]


def theme_of(path: str) -> Tuple[str, str]:
    for key, label, pats in THEMES:
        if any(re.search(p, path) for p in pats):
            return key, label
    return "other", "其他"


def role_of(name: str) -> str:
    for label, pattern in ROLES:
        if re.search(pattern, name):
            return label
    return "其他"


def area_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "nodes" and len(parts) > 2:
        return "nodes/" + parts[1] + "/"
    if parts[0] != "core":
        return parts[0] + "/"
    if len(parts) > 2:
        return "core/" + parts[1] + "/"
    stem = parts[1]
    for prefix in (
        "android_",
        "canonical_",
        "attached_runtime_",
        "delegated_",
        "capability_",
        "device_",
        "node_",
        "task_",
        "desktop_",
        "cross_",
        "truth_",
        "runtime_",
        "session_",
        "orchestration",
        "operator_",
        "execution_",
        "ugcp_",
        "v2_",
        "hybrid_",
        "continuation_",
        "flow_",
    ):
        if stem.startswith(prefix):
            return f"core/{prefix}*"
    return "core/（其余单文件）"


def _first_line(doc: str) -> str:
    for ln in (doc or "").strip().splitlines():
        ln = ln.strip()
        if ln and not set(ln) <= set("=-~#*"):
            return ln[:120]
    return ""


def _kind_index(path: str, cache: Dict[str, Dict[int, Tuple[str, str]]]) -> Dict[int, Tuple[str, str]]:
    """行号 → (所属类名或空串, 函数自己说明的第一行)。"""
    if path not in cache:
        idx: Dict[int, Tuple[str, str]] = {}
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                idx.setdefault(node.lineno, ("", _first_line(ast.get_docstring(node) or "")))
            if isinstance(node, ast.ClassDef):
                for b in node.body:
                    if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        idx[b.lineno] = (node.name, _first_line(ast.get_docstring(b) or ""))
        cache[path] = idx
    return cache[path]


def load_placement() -> Dict[str, Dict[str, List[str]]]:
    if not PLACEMENT_PATH.exists():
        return {}
    return json.loads(PLACEMENT_PATH.read_text(encoding="utf-8")).get("placement", {})


def _placement_key(row: dict) -> str:
    return f"{row['owner']}.{row['name']}" if row["owner"] else row["name"]


def resolve_placement(row: dict, table: Dict[str, Dict[str, List[str]]]):
    """(类别, 放在哪里) 或 None。先按「类名.方法名」，再按裸名，最后按该文件的「*」。"""
    per_file = table.get(row["path"]) or {}
    for key in (_placement_key(row), row["name"], "*"):
        if key in per_file:
            val = per_file[key]
            if isinstance(val, list) and len(val) == 2:
                return val[0], val[1]
            return "", ""  # 格式不对：check_placement 会把它列进 bad
    return None


def check_placement(rows: List[dict], table: Dict[str, Dict[str, List[str]]]) -> Dict[str, List[str]]:
    """放置表与当前清单对账：缺去处的、类别不认识的、已经不在清单里的（过期）。"""
    missing, bad, stale = [], [], []
    used: Dict[str, set] = defaultdict(set)
    for r in rows:
        if r["theme"] in DEFERRED_THEMES:
            continue
        got = resolve_placement(r, table)
        if got is None:
            missing.append(f"{r['path']}::{_placement_key(r)}")
            continue
        per_file = table[r["path"]]
        for key in (_placement_key(r), r["name"], "*"):
            if key in per_file:
                used[r["path"]].add(key)
                break
    for path, per_file in table.items():
        for key, val in per_file.items():
            if not (isinstance(val, list) and len(val) == 2 and val[0] in PLACEMENT_KEYS and str(val[1]).strip()):
                bad.append(f"{path}::{key}")
            if key not in used.get(path, set()):
                stale.append(f"{path}::{key}")
    return {"missing": missing, "bad": bad, "stale": stale}


def _test_referenced(names: List[str]) -> set:
    found: set = set()
    wanted = set(names)
    word = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for f in (REPO_ROOT / "tests").rglob("*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found.update(wanted.intersection(word.findall(text)))
    return found


def collect(reachability: bool = True) -> Dict[str, object]:
    """``reachability=False`` 跳过可达性分析（它占了大半耗时）；只核对去处表时用。"""
    definitions, def_count = check_wiring.collect_definitions(check_wiring._iter_definition_files())
    referenced = check_wiring.collect_references(check_wiring._iter_reference_files())
    unwired = check_wiring.find_unwired(definitions, referenced, def_count)
    unreachable = check_reachability.compute_unreachable() if reachability else []
    unreachable_paths = {m.replace(".", "/") + ".py" for m in unreachable}

    tested = _test_referenced([n for n, _ in unwired])
    placement = load_placement()
    cache: Dict[str, Dict[int, Tuple[str, str]]] = {}
    rows = []
    for name, where in unwired:
        path, line = where.rsplit(":", 1)
        owner, doc = _kind_index(path, cache).get(int(line), ("", ""))
        theme, theme_label = theme_of(path)
        rows.append(
            {
                "name": name,
                "at": where,
                "path": path,
                "kind": "method" if owner else "function",
                "owner": owner,
                "tested": name in tested,
                "role": role_of(name),
                "area": area_of(path),
                "theme": theme,
                "theme_label": theme_label,
                "doc": doc,
                "module_unreachable": path in unreachable_paths,
            }
        )
        got = resolve_placement(rows[-1], placement)
        rows[-1]["placement"], rows[-1]["placement_where"] = got if got else ("", "")
    modules = []
    for mod in unreachable:
        p = REPO_ROOT / (mod.replace(".", "/") + ".py")
        modules.append({"module": mod, "lines": len(p.read_text(encoding="utf-8").splitlines())})
    return {"rows": rows, "unreachable_modules": modules}


def render(data: Dict[str, object]) -> str:
    rows: List[dict] = data["rows"]  # type: ignore[assignment]
    mods: List[dict] = data["unreachable_modules"]  # type: ignore[assignment]
    out: List[str] = []
    n = len(rows)
    tested = sum(r["tested"] for r in rows)
    methods = sum(r["kind"] == "method" for r in rows)
    out.append(f"未接线公开能力 **{n}** 条，分布在 **{len({r['path'] for r in rows})}** 个文件。")
    out.append("")
    out.append("| 维度 | 数 |")
    out.append("|---|---|")
    out.append(f"| 类方法 / 模块函数 | {methods} / {n - methods} |")
    out.append(f"| 只有测试在引用（写了、测了、没接） | {tested} |")
    out.append(f"| 全仓连测试都没引用 | {n - tested} |")
    out.append(f"| 所在模块本身从入口不可达 | {sum(r['module_unreachable'] for r in rows)} |")
    out.append("")
    out.append("### 按名字表明的角色")
    out.append("")
    out.append("| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |")
    out.append("|---|---|---|---|")
    by_role: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)
    order = [label for label, _ in ROLES] + ["其他"]
    for label in order:
        lst = by_role.get(label, [])
        if lst:
            t = sum(x["tested"] for x in lst)
            out.append(f"| {label} | {len(lst)} | {t} | {len(lst) - t} |")
    out.append("")
    out.append("### 按用途")
    out.append("")
    out.append("| 用途 | 条数 | 其中只有测试引用 | 其中连测试都没有 | 文件数 |")
    out.append("|---|---|---|---|---|")
    by_theme: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_theme[r["theme"]].append(r)
    for key, label, _pats in THEMES:
        lst = by_theme.get(key, [])
        if lst:
            t = sum(x["tested"] for x in lst)
            out.append(f"| {label} | {len(lst)} | {t} | {len(lst) - t} | {len({x['path'] for x in lst})} |")
    out.append("")
    out.append("### 每个函数放在哪里（安卓部分按所有者安排暂缓，不在其列）")
    out.append("")
    out.append("逐条核对的结果在 `config/unwired_placement.json`。这是**去处**，不是已执行的处置：删与接都等所有者定。")
    out.append("")
    out.append("| 去处 | 条数 | 意思 |")
    out.append("|---|---|---|")
    placed = [r for r in rows if r["theme"] not in DEFERRED_THEMES]
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for r in placed:
        by_cat[r["placement"] or "（未定）"].append(r)
    for key, label, meaning in PLACEMENTS:
        out.append(f"| {label}（`{key}`） | {len(by_cat.get(key, []))} | {meaning} |")
    if by_cat.get("（未定）"):
        out.append(f"| （未定） | {len(by_cat['（未定）'])} | 放置表里还没有这一条 |")
    out.append(f"| 合计 | {len(placed)} | |")
    out.append("")
    out.append("按用途 × 去处：")
    out.append("")
    out.append("| 用途 | " + " | ".join(label for _k, label, _m in PLACEMENTS) + " | 合计 |")
    out.append("|---|" + "---:|" * (len(PLACEMENTS) + 1))
    for theme_key, theme_label, _pats in THEMES:
        lst = [r for r in placed if r["theme"] == theme_key]
        if not lst:
            continue
        cells = [str(sum(r["placement"] == k for r in lst)) for k, _l, _m in PLACEMENTS]
        out.append(f"| {theme_label} | " + " | ".join(cells) + f" | {len(lst)} |")
    out.append("")
    for key, label, _meaning in PLACEMENTS:
        lst = by_cat.get(key, [])
        if not lst:
            continue
        out.append(f"<details><summary>{label}（{key}）— {len(lst)} 条</summary>")
        out.append("")
        grouped: Dict[str, List[dict]] = defaultdict(list)
        for r in lst:
            grouped[r["path"]].append(r)
        for path in sorted(grouped):
            items = sorted(grouped[path], key=lambda x: int(x["at"].rsplit(":", 1)[1]))
            wheres = {x["placement_where"] for x in items}
            if len(items) > 1 and len(wheres) == 1:
                names = "、".join(f"`{_placement_key(x)}`" for x in items)
                out.append(f"- `{path}` — {names}：{wheres.pop()}")
                continue
            out.append(f"- `{path}`")
            for x in items:
                out.append(f"  - `{_placement_key(x)}`：{x['placement_where']}")
        out.append("")
        out.append("</details>")
        out.append("")
    out.append("### 按子系统")
    out.append("")
    out.append("| 子系统 | 条数 | 文件数 |")
    out.append("|---|---|---|")
    by_area: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_area[r["area"]].append(r)
    for area, lst in sorted(by_area.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f"| `{area}` | {len(lst)} | {len({x['path'] for x in lst})} |")
    out.append("")
    out.append("### 从真实入口不可达的模块")
    out.append("")
    out.append("| 模块 | 行数 |")
    out.append("|---|---|")
    for m in mods:
        out.append(f"| `{m['module']}` | {m['lines']} |")
    out.append("")
    out.append("### 逐文件清单")
    out.append("")
    out.append("按用途分组，每个函数后面是它**自己的说明**（docstring 第一行，原文照录；没写说明的标「无说明」）。")
    out.append("标记：`T` 只有测试在引用；`—` 连测试都没有。")
    out.append("")
    by_file: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_file[r["path"]].append(r)
    for key, label, _pats in THEMES:
        lst = by_theme.get(key, [])
        if not lst:
            continue
        files = sorted({x["path"] for x in lst})
        out.append(f"<details><summary>{label} — {len(lst)} 条</summary>")
        out.append("")
        for path in files:
            items = sorted(by_file[path], key=lambda x: int(x["at"].rsplit(":", 1)[1]))
            out.append(f"- `{path}`")
            for x in items:
                name = f"{x['owner']}.{x['name']}" if x["owner"] else x["name"]
                doc = (x["doc"] or "无说明").replace("|", "\\|")
                out.append(f"  - `{name}` {'T' if x['tested'] else '—'} — {doc}")
        out.append("")
        out.append("</details>")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help=f"刷新 {DOC_PATH.relative_to(REPO_ROOT)} 的生成段")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--check", action="store_true", help=f"核对 {PLACEMENT_PATH.relative_to(REPO_ROOT)} 与当前清单")
    args = ap.parse_args()
    data = collect(reachability=not args.check)
    if args.check:
        report = check_placement(data["rows"], load_placement())  # type: ignore[arg-type]
        for kind, label in (("missing", "没有去处"), ("bad", "格式或类别不对"), ("stale", "已不在清单里")):
            for item in report[kind]:
                print(f"{label}: {item}")
        return 1 if any(report.values()) else 0
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    body = render(data)
    if args.write:
        doc = DOC_PATH.read_text(encoding="utf-8")
        if BEGIN not in doc or END not in doc:
            print(f"{DOC_PATH} 里找不到生成段标记", file=sys.stderr)
            return 1
        head, rest = doc.split(BEGIN, 1)
        _old, tail = rest.split(END, 1)
        DOC_PATH.write_text(head + BEGIN + "\n\n" + body + "\n" + END + tail, encoding="utf-8")
        print(f"已刷新 {DOC_PATH.relative_to(REPO_ROOT)}")
        return 0
    rows = data["rows"]  # type: ignore[index]
    print(f"未接线 {len(rows)} 条；角色分布：", Counter(r["role"] for r in rows).most_common())  # type: ignore[union-attr]
    print("不可达模块：", [m["module"] for m in data["unreachable_modules"]])  # type: ignore[index]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
