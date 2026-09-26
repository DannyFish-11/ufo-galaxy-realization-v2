"""core/genome.py — Galaxy Genome：把散落的 harness 收成一个可版本化目录（R5）。

要解决什么
==========
OpenClawd 的系统提示词写死在 ``core/openclawd.py`` 里，Agent Factory 的六个模板提示词写死在
``core/agent_factory.py`` 里。改一句话就要改代码、过全量 CI、发版本；想灰度、想 A/B、想退回
上周那一版，都无从谈起。元层的 Harness-RSI 算子要写的正是这一格 —— 它不能去改 ``.py``。

Genome 是一份**完整、自包含、带血缘**的 harness 配置目录（形状取自 CosmosMind-ai/rsi-harness
的 ``config/genomes/*/genome.json``，源码实测）::

    config/genomes/<name>/genome.json              入口：genome_id · parent_id · version · base · components
    config/genomes/<name>/components/<id>.json     组件内容

阶段一两格：

* ``instructions`` —— 系统提示词与 Agent 模板提示词。Harness-RSI 的可写面。
* ``model``        —— 当前模型供给的来源快照，**只读**（元层能改「谁来想」要等 §04F 的判据全绿）。

不破坏的四条（设计规格 §07）
============================
* **G1 继承式合并** —— 字段缺省＝继承 base；``null``＝删除该键、交还系统默认；有值＝覆盖；
  对象递归合并，数组整体替换。只声明一格的 Genome 不会波及其余。
* **G2 空值不等于清除** —— ``"system_prompt": ""`` 是一个值，会把提示词换成空串。关键字段的
  空字符串直接判为非法；要清除必须写 ``null``。
* **G3 人工压制优先** —— 显式参数 > 环境变量 ``GALAXY_SYSTEM_PROMPT`` > Genome > 内置默认。
  元层改了什么，人不改 Genome 也能就地压住。
* **G9 逐位一致** —— 默认 Genome 产出的提示词与原先硬编码的字符串逐字节相同（测试独立复刻旧值比对）。

失败永远不拖垮请求：Genome 缺失、损坏、不合法 —— 一律回落到内置默认并告警。

本模块在热路径上（OpenClawd 每轮对话读一次），因此**不得** import ``core.meta``（守卫 G10），
读盘按 mtime 缓存。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.Genome")

REPO_ROOT = Path(__file__).resolve().parent.parent
GENOMES_ROOT = REPO_ROOT / "config" / "genomes"
GENOME_SCHEMA_VERSION = "1"
DEFAULT_GENOME = "default"

#: 阶段一只读的组件：Harness-RSI 不得写（:mod:`core.meta.kernel` 在可写面检查里据此拒绝）。
READ_ONLY_COMPONENTS: Tuple[str, ...] = ("model",)

#: 组件契约：必填字段与「不得为空字符串」的字段（G2）。点号路径。
COMPONENT_CONTRACTS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "instructions": {"required": ("system_prompt",), "non_empty": ("system_prompt", "agent_templates.*")},
    "model": {"required": ("routing_policy",), "non_empty": ("routing_policy",)},
}

_MAX_BASE_DEPTH = 8


class GenomeError(ValueError):
    """Genome 不合法：清单缺字段、组件违约、base 成环……"""


# ---------------------------------------------------------------------------
# G1：继承式合并
# ---------------------------------------------------------------------------

_ABSENT = object()


def merge_overrides(base: Any, override: Any) -> Any:
    """``override`` 叠到 ``base`` 上：缺省继承、``None`` 删除、对象递归、其余（含数组）整体替换。

    两个参数都不会被修改。顶层 ``override`` 为 ``None`` 表示整体交还系统默认，返回 ``None``。
    """
    if override is None:
        return None
    if isinstance(override, dict):
        merged = copy.deepcopy(base) if isinstance(base, dict) else {}
        for key, value in override.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = merge_overrides(merged.get(key, _ABSENT), value)
        return merged
    return copy.deepcopy(override)


# ---------------------------------------------------------------------------
# 契约（G2）
# ---------------------------------------------------------------------------


def _lookup(data: Dict[str, Any], dotted: str) -> List[Tuple[str, Any]]:
    """点号路径取值；``*`` 展开一层对象的全部键。"""
    items: List[Tuple[str, Any]] = [("", data)]
    for part in dotted.split("."):
        nxt: List[Tuple[str, Any]] = []
        for prefix, node in items:
            if not isinstance(node, dict):
                continue
            keys = list(node) if part == "*" else [part] if part in node else []
            nxt += [(f"{prefix}.{k}" if prefix else k, node[k]) for k in keys]
        items = nxt
    return items


def contract_violations(component_id: str, content: Any) -> List[str]:
    contract = COMPONENT_CONTRACTS.get(component_id)
    if contract is None:
        return []
    if not isinstance(content, dict):
        return [f"{component_id}：组件内容必须是 JSON 对象"]
    problems = [f"{component_id}.{f}：必填字段缺失" for f in contract["required"] if not _lookup(content, f)]
    for dotted in contract["non_empty"]:
        for path, value in _lookup(content, dotted):
            if not isinstance(value, str) or not value.strip():
                problems.append(
                    f"{component_id}.{path}：不得为空字符串 —— 空串是一个值，会把原内容替换成空；要清除请写 null（G2）"
                )
    return problems


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Genome:
    name: str
    genome_id: str
    version: int
    parent_id: Optional[str]
    lineage: Tuple[str, ...]  # 自己 + base 链上的 genome_id，由近及远
    components: Dict[str, Any] = field(default_factory=dict)
    content_id: str = ""  # 合并后组件的内容寻址摘要：同内容同 id，改内容必换 id

    def component(self, component_id: str) -> Dict[str, Any]:
        value = self.components.get(component_id)
        return value if isinstance(value, dict) else {}


def genome_dir(name: str, root: Optional[Path] = None) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise GenomeError(f"Genome 名字不合法：{name!r}")
    return (root or GENOMES_ROOT) / name


def read_manifest(name: str, root: Optional[Path] = None) -> Dict[str, Any]:
    path = genome_dir(name, root) / "genome.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GenomeError(f"Genome {name!r} 不存在：{path}") from exc
    except ValueError as exc:
        raise GenomeError(f"Genome {name!r} 的清单不是合法 JSON：{exc}") from exc
    for key in ("genome_schema_version", "genome_id", "version", "components"):
        if key not in manifest:
            raise GenomeError(f"Genome {name!r} 的清单缺字段 {key!r}")
    if str(manifest["genome_schema_version"]) != GENOME_SCHEMA_VERSION:
        raise GenomeError(f"Genome {name!r} 的 schema 版本 {manifest['genome_schema_version']!r} 不认得")
    if not isinstance(manifest["version"], int) or manifest["version"] < 1:
        raise GenomeError(f"Genome {name!r} 的 version 必须是正整数")
    return manifest


def _own_components(name: str, manifest: Dict[str, Any], root: Optional[Path]) -> Dict[str, Any]:
    base_dir = genome_dir(name, root)
    components: Dict[str, Any] = {}
    for entry in manifest["components"]:
        cid, source = entry.get("id"), entry.get("source")
        if not cid or not source:
            raise GenomeError(f"Genome {name!r} 的组件条目缺 id 或 source：{entry!r}")
        path = (base_dir / source).resolve()
        if base_dir.resolve() not in path.parents:
            raise GenomeError(f"Genome {name!r} 的组件 {cid!r} 指向目录之外：{source!r}")
        try:
            components[cid] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GenomeError(f"Genome {name!r} 的组件 {cid!r} 读不出来：{exc}") from exc
    return components


def _content_id(components: Dict[str, Any]) -> str:
    body = json.dumps(components, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "genome:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def load_genome(name: str = DEFAULT_GENOME, *, root: Optional[Path] = None) -> Genome:
    """读一个 Genome，沿 ``base`` 链做继承式合并，并逐组件核契约。不合法抛 :class:`GenomeError`。"""
    chain: List[Tuple[str, Dict[str, Any]]] = []
    current: Optional[str] = name
    while current:
        if any(current == seen for seen, _ in chain):
            raise GenomeError(f"Genome 的 base 链成环：{[n for n, _ in chain] + [current]}")
        if len(chain) >= _MAX_BASE_DEPTH:
            raise GenomeError(f"Genome 的 base 链过深（>{_MAX_BASE_DEPTH}）")
        manifest = read_manifest(current, root)
        chain.append((current, manifest))
        current = manifest.get("base")

    merged: Dict[str, Any] = {}
    for layer_name, manifest in reversed(chain):  # 由远及近，近的覆盖远的
        for cid, content in _own_components(layer_name, manifest, root).items():
            value = merge_overrides(merged.get(cid, _ABSENT), content)
            if value is None:
                merged.pop(cid, None)
            else:
                merged[cid] = value

    problems = [p for cid, content in merged.items() for p in contract_violations(cid, content)]
    if problems:
        raise GenomeError(f"Genome {name!r} 违反组件契约：" + "；".join(problems))
    top = chain[0][1]
    return Genome(
        name=name,
        genome_id=str(top["genome_id"]),
        version=int(top["version"]),
        parent_id=top.get("parent_id"),
        lineage=tuple(str(m["genome_id"]) for _, m in chain),
        components=merged,
        content_id=_content_id(merged),
    )


# ---------------------------------------------------------------------------
# 运行时读取：mtime 缓存 + 失败回落
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str], Tuple[Tuple[Tuple[str, float], ...], Optional[Genome]]] = {}


#: 指针文件：Harness-RSI 生效一版进化 Genome 时写它（它在算子可写面内，回滚即恢复）。
ACTIVE_POINTER = "active.json"


def active_genome_name(root: Optional[Path] = None) -> str:
    """当前生效的 Genome 名。``GALAXY_GENOME`` > ``config/genomes/active.json`` > ``default``（G3：人压过元层）。"""
    explicit = (os.environ.get("GALAXY_GENOME", "") or "").strip()
    if explicit:
        return explicit
    pointer = (root or GENOMES_ROOT) / ACTIVE_POINTER
    if pointer.is_file():
        try:
            name = str(json.loads(pointer.read_text(encoding="utf-8")).get("genome") or "").strip()
            if name:
                return name
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning("Genome 指针文件不可读，按默认 Genome 处理（%s）: %s", pointer, exc)
    return DEFAULT_GENOME


def _stamp(root: Path) -> Tuple[Tuple[str, float], ...]:
    try:
        return tuple(sorted((str(p), p.stat().st_mtime) for p in root.rglob("*.json")))
    except OSError:
        return ()


def active_genome(*, root: Optional[Path] = None) -> Optional[Genome]:
    """当前生效的 Genome；读不出或不合法时返回 ``None``（调用方回落到内置默认）。"""
    base = root or GENOMES_ROOT
    name = active_genome_name(base)
    key = (str(base), name)
    stamp = _stamp(base)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    try:
        genome: Optional[Genome] = load_genome(name, root=base)
    except GenomeError as exc:
        logger.warning("Genome %r 不可用，回落到内置默认: %s", name, exc)
        genome = None
    with _cache_lock:
        _cache[key] = (stamp, genome)
    return genome


#: 系统自己的默认 —— 继承链的尽头。与引入 Genome 之前 core/openclawd.py 里硬编码的那段逐字节相同。
BUILTIN_SYSTEM_PROMPT = (
    "你是 Galaxy 智能助手 (OpenClawd)，一个桌面级超级 AI 智能体。\n"
    "你可以帮助用户进行对话、任务管理、设备控制、代码执行等操作。\n"
    "当你需要执行操作时，请使用提供的工具。\n"
    "如果没有合适的工具，直接用文字回答。\n"
    "表达原则：直接、简洁，不复述问题、不加客套铺垫；"
    "要调用工具就直接调用，不要先输出长段解释。"
)


def system_prompt(builtin: str = BUILTIN_SYSTEM_PROMPT, *, explicit: Optional[str] = None) -> str:
    """OpenClawd 的系统提示词。优先级：显式参数 > ``GALAXY_SYSTEM_PROMPT`` > Genome > 内置默认（G3）。"""
    if explicit:
        return explicit
    env_value = os.environ.get("GALAXY_SYSTEM_PROMPT", "")
    if env_value.strip():
        return env_value
    genome = active_genome()
    value = genome.component("instructions").get("system_prompt") if genome else None
    return value if isinstance(value, str) and value.strip() else builtin


def agent_template_prompt(template_name: str, builtin: str) -> str:
    """Agent Factory 模板的系统提示词：Genome 有就用 Genome，否则内置。显式覆盖由调用方在其后施加。"""
    genome = active_genome()
    templates = genome.component("instructions").get("agent_templates") if genome else None
    value = templates.get(template_name) if isinstance(templates, dict) else None
    return value if isinstance(value, str) and value.strip() else builtin


__all__ = [
    "ACTIVE_POINTER",
    "BUILTIN_SYSTEM_PROMPT",
    "DEFAULT_GENOME",
    "GENOMES_ROOT",
    "GENOME_SCHEMA_VERSION",
    "READ_ONLY_COMPONENTS",
    "Genome",
    "GenomeError",
    "active_genome",
    "active_genome_name",
    "agent_template_prompt",
    "contract_violations",
    "genome_dir",
    "load_genome",
    "merge_overrides",
    "read_manifest",
    "system_prompt",
]
