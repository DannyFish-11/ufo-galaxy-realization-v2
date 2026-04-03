"""
core.openclawd — Subject Core: Cognition, Execution Branching, and Manifestation
==================================================================================

**Unified-Subject Architecture**
---------------------------------
``OpenClawd`` is the **subject core** — the cognition and execution nucleus of
the unified subject.  It is NOT a parallel subject alongside
``DesktopPresenceRuntime``.  The two form one coherent entity:

- ``DesktopPresenceRuntime`` — the outer runtime shell (Windows desktop
  clothing).  Owns the canonical tri-state lifecycle, native multimodal
  ingress, and the ``runtime_session_id``.
- ``OpenClawd`` (this module) — the inner cognition/execution core.  Operates
  entirely **inside the liminal phase** of the shell's tri-state lifecycle.

.. code-block:: text

    DesktopPresenceRuntime (shell)
        └─ invokes OpenClawd.process() during LIMINAL phase
              └─ OpenClawd (subject core)
                    Stage 1: Ingest
                      ├─ PerceptionFrame (continuous host ingress from shell)
                      └─ multimodal_context (request-bound fusion via MultimodalBus)
                    Stage 2: Continuum / Liminal Cognition
                      └─ ContinuumOrchestrator — intent → state_continuum
                    Stage 3: Execution Branch (_determine_execution_path)
                      ├─ local       → Windows / System API manifestation
                      ├─ cross_device → gateway / remote expansion
                      ├─ hybrid      → both loops simultaneously
                      └─ none        → no manifestation (respond only)
                    Stage 4: Manifest
                      └─ DecisionExecutor (local) / CommandRouter (cross-device)

**Two distinct multimodal input paths**
----------------------------------------
1. **Continuous host perception** — ``PerceptionFrame`` objects produced by
   ``MultimodalIngressBus`` (owned by the runtime shell).  These represent
   the ambient sensory context of the Windows environment: audio, video,
   system signals.  Made available to ``process()`` via the shell when
   relevant.
2. **Request-bound multimodal context** — ``multimodal_context`` kwarg on
   :meth:`process`.  A per-request payload bundle (images, audio clips, etc.)
   attached by the caller.  Fused inside this module via
   ``MultimodalBus.ingest`` to produce a ``fusion_summary`` appended to the
   prompt.

**Execution path semantics** (``execution_path`` in response metadata)
------------------------------------------------------------------------
- ``"local"``        — execution confined to this Windows device via System API
                       (``DecisionExecutor``, ``WindowsExecutionArbiter``, etc.)
- ``"cross_device"`` — execution expands to remote devices via the gateway;
                       this is a **liminal domain expansion**, not a parallel
                       system.
- ``"hybrid"``       — both local and cross-device loops run concurrently.
- ``"none"``         — no manifestation; subject responds without acting.

The ``runtime_domain`` field in ``state_continuum`` carries the same
information as an internal continuum posture detail; ``execution_path``
surfaces it in the response so the runtime shell can log it against
``runtime_session_id``.

**State systems summary** (do not conflate)
--------------------------------------------
- Tri-state lifecycle (``silent`` / ``liminal`` / ``manifest``) → owned by
  ``DesktopPresenceRuntime`` shell.
- Continuum posture (``tri_state_phase`` + ``runtime_domain``) → owned by
  ``ContinuumOrchestrator`` inside this module.
- UI shell states (``DORMANT`` / ``ISLAND`` / ``SIDESHEET`` / ``FULLAGENT``)
  → ``system_integration/``; desktop clothing modes; completely separate.

设计原则:
  1. 单例模式 — 全局唯一主体核心
  2. 懒加载 — 所有模块按需导入，避免循环依赖
  3. 容错降级 — 任何模块不可用时自动降级
  4. 统一响应 — 所有方法返回标准 dict 格式，携带 state_continuum /
                execution_path / runtime_domain / runtime_session_id
"""

import asyncio as _asyncio_module
import dataclasses
import enum
import logging
import socket
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger("Galaxy.OpenClawd")

# ============================================================================
# Helper: local-device detection + Parallel-group state machine
# ============================================================================
# PR-7: Extracted to core/orchestration/lifecycle.py. Re-imported here for
# backward compatibility with any module that imports directly from openclawd.
# The noqa suppresses E402 (module-level import not at top of file) — this
# placement is intentional: module-level constants _DEFAULT_SKILL_SCHEMA and
# the built-in tool lists below depend on these names being in scope and the
# import must follow the top-of-module stdlib imports already present above.
from core.orchestration.lifecycle import (  # noqa: E402
    _LOCAL_DEVICE_PREFIXES,
    _LOCAL_HOSTNAME,
    _is_local_device,
    _SubtaskStatus,
    _SubtaskEntry,
    ParallelResult,
    ParallelGroupTracker,
    LIFECYCLE_MANAGER_AUTHORITY,
    LifecycleManager,
)


# 当能力总线和直接加载路径均无法提供 Skill 参数 schema 时使用的默认值
_DEFAULT_SKILL_SCHEMA: Dict = {
    "type": "object",
    "properties": {
        "input": {"type": "string", "description": "输入参数"}
    },
}

# GitHub 插件内置工具定义（供 LLM function calling 使用）
_GITHUB_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "github__install",
            "description": (
                "从 GitHub 仓库安装 MCP 工具或 Skill 插件，安装后可立即在当前会话中调用。"
                "GITHUB_TOKEN 须在环境变量或 Dashboard 中配置，勿在对话中提供 Token。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "GitHub HTTPS 仓库 URL，例如 https://github.com/owner/repo 或 https://github.com/owner/repo/tree/main",
                    },
                    "ref": {
                        "type": "string",
                        "description": "指定分支、Tag 或 Commit SHA（可选，覆盖 URL 中的分支）",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["mcp", "skill"],
                        "description": "插件类型：mcp（MCP 工具服务器）或 skill（Skill 技能）；不填则自动检测",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "设为 true 时只验证 URL 格式，不实际安装",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__uninstall",
            "description": "卸载通过 github__install 安装的 MCP 工具或 Skill 插件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "插件名称（与安装时 manifest 中的 name 字段一致）",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__list",
            "description": "列出当前已安装的所有 GitHub 来源的 MCP 工具和 Skill 插件及其安装信息。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__status",
            "description": "查看 GitHub 插件安装器状态，包括 GITHUB_TOKEN 是否已配置、安装目录、已安装数量等。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__ingest",
            "description": (
                "将 GitHub 仓库内容（README、文档、Manifest 等）摄取到统一知识库（Knowledge Core）。"
                "摄取后，仓库内容可通过知识检索流程获取，来源标注为 github://{owner}/{repo}。"
                "此操作不安装插件，仅建立知识关联。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "GitHub HTTPS 仓库 URL，例如 https://github.com/owner/repo",
                    },
                    "ref": {
                        "type": "string",
                        "description": "指定分支、Tag 或 Commit SHA（可选）",
                    },
                    "include_code": {
                        "type": "boolean",
                        "description": "是否同时摄取仓库根目录的源代码文件（默认 false）",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__context",
            "description": (
                "从 GitHub 仓库提取结构化工程上下文（README、描述、Topics、Manifest 等），"
                "可注入到规划、编码或调试流程。不持久化到知识库，仅返回实时上下文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "GitHub HTTPS 仓库 URL",
                    },
                    "ref": {
                        "type": "string",
                        "description": "指定分支、Tag 或 Commit SHA（可选）",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

# Academic 内置工具定义（供 LLM function calling 使用）
_ACADEMIC_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "academic__search",
            "description": (
                "在学术数据库（arXiv、Semantic Scholar、PubMed、IEEE Xplore）中搜索论文。"
                "默认将搜索结果摄取到统一知识库（Knowledge Core），以便后续回检与推理引用。"
                "返回论文元数据列表，包括标题、作者、摘要、来源、标签和摘取的条目 ID。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或自然语言问题",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "arxiv", "semantic_scholar", "pubmed", "ieee"],
                        "description": "数据源，默认为 all（全部来源）",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "每个数据源最多返回的论文数量（默认 10）",
                    },
                    "ingest": {
                        "type": "boolean",
                        "description": "是否将搜索结果摄取到统一知识库（默认 true）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__ingest",
            "description": (
                "将单篇论文的元数据和摘要摄取到统一知识库（Knowledge Core）。"
                "来源标注为 academic://{source}/{paper_id}，source_type 为 'academic'。"
                "用于把已检索到的论文持久化为可回检的知识片段。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper": {
                        "type": "object",
                        "description": (
                            "论文元数据对象，至少包含 paper_id、title、abstract、source 字段。"
                            "其他可选字段：authors、published_date、url、tags、notes、doi、citation_count。"
                        ),
                    },
                },
                "required": ["paper"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__recall",
            "description": (
                "从统一知识库（Knowledge Core）中回检之前摄取的学术知识片段。"
                "仅返回 source_type='academic' 或 source 以 academic:// 开头的知识条目。"
                "可与 academic__search 配合使用：先搜索并摄取，后续对话中通过此工具回检。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "回检查询（自然语言）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回的知识片段数量（默认 5）",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# Engineering loop built-in tools (mediated self-healing, PR-6)
_ENGINEER_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "engineer__diagnose",
            "description": (
                "向受管工程循环（SelfHealingLoop）提交一条诊断/问题，创建新的 PatchProposal，"
                "进入 DIAGNOSE 阶段。这是所有自愈/代码修复流程的唯一受控入口。"
                "返回 proposal_id，用于后续 engineer__plan / engineer__apply 等步骤。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_summary": {
                        "type": "string",
                        "description": "问题的人类可读描述（例如 'CPU 过载 > 90%，需修复调度逻辑'）",
                    },
                    "source": {
                        "type": "string",
                        "description": "诊断来源（例如 'Node_112'、'user'、'openclawd'）",
                    },
                },
                "required": ["issue_summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__context",
            "description": (
                "将代码/仓库上下文附加到指定的 PatchProposal，并推进到 GATHER_CONTEXT 阶段。"
                "上下文可包含文件代码片段、仓库元数据、相关日志等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "由 engineer__diagnose 返回的 proposal_id",
                    },
                    "context": {
                        "type": "object",
                        "description": "上下文字典（文件代码片段、仓库元数据、日志等）",
                    },
                },
                "required": ["proposal_id", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__plan",
            "description": (
                "为 PatchProposal 附加具体的补丁计划，推进到 PLAN_PATCH 阶段。"
                "必须先完成 engineer__context 步骤。"
                "补丁内容可以是 diff、伪代码描述或修改说明。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "由 engineer__diagnose 返回的 proposal_id",
                    },
                    "patch_content": {
                        "type": "string",
                        "description": "补丁描述或 diff 文本",
                    },
                    "target_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "补丁目标文件路径列表（可选）",
                    },
                },
                "required": ["proposal_id", "patch_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__apply",
            "description": (
                "通过受控执行路径应用已计划的补丁，推进 PatchProposal 到 APPLY 阶段。"
                "安全门控：仅处于 PLAN_PATCH 阶段的提案才允许应用，防止未经规划的直接代码变更。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "由 engineer__diagnose 返回的 proposal_id",
                    },
                },
                "required": ["proposal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__validate",
            "description": (
                "对已应用的补丁运行验证检查，推进 PatchProposal 到 VALIDATE 阶段。"
                "记录验证结果（通过/失败）和验证说明。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "由 engineer__diagnose 返回的 proposal_id",
                    },
                    "passed": {
                        "type": "boolean",
                        "description": "验证是否通过（默认 true）",
                    },
                    "notes": {
                        "type": "string",
                        "description": "验证说明或测试输出",
                    },
                },
                "required": ["proposal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__record",
            "description": (
                "将修复结果记录到统一知识库（Knowledge Core），推进 PatchProposal 到 RECORD_OUTCOME 阶段。"
                "使用 RAGMemory.ingest_knowledge 写入，source_type='engineering'，"
                "与其他知识共享同一 RAG 检索流水线，不创建独立的修复专用知识孤岛。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "由 engineer__diagnose 返回的 proposal_id",
                    },
                },
                "required": ["proposal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "engineer__status",
            "description": (
                "获取受管工程循环（SelfHealingLoop）的当前状态快照，"
                "包括待处理的提案列表及最近完成的修复记录。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# Governed system resource layer tools (PR-7: unified resource registry)
_RESOURCE_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "resource__list",
            "description": (
                "列出受治理系统资源注册表中的所有资源。"
                "资源涵盖 GitHub、学术检索、设备/运行时、本地工具、工程支持等所有外部接入面。"
                "返回资源列表，包括类型、来源、健康状态、可用性、信任级别和能力列表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "enum": [
                            "github", "academic", "device", "local_tool",
                            "engineering", "mcp", "skill", "node", "builtin", "unknown",
                        ],
                        "description": "按资源类型过滤（可选，不填则返回全部类型）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resource__status",
            "description": (
                "获取受治理系统资源注册表的状态快照，"
                "包括已注册资源总数、健康资源数量、不可用资源数量。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resource__health",
            "description": (
                "更新指定资源的健康状态和可用性。"
                "用于运行时健康监测路径将最新状态同步到受治理资源层。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "资源唯一标识符（如 builtin__github、device__android_001）",
                    },
                    "health": {
                        "type": "string",
                        "enum": ["healthy", "degraded", "unavailable", "unknown"],
                        "description": "新的健康状态",
                    },
                    "availability": {
                        "type": "string",
                        "enum": ["available", "limited", "unavailable", "unknown"],
                        "description": "新的可用性状态（可选）",
                    },
                },
                "required": ["resource_id", "health"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resource__lookup",
            "description": "按 resource_id 或 source URI 精确查找受治理资源记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "资源唯一标识符（与 source 二选一）",
                    },
                    "source": {
                        "type": "string",
                        "description": "资源 source URI（如 github://api.github.com）",
                    },
                },
            },
        },
    },
]


# PR-515 / GAP-512-009: OpenClawd is the multimodal ingress authority.
# CriticalPathHarness records are written from _select_multimodal_route()
# so that routing decisions are canonical-runtime-inspectable, not only
# available through ContinuumState / TopologyRoutePlan projections.
CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED: str = (
    "OPENCLAWD::CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED_V1: "
    "core/openclawd.py integrates CriticalPathHarness (PR-515) at the "
    "_select_multimodal_route() boundary to record multimodal ingress "
    "and routing decisions in the canonical harness layer. "
    "Closes GAP-512-009."
)


class OpenClawd:
    """Subject Core — Cognition, Execution Branching, and Manifestation

    ``OpenClawd`` is the **subject core** / **decision core** — the inner
    cognitive and execution nucleus of the unified subject.  It is NOT a
    parallel entrypoint; it operates entirely *inside* the liminal phase of
    :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`'s
    tri-state lifecycle.

    **Architectural role**

    .. code-block:: text

        DesktopPresenceRuntime  ← runtime shell / outer authority
            └─ OpenClawd        ← subject core / decision core  (this class)
                  └─ AgentKernel  ← embedded cognition/planning sub-layer
                       ├─ _delegate_local_manifestation()   ← local execution
                       ├─ _delegate_single_remote()         ← single device delegation
                       └─ _delegate_multi_device_orchestration()  ← multi-device

    OpenClawd interprets request intent / state / execution branch and
    **delegates** manifestation/execution.  It is NOT the transport substrate
    itself, NOT a surface authority, and NOT the multi-device orchestration
    layer.  Those concerns live below and above it, respectively.

    **Four-stage process flow** (inside LIMINAL):

    1. **Ingest** — fuse request-bound ``multimodal_context`` via
       ``MultimodalBus.ingest``; attach ``runtime_session_id`` as trace ID.
    2. **Liminal / Continuum** — ``ContinuumOrchestrator.run()`` evaluates
       intent, posture (``tri_state_phase`` + ``runtime_domain``), and decision
       gate.  Produces ``state_continuum`` dict.
    3. **Branch** — ``_determine_execution_path()`` resolves the liminal
       branch: ``local`` | ``cross_device`` | ``hybrid`` | ``none``.
    4. **Manifest** — delegate to the appropriate execution point:

       - **Local manifestation** (:meth:`_delegate_local_manifestation`) —
         ``DecisionExecutor`` + local ``AgentKernel``.  Execution stays on
         this Windows device (System API, local tools).
       - **Single remote delegation** (:meth:`_delegate_single_remote`) —
         ``CommandRouter`` dispatches to one named remote device via the
         cross-device substrate (gateway / WebSocket).
       - **Multi-device orchestration delegation**
         (:meth:`_delegate_multi_device_orchestration`) — parallel subtask
         fan-out across multiple autonomous devices.  This sits *above* the
         substrate but is still initiated by OpenClawd as decision core.
       - **No-op / none** — subject responds without acting (observe / hint
         action level; ``execution_path = "none"``).

    Every response carries ``execution_path``, ``state_continuum``,
    ``runtime_domain``, ``delegation_point``, and the originating
    ``runtime_session_id`` so that the runtime shell can correlate all stages
    in its structured logs.

    串联模块:
    - ai_intent.py       -> 意图解析
    - multi_llm_router.py -> 模型选择
    - agent_factory.py   -> Agent 创建/复用
    - agent_team.py      -> 团队协作
    - device_orchestrator -> 设备操控
    - mcp_loader.py + skill_loader.py -> 协议工具调用
    """

    # 意图 -> 处理器映射
    _INTENT_HANDLER_MAP = {
        "chat": "_dispatch_chat",
        "device_control": "_dispatch_device",
        "task_manage": "_dispatch_agent",
        "file_operation": "_dispatch_agent",
        "search": "_dispatch_agent",
        "ocr": "_dispatch_tool",
        "system_status": "_dispatch_status",
        "network": "_dispatch_agent",
        "code": "_dispatch_agent",
        # Priority D: 高层自治目标执行
        "goal_execution": "_dispatch_goal_execution",
        # Priority E: 多设备并行任务
        "parallel_goal": "_dispatch_parallel_goal",
    }

    # 核心节点静态 action 目录 — 精确的节点能力描述供 LLM 工具选择
    # 格式: {node_id: {action_name: description, ...}}
    # 仅暴露高价值节点，避免工具列表膨胀 (LLM function calling 建议 ≤ 128 工具)
    _CORE_NODE_ACTIONS: Dict[str, Dict[str, str]] = {
        "06": {  # Filesystem
            "list": "列出目录内容",
            "read": "读取文件内容",
            "write": "写入文件",
            "mkdir": "创建目录",
            "delete": "删除文件或目录",
            "move": "移动/重命名文件",
            "copy": "复制文件",
            "search": "搜索文件",
        },
        "07": {  # Git
            "status": "查看仓库状态",
            "clone": "克隆仓库",
            "commit": "提交更改",
            "push": "推送到远程",
            "pull": "拉取远程更新",
            "log": "查看提交日志",
            "diff": "查看代码差异",
            "checkout": "切换分支或版本",
        },
        "08": {  # Fetch — HTTP 客户端
            "get": "发送 HTTP GET 请求",
            "post": "发送 HTTP POST 请求",
        },
        "09": {  # Sandbox — 代码沙箱
            "execute": "在安全沙箱中执行代码 (支持 Python/JS/Bash/Go/Rust/C 等 14 种语言)",
        },
        "15": {  # OCR
            "extract_text": "从图像中提取文字 (OCR)",
            "document_markdown": "将文档图像转换为 Markdown",
            "table_extract": "从图像中提取表格",
            "ui_analysis": "分析 UI 界面元素",
        },
        "17": {  # EdgeTTS — 语音合成
            "synthesize": "文本转语音合成 (支持中/英/日/韩等多语言)",
            "voices": "列出可用语音列表",
        },
        "22": {  # BraveSearch
            "search": "使用 Brave Search 进行网络搜索",
        },
        "25": {  # GoogleSearch
            "search": "使用 Google 进行网络搜索",
        },
        "33": {  # ADB — Android 设备控制
            "tap": "点击屏幕坐标",
            "swipe": "滑动屏幕",
            "shell": "执行 ADB shell 命令",
            "screenshot": "截取设备屏幕",
            "input": "输入文本",
        },
        "45": {  # DesktopAuto — 桌面自动化
            "click": "点击屏幕坐标",
            "type": "输入文本",
            "hotkey": "按下组合键",
            "screenshot": "截取桌面屏幕",
            "scroll": "滚动鼠标",
        },
        "101": {  # CodeEngine
            "parse_code": "解析和分析代码结构 (AST)",
            "generate_code": "根据需求生成代码",
            "refactor_code": "代码重构和优化",
            "review_code": "代码质量审查",
        },
        "120": {  # File (新版)
            "read": "读取文件内容",
            "write": "写入文件",
            "list": "列出目录内容",
            "search": "搜索文件",
            "info": "获取文件信息",
        },
        "121": {  # Web
            "http_request": "发送 HTTP 请求",
            "scrape": "网页抓取",
            "download": "下载文件",
            "api_call": "调用 API",
        },
        "122": {  # Shell
            "execute": "执行系统命令",
            "script": "执行脚本",
            "list_processes": "列出进程",
        },
    }

    # 从静态目录提取节点 ID 白名单
    _CORE_NODE_IDS = set(_CORE_NODE_ACTIONS.keys())

    # ── Timeout / Cancel configuration ──────────────────────────────────────
    # Timeout for a single goal_execution dispatch (seconds). Override via
    # subclass or instance attribute for test / production tuning.
    GOAL_EXECUTION_TIMEOUT: float = 60.0
    # Timeout for each parallel_subtask dispatch (seconds).
    PARALLEL_SUBTASK_TIMEOUT: float = 60.0
    # Maximum number of dynamically discovered node tools to expose to LLM.
    # LLM function calling APIs typically recommend ≤ 128 tools to avoid
    # context overflow; keep this value in sync with that constraint.
    NODE_DYNAMIC_TOOL_LIMIT: int = 128

    def __init__(self):
        self._initialized = False
        self._session_memory: Dict[str, List[Dict]] = {}
        self._request_count = 0
        self._error_count = 0
        self._start_time = time.time()
        # Node action 发现缓存: {node_id: {action_name: description}}
        self._node_actions_cache: Dict[str, Dict[str, str]] = {}
        # Node registry 缓存: {node_id: node_key}
        self._node_id_to_key: Dict[str, str] = {}
        # PR86: 持有 Router 实例（单一来源）
        self._router = None
        # PR86: 内嵌 AgentKernel（懒加载）
        self._kernel = None
        # Cancel registry — set of task_ids or group_ids that have been cancelled.
        # Using a set makes repeated cancel() calls idempotent.
        # task_ids follow the pattern "goal_<hex12>" or "<group_id>_sub<idx>";
        # group_ids are short hex strings (uuid4().hex[:8]).  The distinct
        # prefixes prevent accidental collisions between the two namespaces.
        self._cancel_registry: set = set()

        # State Continuum Orchestrator (PR-5): lazy-initialised on first request.
        self._continuum_orchestrator = None

        # Decision Executor (PR-8): lazy-initialised on first request.
        self._decision_executor = None

        # Phase 9: 工具权限检查器
        self._tool_permission_checker = None
        try:
            from core.tool_permissions import get_tool_permission_checker
            self._tool_permission_checker = get_tool_permission_checker()
        except Exception as e:
            logger.warning(f"工具权限检查器不可用，所有工具将无限制: {e}")

        # PR-001: Canonical capability dispatcher — single primary execution path
        # owned by OpenClawd.  Initialized here so that the dispatcher shares
        # the same node_id_to_key cache and permission checker as this instance.
        try:
            from core.capabilities.canonical_dispatcher import CanonicalDispatcher
            self._capability_dispatcher: Optional["CanonicalDispatcher"] = CanonicalDispatcher(
                node_id_to_key=self._node_id_to_key,
                tool_permission_checker=self._tool_permission_checker,
            )
        except Exception as _e:
            logger.warning(f"CanonicalDispatcher 初始化失败，将回退到内联路径: {_e}")
            self._capability_dispatcher = None

        # PR-7: orchestration submodule composition
        from core.orchestration.lifecycle import LifecycleManager
        from core.orchestration.state import SessionMemoryManager
        self._lifecycle_manager = LifecycleManager()
        self._session_manager = SessionMemoryManager()

        logger.info("OpenClawd 星枢核心智能体初始化")

    # ========================================================================
    # Control Plane Phase 2 helpers
    # ========================================================================

    def _emit_audit(
        self,
        event_type,
        *,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        message: str = "",
        payload: Optional[Dict] = None,
    ) -> Optional[str]:
        """Emit a :class:`~core.control_plane.TraceEvent` to the shared ledger.

        Silently swallows all exceptions so a ledger failure never breaks
        the main execution path.  Returns the new ``event_id`` or ``None``.
        """
        try:
            from core.control_plane._globals import get_audit_ledger
            from core.control_plane.audit_ledger import Severity
            return get_audit_ledger().append(
                event_type,
                severity=Severity.INFO,
                source="openclawd",
                message=message,
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                device_id=device_id,
                agent_id=agent_id,
                payload=payload or {},
            )
        except Exception:
            return None

    def _select_device_via_scheduler(
        self,
        required_capabilities: Optional[List[str]] = None,
        required_mode: Optional[str] = None,
    ) -> Optional[str]:
        """Use the smart scheduler to pick the best available device.

        Reads the device list from the shared ``connection_manager`` and
        applies :class:`~core.control_plane.DeviceScoringEngine` to return
        the highest-scoring eligible device ID, or ``None`` if no suitable
        device is found.

        Parameters
        ----------
        required_capabilities:
            List of capability strings the selected device must support.
        required_mode:
            Optional :class:`~core.schemas.remote_execution.RemoteExecutionMode`
            value string (e.g. ``"agent_runtime"``).  When supplied, only
            devices whose execution profile supports the requested mode are
            considered as candidates.  Devices with an unknown profile are
            always included (conservative / backward-compatible behaviour).
        """
        try:
            from core.control_plane._globals import get_scoring_engine, get_audit_ledger
            from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceStatus as SchedDeviceStatus
            from core.control_plane.audit_ledger import EventType, Severity
            from core.routes._shared import connection_manager
            from core.device_execution_profile import build_profile_from_device_info

            all_devices = connection_manager.get_all_devices()
            if not all_devices:
                return None

            candidates = []
            for did, info in all_devices.items():
                raw_status = info.get("status", "offline")
                if raw_status not in (SchedDeviceStatus.ONLINE, "online", "connected"):
                    continue
                caps = info.get("capabilities", [])
                if isinstance(caps, list):
                    cap_names = [
                        c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else str(c))
                        for c in caps
                    ]
                else:
                    cap_names = []

                # PR-6: filter by required execution mode when specified.
                # Devices with unknown profile are always admitted (backward-compatible).
                if required_mode:
                    try:
                        _profile = build_profile_from_device_info(info, device_id=did)
                        if (
                            _profile.profile_class != "unknown"
                            and not _profile.supports_mode(required_mode)
                        ):
                            logger.debug(
                                "_select_device_via_scheduler: skipping device=%s "
                                "(profile_class=%s does not support mode=%s)",
                                did, _profile.profile_class, required_mode,
                            )
                            continue
                    except Exception:
                        pass  # non-fatal: admit the device

                candidates.append(
                    DeviceScoreInput(
                        device_id=did,
                        status=SchedDeviceStatus.ONLINE,
                        ping_latency_ms=float(info.get("ping_ms", 0.0)),
                        load_pct=float(info.get("load_pct", 0.0)),
                        capabilities=cap_names,
                    )
                )

            if not candidates:
                return None

            engine = get_scoring_engine()
            best = engine.select_best_device(candidates, required_capabilities or [])
            if best is not None:
                # Record scheduler decision in audit ledger
                try:
                    get_audit_ledger().append(
                        EventType.SCHEDULER_DECISION,
                        severity=Severity.INFO,
                        source="openclawd.scheduler",
                        message=f"Auto-selected device {best.device_id} (score={best.total:.3f})",
                        payload={
                            "selected_device_id": best.device_id,
                            "score": best.total,
                            "required_capabilities": required_capabilities or [],
                            "candidates_count": len(candidates),
                        },
                    )
                except Exception:
                    pass
                return best.device_id
        except Exception as e:
            logger.debug("_select_device_via_scheduler failed (non-fatal): %s", e)
        return None

    def _ensure_initialized(self):
        """标记为已初始化 (懒加载模式，模块在各方法内按需导入)"""
        if not self._initialized:
            self._initialized = True
            logger.info("OpenClawd 就绪 — 所有模块将按需懒加载")

    def _get_router(self):
        """获取 OpenClawd 持有的 LLM 路由器（单例，Dashboard > ENV > defaults）"""
        if self._router is None:
            try:
                from core.multi_llm_router import get_llm_router
                self._router = get_llm_router()
            except Exception as e:
                logger.warning(f"LLM 路由器加载失败: {e}")
        return self._router

    def _get_kernel(self):
        """获取 OpenClawd 创建并持有的内嵌 AgentKernel（懒加载）。

        OpenClawd 是 AgentKernel 的唯一持有者和生命周期管理者。
        AgentKernel 作为认知/规划层嵌入在 OpenClawd 内部，不对外暴露为独立主权。

        职责说明：
          - 创建并持有 AgentKernel 实例（_kernel 属性）
          - 将 OpenClawd 管理的 LLM Router 注入到 Kernel
          - 返回 KernelResponse（认知产物），由 OpenClawd 解释后决定执行/委托动作
        """
        if self._kernel is None:
            try:
                from core.agent.kernel import AgentKernel
                self._kernel = AgentKernel()
                # 将 OpenClawd 持有的 router 注入到 Kernel
                router = self._get_router()
                if router is not None:
                    self._kernel._llm_router = router
            except Exception as e:
                logger.warning(f"AgentKernel 加载失败: {e}")
        return self._kernel

    # ========================================================================
    # Cancel / Abort API
    # ========================================================================

    def cancel_task(self, task_id: str) -> bool:
        """Mark a task (by task_id) as cancelled.

        Idempotent — calling multiple times for the same task_id is safe.

        Returns:
            True  if the task_id was newly added to the cancel registry.
            False if it was already cancelled (idempotent no-op).
        """
        if task_id in self._cancel_registry:
            logger.debug("cancel_task: %s already cancelled (idempotent)", task_id)
            return False
        self._cancel_registry.add(task_id)
        logger.info("cancel_task: %s added to cancel registry", task_id)
        return True

    def cancel_group(self, group_id: str) -> bool:
        """Mark an entire parallel group (by group_id) as cancelled.

        Adds the group_id itself to the cancel registry so that any
        in-flight subtask that checks ``_is_cancelled(entry)`` will abort.

        Idempotent — safe to call multiple times.

        Returns:
            True  if the group_id was newly added to the cancel registry.
            False if it was already cancelled.
        """
        if group_id in self._cancel_registry:
            logger.debug("cancel_group: %s already cancelled (idempotent)", group_id)
            return False
        self._cancel_registry.add(group_id)
        logger.info("cancel_group: %s added to cancel registry", group_id)
        return True

    def _is_cancelled(self, task_id: str, group_id: Optional[str] = None) -> bool:
        """Return True if task_id or its group_id is in the cancel registry."""
        if task_id in self._cancel_registry:
            return True
        if group_id and group_id in self._cancel_registry:
            return True
        return False

    # ========================================================================
    # State Continuum (PR-5)
    # ========================================================================

    def _get_continuum_orchestrator(self):
        """Return a cached :class:`~core.continuum.orchestrator.ContinuumOrchestrator`.

        Reads ``enable_continuum`` / ``debug_continuum`` from ``config.json``
        (via :mod:`core.unified_config`) and passes them as ``extra_flags``
        to the orchestrator constructor.  The orchestrator is created once and
        reused across requests so that the :class:`~core.continuum.temporal_engine.TemporalEngine`
        accumulates state across successive ticks.

        Returns:
            :class:`~core.continuum.orchestrator.ContinuumOrchestrator` instance,
            or ``None`` when the import fails or construction raises an exception.
        """
        if self._continuum_orchestrator is None:
            try:
                from core.unified_config import config as _cfg
                extra_flags = {
                    "enable_continuum": _cfg.get("enable_continuum", True),
                    "debug_continuum": _cfg.get("debug_continuum", False),
                    "enable_perception": _cfg.get("enable_perception", True),
                    "enable_human_field": _cfg.get("enable_human_field", True),
                    "enable_liminal_field": _cfg.get("enable_liminal_field", True),
                    "enable_decision_gate": _cfg.get("enable_decision_gate", True),
                    "continuum_max_tick_ms": _cfg.get("continuum_max_tick_ms", 0),
                    "continuum_sampling_rate": _cfg.get("continuum_sampling_rate", 1.0),
                }
            except Exception:
                extra_flags = {}
            try:
                from core.continuum.orchestrator import ContinuumOrchestrator
                self._continuum_orchestrator = ContinuumOrchestrator(extra_flags=extra_flags)
            except Exception as e:
                logger.debug("ContinuumOrchestrator unavailable: %s", e)
        return self._continuum_orchestrator

    def _run_continuum(
        self,
        trace_id: str,
        multimodal_context: Optional[Any] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run one continuum evaluation cycle and return a serialisable dict.

        Attempts to source a :class:`~core.multimodal.perception_frame.PerceptionFrame`
        from the multimodal ingress bus.  Falls back to a minimal default
        frame when the bus is unavailable.

        Args:
            trace_id:           Correlation ID for the originating request.
            multimodal_context: Optional multimodal context (unused directly;
                               reserved for future ingress bus enrichment).
            runtime_session_id: Optional identifier from
                               :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
                               Forwarded to the continuum orchestrator so that
                               evaluation log entries carry the runtime correlation key.

        Returns:
            A ``dict`` representation of the resulting
            :class:`~core.continuum.types.ContinuumState`, or ``None`` when
            the continuum is disabled or an unrecoverable error occurs.
        """
        try:
            orch = self._get_continuum_orchestrator()
            if orch is None:
                return None

            # Try to obtain a live PerceptionFrame from the running singleton
            # ingress bus (PR-3).  If the singleton is not running (bus disabled
            # or no pipelines wired) fall back to a fresh bus instance that
            # returns a default frame with all-missing quality.
            frame = None
            try:
                from core.multimodal.ingest_runtime import get_ingest_bus as _get_ingest_bus
                _running_bus = _get_ingest_bus()
                if _running_bus is not None:
                    frame = _running_bus.build_frame()
                else:
                    from core.multimodal.ingress_bus import MultimodalIngressBus
                    frame = MultimodalIngressBus().build_frame()
            except Exception:
                pass  # orchestrator will construct a minimal default

            continuum_state = orch.run(
                frame=frame,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            return continuum_state.model_dump()
        except Exception as _ce:
            logger.debug("_run_continuum failed (degrading to None): %s", _ce)
            return None

    def _get_decision_executor(self):
        """Return a cached :class:`~core.execution.decision_executor.DecisionExecutor`.

        The executor is created once and reused across requests.  Returns
        ``None`` when the module is unavailable so the caller can skip
        execution silently.
        """
        if self._decision_executor is None:
            try:
                from core.execution.decision_executor import DecisionExecutor
                self._decision_executor = DecisionExecutor()
            except Exception as exc:
                logger.debug("DecisionExecutor unavailable: %s", exc)
        return self._decision_executor

    def _run_execution(
        self,
        state_continuum: Optional[Dict[str, Any]],
        entry_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke the decision executor against the continuum state.

        Errors are swallowed so the response flow is never interrupted.

        Args:
            state_continuum: Serialised ContinuumState dict, or ``None``.
            entry_mode: Execution mode from the ingress layer
                (``"local"`` | ``"cross_device"`` | ``"hybrid"`` | ``None``).
                Forwarded to :meth:`~core.execution.decision_executor.DecisionExecutor.execute`
                for mode-aware gating.  When ``None`` the executor falls back
                to config-based policy (backward-compatible).

        Returns:
            Serialisable dict representation of the
            :class:`~core.execution.decision_executor.ExecutionResult`
            (always returned, never raises).  Includes an additive
            ``"execution_intent"`` key carrying a compact
            :class:`~core.execution.intent_profile.ExecutionIntentProfile`
            summary (PR-22).
        """
        # PR-22: Build the canonical execution intent profile before dispatching.
        # This is additive — downstream code is not required to consume it.
        _intent_profile = self._build_intent_profile(
            state_continuum,
            entry_mode=entry_mode,
        )

        # PR-23: Consult the Execution Readiness Gate before action dispatch.
        # Blocked / observe-only results surface a structured skipped_reason.
        # Errors in the gate are fully isolated and never break response flow.
        _readiness = self._check_readiness(_intent_profile, state_continuum)
        if _readiness is not None and not _readiness.ready:
            logger.debug(
                "_run_execution: readiness gate blocked — status=%s blocked_by=%s reason=%r intent_id=%s",
                _readiness.status,
                _readiness.blocked_by,
                _readiness.reason,
                getattr(_intent_profile, "intent_id", "unknown"),
            )
            _blocked_result: Dict[str, Any] = {
                "action_taken": "none",
                "success": False,
                "skipped_reason": f"readiness_gate:{_readiness.status}:{_readiness.blocked_by}",
                "execution_intent": _intent_profile.compact_summary(),
                "readiness": _readiness.governance_summary(),
            }
            # PR-24: Emit a fallback decision trace for the blocked path.
            _blocked_result["fallback_trace"] = self._build_fallback_trace(
                _intent_profile, _readiness, _blocked_result
            )
            # PR-25: Emit a canonical execution trace envelope for the blocked lifecycle.
            _blocked_result["execution_trace"] = self._build_execution_trace(
                _intent_profile, _readiness, _blocked_result
            )
            return _blocked_result

        try:
            executor = self._get_decision_executor()
            if executor is None:
                _no_exec_result: Dict[str, Any] = {
                    "action_taken": "none",
                    "success": False,
                    "skipped_reason": "executor_unavailable",
                    "execution_intent": _intent_profile.compact_summary(),
                    "readiness": _readiness.governance_summary() if _readiness else None,
                }
                # PR-24: Trace the executor-unavailable fallback.
                _no_exec_result["fallback_trace"] = self._build_fallback_trace(
                    _intent_profile, _readiness, _no_exec_result
                )
                # PR-25: Emit a canonical execution trace envelope.
                _no_exec_result["execution_trace"] = self._build_execution_trace(
                    _intent_profile, _readiness, _no_exec_result
                )
                return _no_exec_result
            # Extract force_local_execution override from state_continuum metadata
            # (allows per-request override when entry_mode=cross_device).
            _force: bool = False
            if state_continuum and isinstance(state_continuum, dict):
                _meta = state_continuum.get("metadata") or {}
                if isinstance(_meta, dict):
                    _force = bool(_meta.get("force_local_execution", False))
            result = executor.execute(
                state_continuum,
                entry_mode=entry_mode,
                force_local_execution=_force,
            )
            if result.action_taken not in ("noop", "none"):
                logger.debug(
                    "_run_execution: action=%s target=%r success=%s intent_id=%s",
                    result.action_taken, result.target, result.success,
                    _intent_profile.intent_id,
                )
            _exec_dict: Dict[str, Any] = {
                "action_taken": result.action_taken,
                "target": result.target,
                "success": result.success,
                "skipped_reason": result.skipped_reason,
                "metadata": result.metadata,
                "execution_intent": _intent_profile.compact_summary(),
                "readiness": _readiness.governance_summary() if _readiness else None,
            }
            # PR-24: Emit a fallback decision trace for every execution result.
            _exec_dict["fallback_trace"] = self._build_fallback_trace(
                _intent_profile, _readiness, _exec_dict
            )
            # PR-25: Emit a canonical execution trace envelope.
            _exec_dict["execution_trace"] = self._build_execution_trace(
                _intent_profile, _readiness, _exec_dict
            )
            return _exec_dict
        except Exception as _ee:
            logger.debug("_run_execution failed (swallowed): %s", _ee)
            _err_result: Dict[str, Any] = {
                "action_taken": "error",
                "success": False,
                "skipped_reason": f"internal_error: {_ee}",
                "execution_intent": _intent_profile.compact_summary(),
                "readiness": _readiness.governance_summary() if _readiness else None,
            }
            # PR-24: Trace the internal-error fallback.
            _err_result["fallback_trace"] = self._build_fallback_trace(
                _intent_profile, _readiness, _err_result
            )
            # PR-25: Emit a canonical execution trace envelope.
            _err_result["execution_trace"] = self._build_execution_trace(
                _intent_profile, _readiness, _err_result
            )
            return _err_result

    def _build_intent_profile(
        self,
        state_continuum: Optional[Dict[str, Any]],
        entry_mode: Optional[str] = None,
    ):
        """Build an :class:`~core.execution.intent_profile.ExecutionIntentProfile` (PR-22).

        Gracefully returns a minimal safe profile on any error.
        """
        try:
            from core.execution.intent_profile import build_execution_intent_profile  # noqa: PLC0415
            _session_id: Optional[str] = None
            if state_continuum and isinstance(state_continuum, dict):
                _meta = state_continuum.get("metadata") or {}
                if isinstance(_meta, dict):
                    _session_id = _meta.get("runtime_session_id") or None
            return build_execution_intent_profile(
                state_continuum,
                runtime_session_id=_session_id,
                source="openclawd",
                entry_mode=entry_mode,
            )
        except Exception as _exc:
            logger.debug("_build_intent_profile failed (swallowed): %s", _exc)
            try:
                from core.execution.intent_profile import ExecutionIntentProfile  # noqa: PLC0415
                return ExecutionIntentProfile(source="openclawd")
            except Exception:
                # Absolute last resort — return a minimal stub that matches the
                # compact_summary() contract from ExecutionIntentProfile.
                class _Stub:  # noqa: SIM115
                    intent_id = "unknown"

                    def compact_summary(self) -> Dict[str, Any]:  # noqa: ANN201
                        return {
                            "intent_id": "unknown",
                            "source": "openclawd",
                            "action_level": "observe",
                            "intent_mode": "advisory",
                            "target_type": None,
                            "target_ref": None,
                            "device_scope": None,
                            "runtime_domain": None,
                            "confidence": 0.0,
                            "degrade_reason": "intent_profile_unavailable",
                        }

                return _Stub()

    def _check_readiness(
        self,
        intent_profile: Any,
        state_continuum: Optional[Dict[str, Any]],
    ) -> Optional[Any]:
        """Consult the Execution Readiness Gate (PR-23).

        Gracefully returns ``None`` when the gate module is unavailable so that
        the existing execution flow is never interrupted.

        Args:
            intent_profile: The :class:`~core.execution.intent_profile.ExecutionIntentProfile`
                built by :meth:`_build_intent_profile`.
            state_continuum: Serialised ContinuumState dict, or ``None``.

        Returns:
            A :class:`~core.execution.readiness_gate.ReadinessResult`, or
            ``None`` when the gate is unavailable.
        """
        try:
            from core.execution.readiness_gate import evaluate_readiness  # noqa: PLC0415
            return evaluate_readiness(
                intent_profile,
                state_continuum=state_continuum,
            )
        except Exception as _exc:
            logger.debug("_check_readiness failed (swallowed): %s", _exc)
            return None

    def _build_fallback_trace(
        self,
        intent_profile: Any,
        readiness_result: Any,
        execution_result: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Build a :class:`~core.execution.fallback_trace.FallbackDecisionTrace` (PR-24).

        Produces a compact fallback decision trace record from the intent
        profile, readiness gate result, and execution result.  Errors are
        fully isolated — ``None`` is returned when the module is unavailable
        or an unexpected exception occurs so that the existing response flow
        is never interrupted.

        Args:
            intent_profile: The :class:`~core.execution.intent_profile.ExecutionIntentProfile`
                built by :meth:`_build_intent_profile`.
            readiness_result: The :class:`~core.execution.readiness_gate.ReadinessResult`
                returned by :meth:`_check_readiness`, or ``None``.
            execution_result: The serialised execution result dict (before the
                ``"fallback_trace"`` key is inserted), or ``None``.

        Returns:
            A compact fallback trace dict, or ``None`` on failure.
        """
        try:
            from core.execution.fallback_trace import (  # noqa: PLC0415
                build_fallback_trace,
                summarize_fallback_trace,
            )
            _trace = build_fallback_trace(
                intent_profile=intent_profile,
                readiness_result=readiness_result,
                execution_result=execution_result,
            )
            return summarize_fallback_trace(_trace)
        except Exception as _exc:
            logger.debug("_build_fallback_trace failed (swallowed): %s", _exc)
            return None

    def _emit_routing_decision_event(
        self,
        route_dict: Dict[str, Any],
        *,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-41: Emit a structured routing observability event from a canonical routing decision.

        Records the routing decision into the global :class:`~core.routing_observability.ControlLoopMetrics`
        singleton and returns a compact serialisable dict for embedding in response
        metadata.  Errors are fully isolated — ``None`` is returned on any failure
        so that the existing request flow is never interrupted.

        Parameters
        ----------
        route_dict:
            The dict returned by :meth:`_select_multimodal_route`.
        trace_id:
            Correlation trace ID for the request.
        runtime_session_id:
            Active session ID for the request.

        Returns
        -------
        dict or None
            Serialisable :class:`~core.routing_observability.RoutingDecisionEvent` dict,
            or ``None`` on failure.
        """
        try:
            from core.routing_observability import record_routing_decision  # noqa: PLC0415

            event = record_routing_decision(
                route_dict,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            return event.to_dict()
        except Exception as _exc:
            logger.debug("_emit_routing_decision_event failed (swallowed): %s", _exc)
            return None

    def _build_degraded_operation_envelope(
        self,
        route_dict: Dict[str, Any],
        *,
        supply_snapshot: Optional[Dict[str, Any]] = None,
        prior_envelope: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-29: Build a canonical :class:`~core.degraded_operation_envelope.DegradedOperationEnvelope`.

        Converts the routing decision dict produced by
        :meth:`_select_multimodal_route` into a normalised, serialisable
        degraded-operation envelope that captures the current degradation level,
        provider failover chain, fallback policy ladder, and operator-facing
        severity.

        This is the primary integration point for PR-29 — the envelope is
        embedded in every response so that downstream projection and diagnostics
        layers can consume it without inventing their own degradation semantics.

        Parameters
        ----------
        route_dict:
            The dict returned by :meth:`_select_multimodal_route`.
        supply_snapshot:
            Optional canonical model supply state dict for deriving skipped
            provider steps in the failover chain.
        prior_envelope:
            Optional prior envelope dict for tracking level transitions across
            the control loop.
        trace_id:
            Correlation trace ID for the request.

        Returns
        -------
        dict or None
            Serialisable :class:`~core.degraded_operation_envelope.DegradedOperationEnvelope`
            dict, or ``None`` on failure.
        """
        try:
            from core.degraded_operation_envelope import (  # noqa: PLC0415
                build_degraded_operation_envelope,
                envelope_summary,
            )

            env = build_degraded_operation_envelope(
                route_dict=route_dict,
                supply_snapshot=supply_snapshot,
                prior_envelope=prior_envelope,
                trace_id=trace_id,
            )
            return env.to_dict()
        except Exception as _exc:
            logger.debug("_build_degraded_operation_envelope failed (swallowed): %s", _exc)
            return None

    def _apply_latency_budget(
        self,
        *,
        multimodal_context: Any,
        canonical_perception: Optional[Dict[str, Any]],
        multimodal_route: Optional[Dict[str, Any]],
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """PR-30: Apply control-loop latency budgets and return a serialisable summary.

        Evaluates ingest cadence, control-plan recompute, projection refresh,
        provider-selection latency, and text-only fast-path eligibility for the
        current control-loop iteration.  The returned dict is embedded in
        response metadata for structured latency accounting without coupling to
        a specific dashboard implementation.

        Errors are fully isolated — ``None`` is returned on any failure so that
        the existing response flow is never interrupted.

        Args:
            multimodal_context:
                Raw multimodal context payload supplied to :meth:`process`.
            canonical_perception:
                Canonical perception state dict (PR-16).
            multimodal_route:
                Routing decision dict returned by :meth:`_select_multimodal_route`.
            trace_id:
                Trace identifier for the current request.
            runtime_session_id:
                Runtime session identifier for the current request.

        Returns:
            Serialised :class:`~core.control_loop_latency_budget.LatencyBudgetSummary`
            dict, or ``None`` on error.
        """
        try:
            from core.control_loop_latency_budget import (
                assess_text_only_fast_path as _assess_fp,
                build_latency_budget_summary as _build_summary,
                get_control_loop_latency_budget as _get_budget,
                IngestCadencePolicy as _ICP,
                RecomputePolicy as _RCP,
                ProjectionRefreshPolicy as _PRP,
            )

            _budget = _get_budget()

            # ── Text-only fast path assessment ────────────────────────────────
            _fp = _assess_fp(
                multimodal_context=multimodal_context,
                canonical_perception=canonical_perception,
            )

            # ── Ingest cadence decision ───────────────────────────────────────
            _ingest_policy: _ICP = _budget.decide_ingest_cadence(
                has_multimodal_context=_fp.has_multimodal_context,
                is_text_only=_fp.is_text_only,
            )

            # ── Control-plan recompute decision ───────────────────────────────
            _recompute_policy: _RCP = _budget.decide_recompute()

            # ── Projection refresh decision ───────────────────────────────────
            # Use route_type as a lightweight fingerprint for suppression.
            _fp_hint = (multimodal_route or {}).get("route_type") if multimodal_route else None
            _projection_policy: _PRP = _budget.decide_projection_refresh(
                state_fingerprint=_fp_hint,
            )

            # ── Provider selection latency recording ──────────────────────────
            _route_type = (multimodal_route or {}).get("route_type", "unknown") if multimodal_route else "unknown"
            _provider_budget = _budget.record_provider_selection(
                measured_ms=0.0,  # measured at call site; 0.0 is safe default
                route_type=str(_route_type),
                fast_path_applied=_fp.is_text_only,
            )

            # ── Compose summary ───────────────────────────────────────────────
            _summary = _build_summary(
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
                ingest_cadence_policy=_ingest_policy,
                recompute_policy=_recompute_policy,
                projection_refresh_policy=_projection_policy,
                provider_selection_budget=_provider_budget,
                text_only_fast_path=_fp,
                ingest_window_stats=_budget.snapshot_ingest_stats(),
                recompute_window_stats=_budget.snapshot_recompute_stats(),
                projection_window_stats=_budget.snapshot_projection_stats(),
            )
            return _summary.to_dict()
        except Exception as _exc:
            logger.debug("_apply_latency_budget failed (swallowed): %s", _exc)
            return None

    def _build_permission_safety_state(
        self,
        *,
        source_registry_snapshot: Optional[Dict[str, Any]] = None,
        multimodal_route: Optional[Dict[str, Any]] = None,
        execution_plan: Optional[Dict[str, Any]] = None,
        degraded_operation_envelope: Optional[Dict[str, Any]] = None,
        canonical_perception: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-32: Build the canonical permission/trust/safety snapshot.

        Aggregates permission visibility, trust/risk labels, and control-safety
        state from the current shell-owned source registry, routing decision,
        execution plan, and degraded-operation envelope into a single canonical
        :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot`.

        The snapshot is embedded in response metadata so projection and
        diagnostics layers consume an authoritative safety view without
        inventing separate trust semantics.

        Parameters
        ----------
        source_registry_snapshot:
            Shell-owned source registry snapshot dict.
        multimodal_route:
            Current multimodal route decision dict.
        execution_plan:
            Current execution plan dict.
        degraded_operation_envelope:
            Canonical degraded-operation envelope dict (PR-29).
        canonical_perception:
            Canonical perception state dict.
        trace_id:
            Correlation trace ID.
        runtime_session_id:
            Runtime session identifier.

        Returns
        -------
        dict or None
            Serialisable :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot`
            dict, or ``None`` on failure.
        """
        try:
            from core.multimodal.permission_safety_state import (  # noqa: PLC0415
                build_permission_safety_snapshot,
                get_permission_safety_state,
            )

            snap = build_permission_safety_snapshot(
                source_registry_snapshot=source_registry_snapshot,
                multimodal_route=multimodal_route,
                execution_plan=execution_plan,
                degraded_operation_envelope=degraded_operation_envelope,
                canonical_perception=canonical_perception,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            # Commit to singleton so diagnostics/projection can access without
            # rebuilding.
            get_permission_safety_state().commit(snap)
            return snap.to_dict()
        except Exception as _exc:
            logger.debug("_build_permission_safety_state failed (swallowed): %s", _exc)
            return None

    def _apply_operator_overrides(
        self,
        *,
        multimodal_route: Optional[Dict[str, Any]],
        cross_device_allowed: bool = True,
        remote_mode: Optional[str] = None,
        current_audio_source_id: Optional[str] = None,
        current_video_source_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-33: Apply canonical operator overrides and return a serialisable snapshot.

        Reads the active :class:`~core.operator_override.OperatorOverrideSet`
        from the process-wide singleton and applies any active overrides to the
        supplied routing and execution-policy inputs.  The resulting
        :class:`~core.operator_override.OperatorOverrideSnapshot` is embedded in
        response metadata so that projection, diagnostics, and explainability
        layers can surface override-influenced decisions.

        Overrides are **inputs** to canonical control decisions.  This method
        does not bypass any other policy authority; it shapes the inputs that the
        control core then finalises.

        Parameters
        ----------
        multimodal_route:
            The dict returned by :meth:`_select_multimodal_route`, modified
            in-place if an override applies.
        cross_device_allowed:
            Canonical cross-device expansion flag from the execution policy.
        remote_mode:
            Canonical remote-execution mode string.
        current_audio_source_id:
            Current primary audio source ID (from shell-owned registry).
        current_video_source_id:
            Current primary video source ID (from shell-owned registry).
        trace_id:
            Correlation trace ID.
        runtime_session_id:
            Runtime session identifier.

        Returns
        -------
        dict or None
            Serialisable :class:`~core.operator_override.OperatorOverrideSnapshot`
            dict enriched with applied override details, or ``None`` on failure.
        """
        try:
            from core.operator_override import (  # noqa: PLC0415
                get_operator_override_state,
                apply_route_override,
                apply_execution_policy_override,
                apply_source_override,
                build_override_summary,
                OperatorOverrideSnapshot,
            )

            state = get_operator_override_state()
            override_set = state.active_override_set

            # ── Route override ──────────────────────────────────────────────
            if multimodal_route is not None and override_set is not None:
                overridden_route = apply_route_override(multimodal_route, override_set)
                # Mutate the dict in-place: the caller holds a reference to this
                # dict and re-reads it after this method returns (e.g. to refresh
                # _is_native_multimodal).  Replacing all keys preserves the reference
                # while applying all override changes atomically.
                multimodal_route.clear()
                multimodal_route.update(overridden_route)

            # ── Execution policy override ────────────────────────────────────
            _exec_override = apply_execution_policy_override(
                cross_device_allowed=cross_device_allowed,
                remote_mode=remote_mode,
                override_set=override_set,
            )

            # ── Source selection override ────────────────────────────────────
            _src_override = apply_source_override(
                current_audio_source_id=current_audio_source_id,
                current_video_source_id=current_video_source_id,
                override_set=override_set,
            )

            # ── Build snapshot ───────────────────────────────────────────────
            snap = state.snapshot(
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            snap_dict = snap.to_dict()

            # Enrich snapshot dict with per-domain application results
            snap_dict["execution_policy_override"] = _exec_override
            snap_dict["source_override"] = _src_override
            snap_dict["summary"] = build_override_summary(snap)

            return snap_dict
        except Exception as _exc:
            logger.debug("_apply_operator_overrides failed (swallowed): %s", _exc)
            return None

    def _build_decision_timeline_snapshot(
        self,
        *,
        route_dict: Optional[Dict[str, Any]] = None,
        degraded_operation_envelope: Optional[Dict[str, Any]] = None,
        permission_safety_state: Optional[Dict[str, Any]] = None,
        operator_override_state: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-34: Build a canonical :class:`~core.decision_timeline.ExplainabilitySnapshot`.

        Records decision events derived from the canonical control-loop
        artifacts produced in this iteration (routing, fallback, operator
        overrides, trust/safety gating) into the process-wide
        :class:`~core.decision_timeline.DecisionTimeline` singleton, then
        captures and returns an :class:`~core.decision_timeline.ExplainabilitySnapshot`
        dict.

        All explanations originate from canonical decisions made earlier in
        this method — nothing is reconstructed from logs or ad-hoc text.

        Parameters
        ----------
        route_dict:
            The routing-decision dict from :meth:`_select_multimodal_route`
            (potentially mutated in-place by :meth:`_apply_operator_overrides`).
        degraded_operation_envelope:
            Serialised :class:`~core.degraded_operation_envelope.DegradedOperationEnvelope`
            from :meth:`_build_degraded_operation_envelope`.
        permission_safety_state:
            Serialised :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot`
            from :meth:`_build_permission_safety_state`.
        operator_override_state:
            Serialised :class:`~core.operator_override.OperatorOverrideSnapshot`
            from :meth:`_apply_operator_overrides`.
        trace_id:
            Correlation trace ID for this control-loop iteration.
        runtime_session_id:
            Runtime / OpenClawd session identifier.

        Returns
        -------
        dict or None
            Serialisable :class:`~core.decision_timeline.ExplainabilitySnapshot`
            dict, or ``None`` on failure.
        """
        try:
            from core.decision_timeline import (  # noqa: PLC0415
                record_route_selection_event,
                record_operator_override_event,
                record_trust_safety_gating_event,
                build_explainability_snapshot,
            )

            # ── Route / fallback decision ──────────────────────────────────
            if isinstance(route_dict, dict):
                record_route_selection_event(
                    route_dict=route_dict,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                )

            # ── Operator override influence ────────────────────────────────
            if isinstance(operator_override_state, dict):
                record_operator_override_event(
                    override_snapshot_dict=operator_override_state,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                )

            # ── Trust / safety gating influence ───────────────────────────
            if isinstance(permission_safety_state, dict):
                record_trust_safety_gating_event(
                    permission_safety_dict=permission_safety_state,
                    trace_id=trace_id,
                    runtime_session_id=runtime_session_id,
                )

            snap = build_explainability_snapshot(
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            return snap.to_dict()
        except Exception as _exc:
            logger.debug("_build_decision_timeline_snapshot failed (swallowed): %s", _exc)
            return None

    def _build_execution_trace(
        self,
        intent_profile: Any,
        readiness_result: Any,
        execution_result: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Build a compact :class:`~contracts.execution_trace.ExecutionTraceEnvelope` (PR-25).

        Produces a compact execution trace envelope covering all lifecycle stages
        that have completed in this execution run.  Errors are fully isolated —
        ``None`` is returned when the module is unavailable or an unexpected
        exception occurs so that the existing response flow is never interrupted.

        Args:
            intent_profile: The :class:`~core.execution.intent_profile.ExecutionIntentProfile`
                built by :meth:`_build_intent_profile`.
            readiness_result: The :class:`~core.execution.readiness_gate.ReadinessResult`
                returned by :meth:`_check_readiness`, or ``None``.
            execution_result: The serialised execution result dict (before the
                ``"execution_trace"`` key is inserted), or ``None``.

        Returns:
            A compact execution trace envelope dict, or ``None`` on failure.
        """
        try:
            from contracts.execution_trace import build_trace_envelope  # noqa: PLC0415

            # Extract the fallback_trace object from execution_result if present;
            # it may be a dict (compact summary) — pass as-is to the builder
            # which handles duck-typed objects gracefully.
            _ft = None
            if execution_result and isinstance(execution_result, dict):
                _ft = execution_result.get("fallback_trace")

            _envelope = build_trace_envelope(
                intent_profile=intent_profile,
                readiness_result=readiness_result,
                fallback_trace=_ft,
                execution_result=execution_result,
            )
            return _envelope.compact_summary()
        except Exception as _exc:
            logger.debug("_build_execution_trace failed (swallowed): %s", _exc)
            return None

    def _build_mainline_convergence_stamp(
        self,
        *,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        execution_path: Optional[str] = None,
        capability_source: Optional[str] = None,
        knowledge_source: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-8: Build the mainline convergence stamp for this response.

        Records one :class:`~core.mainline_convergence.MainlineExecutionTrace`
        in the module-level registry and returns a compact dict suitable for
        embedding in response metadata.  Errors are fully isolated — ``None``
        is returned on any failure so the response flow is never interrupted.

        Returns:
            Compact mainline convergence dict, or ``None`` on failure.
        """
        try:
            from core.mainline_convergence import (
                build_mainline_trace,
                get_mainline_convergence_registry,
                MainlineChainStage,
                MainlinePathClass,
                OPENCLAWD_AUTHORITY_ROLE,
            )

            trace = build_mainline_trace(
                trace_id=trace_id,
                session_id=session_id,
                task_id=task_id,
                entry_stage=MainlineChainStage.OPENCLAWD_AUTHORITY,
                execution_path=execution_path,
                path_class=MainlinePathClass.MAINLINE,
                authority_role=OPENCLAWD_AUTHORITY_ROLE,
                capability_source=capability_source,
                knowledge_source=knowledge_source,
                resource_type=resource_type,
            )
            trace.add_stage(MainlineChainStage.RESPONSE_EMISSION)
            trace.close(success=True)
            get_mainline_convergence_registry().record(trace)

            return {
                "trace_id": trace.trace_id,
                "path_class": trace.path_class,
                "stages_visited": list(trace.stages_visited),
                "authority_role": trace.authority_role,
                "execution_path": trace.execution_path,
            }
        except Exception as _exc:
            logger.debug("_build_mainline_convergence_stamp failed (swallowed): %s", _exc)
            return None

    def _build_production_baseline_summary(
        self,
        *,
        response_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-36: Build a compact production baseline status summary.

        Confirms that the unified canonical control loop is active as the
        production baseline and reports coverage of canonical primary artifacts
        found in *response_metadata*.  Errors are fully isolated — ``None``
        is returned on any failure so the response flow is never interrupted.

        Args:
            response_metadata:
                The partially-assembled metadata dict for the current response.
                When provided, canonical artifact coverage is assessed.

        Returns:
            Compact production baseline summary dict, or ``None`` on failure.
        """
        try:
            from core.production_baseline import build_production_baseline_summary as _build_pbs

            return _build_pbs(response_metadata=response_metadata or {})
        except Exception as _exc:
            logger.debug("_build_production_baseline_summary failed (swallowed): %s", _exc)
            return None

    def _build_canonical_perception_state(
        self,
        *,
        runtime_session_id: Optional[str] = None,
        trace_id: str = "",
        multimodal_context: Optional[Any] = None,
        fused_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-16: Build a serializable :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState` dict.

        Assembles the canonical perception truth from two sources:

        1. **Continuous host perception** — the latest
           :class:`~core.multimodal.perception_frame.PerceptionFrame` from the
           runtime shell's ``MultimodalIngressBus`` singleton (if available).
        2. **Request-bound multimodal context** — the fused output from
           ``MultimodalBus.ingest()`` plus the raw ``multimodal_context`` bundle.

        The runtime shell owns and provides the continuous perception snapshot;
        OpenClawd consumes both sources here as its primary perception contract.

        Returns:
            ``to_dict()`` output of the canonical state, or ``None`` when the
            builder itself raises an unrecoverable exception (should not occur
            in practice).
        """
        try:
            from core.perception.canonical_perception_state import build_canonical_perception_state as _build_cps

            # Try to obtain a live PerceptionFrame from the running singleton
            # ingress bus (owned by the runtime shell).  Gracefully falls back
            # to None when the bus is disabled or unavailable.
            _frame = None
            try:
                from core.multimodal.ingest_runtime import get_ingest_bus as _get_ib
                _running_bus = _get_ib()
                if _running_bus is not None:
                    _frame = _running_bus.build_frame()
            except Exception:
                pass  # continuous perception unavailable; degrade gracefully

            _cps = _build_cps(
                runtime_session_id=runtime_session_id,
                trace_id=trace_id,
                fused_context=fused_context,
                multimodal_context=multimodal_context,
                continuous_frame=_frame,
            )
            return _cps.to_dict()
        except Exception as _cps_err:
            logger.debug("_build_canonical_perception_state failed (swallowed): %s", _cps_err)
            return None

    def _build_canonical_model_supply_state(self) -> Optional[Dict[str, Any]]:
        """PR-24: Build a serialisable canonical model supply state dict.

        Wires the canonical model supply truth (PR-18) into the unified
        control-loop state so the :class:`~core.schemas.unified_control_plan.UnifiedControlPlan`
        captures model supply alongside perception truth.  This closes the gap
        where :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
        was introduced by PR-18 but not yet forwarded into the control plan.

        Called once per :meth:`process` invocation, before
        :meth:`_build_unified_control_plan`, so the result can be passed to
        both the kernel and direct execution return paths.

        Returns:
            ``to_dict()`` output of
            :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`,
            or ``None`` when the router or supply builder is unavailable
            (graceful degradation — text-only / restricted deployments are
            unaffected).
        """
        try:
            from core.model_topology.canonical_model_supply_state import (
                build_canonical_model_supply_state_from_router as _build_cmss,
            )

            _router = self._get_router()
            if _router is None:
                return None
            _cmss = _build_cmss(_router)
            return _cmss.to_dict()
        except Exception as _cmss_err:
            logger.debug(
                "_build_canonical_model_supply_state failed (swallowed): %s", _cmss_err
            )
            return None

    def _build_execution_plan(
        self,
        *,
        execution_path: str,
        delegation_point: Optional[str] = None,
        trace_id: str = "",
        session_id: str = "",
        device_id: Optional[str] = None,
        remote_execution_mode: Optional[str] = None,
        required_capabilities: Optional[List[str]] = None,
        orchestration_plan_id: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ):
        """PR-11: Build a canonical :class:`~core.schemas.execution_plan.ExecutionPlan`.

        Called by :meth:`process` after
        :meth:`_determine_execution_path` has resolved the execution branch
        but before any delegation method is called.  The plan is an additive
        record of execution intent — existing callers that do not inspect the
        ``execution_plan`` key in the response are unaffected.

        Returns the constructed :class:`~core.schemas.execution_plan.ExecutionPlan`
        or ``None`` when the schema module is unavailable (to maintain
        graceful degradation in restricted environments).
        """
        try:
            from core.schemas.execution_plan import build_execution_plan as _bep
            return _bep(
                execution_path=execution_path,
                delegation_point=delegation_point,
                trace_id=trace_id,
                session_id=session_id or "",
                device_id=device_id,
                remote_execution_mode=remote_execution_mode,
                required_capabilities=required_capabilities,
                orchestration_plan_id=orchestration_plan_id,
                timeout_ms=timeout_ms,
            )
        except Exception as _plan_err:
            logger.debug("_build_execution_plan failed (swallowed): %s", _plan_err)
            return None

    @staticmethod
    def _finalise_plan_lifecycle(plan, *, success: bool) -> None:
        """PR-12: Advance plan + step lifecycle to a terminal state after execution.

        Stamps ``succeeded`` or ``failed`` on the plan and all its steps
        based on the ``success`` flag.  Fail-soft — never interrupts the
        request path.

        Parameters
        ----------
        plan:
            The :class:`~core.schemas.execution_plan.ExecutionPlan` to
            update, or ``None`` (no-op).
        success:
            ``True`` if execution completed successfully; ``False``
            otherwise.
        """
        if plan is None:
            return
        try:
            from core.schemas.execution_lifecycle import (
                ExecutionLifecycleState as _ELS,
                LifecycleTransition as _LT,
                advance_lifecycle,
            )
            terminal = advance_lifecycle(
                _ELS(plan.lifecycle_state) if plan.lifecycle_state else _ELS.PLANNED,
                success=success,
            )
            plan_t = _LT.make(
                to_state=terminal,
                from_state=_ELS(plan.lifecycle_state) if plan.lifecycle_state else _ELS.PLANNED,
                reason="execution_completed" if success else "execution_failed",
            )
            plan.lifecycle_state = terminal.value
            if isinstance(plan.lifecycle_trail, list):
                plan.lifecycle_trail.append(plan_t)
            else:
                plan.lifecycle_trail = [plan_t]

            # Advance each step as well
            for step in (plan.steps or []):
                step_terminal = advance_lifecycle(
                    _ELS(step.lifecycle_state) if step.lifecycle_state else _ELS.CREATED,
                    success=success,
                )
                step_t = _LT.make(
                    to_state=step_terminal,
                    from_state=_ELS(step.lifecycle_state) if step.lifecycle_state else _ELS.CREATED,
                    reason="step_completed" if success else "step_failed",
                )
                step.lifecycle_state = step_terminal.value
                if isinstance(step.lifecycle_trail, list):
                    step.lifecycle_trail.append(step_t)
                else:
                    step.lifecycle_trail = [step_t]
        except Exception as _lc_err:
            logger.debug("_finalise_plan_lifecycle failed (swallowed): %s", _lc_err)

    @staticmethod
    def _summarise_execution_plan(plan) -> Optional[Dict[str, Any]]:
        """PR-11: Return a compact summary dict for *plan*, or ``None`` on failure.

        Uses :func:`~core.schemas.execution_plan.plan_summary` to produce a
        small, JSON-safe summary dict for embedding in response metadata and
        :class:`~core.unified_response.UnifiedChatResponse`.
        Swallows all errors so it never interrupts request processing.
        """
        if plan is None:
            return None
        try:
            from core.schemas.execution_plan import plan_summary as _ps
            return _ps(plan)
        except Exception as _sum_err:
            logger.debug("_summarise_execution_plan failed (swallowed): %s", _sum_err)
            return None

    def _select_multimodal_route(
        self,
        canonical_perception: Optional[Dict[str, Any]],
        source_registry_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """PR-20 / PR-27: Determine the native-multimodal-first routing decision.

        OpenClawd is the **routing authority**.  This method inspects
        ``canonical_perception`` (built by :meth:`_build_canonical_perception_state`)
        and decides which tier of the native-multimodal-first hierarchy to use:

        1. **native_multimodal** — perception warrants native MM *and* a
           native MM provider is available.  ``is_native_multimodal=True``.
        2. **partial_multimodal** — native MM warranted but native provider
           unavailable; route to any text-capable provider (caller feeds
           derived ``fusion_summary`` as input).
        3. **advisory** — no provider reachable at all; safe no-op.

        Text-only requests (``requires_native_multimodal=False``) return
        ``route_type="text_only"`` immediately without consulting the router.

        PR-27 augments this method with an explicit modality confidence and
        routing eligibility assessment.  When the confidence/readiness layer
        determines that the multimodal signal is too weak or degraded, the
        route degrades gracefully rather than blindly using the best-available
        native MM provider.

        The returned dict is embedded in :attr:`metadata` under the key
        ``"multimodal_route_decision"`` so that later PRs can project it to
        the diagnostics / status board.

        Parameters
        ----------
        canonical_perception:
            Serialised :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`
            dict as produced by :meth:`_build_canonical_perception_state`.
            May be ``None`` for text-only requests.
        source_registry_snapshot:
            Optional serialised snapshot from the runtime shell's
            :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`.
            When provided, source health and quality facts calibrate the
            modality confidence assessment (PR-27).

        Returns
        -------
        dict
            Keys:

            ``route_type``
                One of ``"native_multimodal"``, ``"partial_multimodal"``,
                ``"advisory"``, ``"text_only"``.
            ``is_native_multimodal``
                ``True`` when tier-1 native multimodal was selected.
            ``provider``
                Selected provider name, or ``"none"``.
            ``model``
                Selected model name, or ``"none"``.
            ``route_reason``
                Human-readable rationale for the selected tier.
            ``fallback_reason``
                Non-empty when a downgrade from tier-1 occurred.
            ``active_modalities``
                Modality list read from the perception state.
            ``perception_routing_readiness``
                Serialised :class:`~core.multimodal.modality_confidence_policy.PerceptionRoutingReadiness`
                dict (PR-27).  Always present; never raises.
        """
        # ── PR-27: Build modality confidence / routing readiness ─────────────
        _readiness: Optional[Dict[str, Any]] = None
        try:
            from core.multimodal.modality_confidence_policy import (
                build_perception_routing_readiness as _build_readiness,
            )
            _readiness_obj = _build_readiness(
                canonical_perception=canonical_perception,
                source_registry_snapshot=source_registry_snapshot,
            )
            _readiness = _readiness_obj.to_dict()
            _eligibility_eligible: bool = (
                _readiness_obj.eligibility.is_native_multimodal_eligible
            )
            _eligibility_summary: str = (
                _readiness_obj.eligibility.eligibility_summary
            )
            _eligibility_reason: str = (
                _readiness_obj.eligibility.primary_reason.value
            )
        except Exception as _pr27_err:
            logger.debug("build_perception_routing_readiness failed (swallowed): %s", _pr27_err)
            _readiness = None
            _eligibility_eligible = True  # Fail open: don't block routing if policy fails
            _eligibility_summary = "readiness_assessment_unavailable"
            _eligibility_reason = "unknown"

        # ── Read perception signals ──────────────────────────────────────────
        requires_native_mm: bool = False
        active_modalities: List[str] = []
        if canonical_perception:
            requires_native_mm = bool(
                canonical_perception.get("requires_native_multimodal", False)
            )
            active_modalities = list(
                canonical_perception.get("active_modalities") or []
            )

        # ── Text-only short-circuit ──────────────────────────────────────────
        if not requires_native_mm:
            result = {
                "route_type": "text_only",
                "is_native_multimodal": False,
                "provider": "none",
                "model": "none",
                "route_reason": "perception_state=text_only no_multimodal_input_detected",
                "fallback_reason": "",
                "active_modalities": active_modalities,
            }
            if _readiness is not None:
                result["perception_routing_readiness"] = _readiness
            return result

        # ── PR-27: Eligibility gate — degrade if confidence is too low ───────
        if not _eligibility_eligible and _readiness is not None:
            result = {
                "route_type": "text_only",
                "is_native_multimodal": False,
                "provider": "none",
                "model": "none",
                "route_reason": (
                    f"modality_confidence_ineligible "
                    f"reason={_eligibility_reason} "
                    f"summary={_eligibility_summary}"
                ),
                "fallback_reason": (
                    f"confidence_below_threshold reason={_eligibility_reason}"
                ),
                "active_modalities": active_modalities,
                "perception_routing_readiness": _readiness,
            }
            return result

        # ── Multimodal routing hierarchy ─────────────────────────────────────
        router = self._get_router()
        if router is None:
            result = {
                "route_type": "advisory",
                "is_native_multimodal": False,
                "provider": "none",
                "model": "none",
                "route_reason": "router_unavailable degraded_to=advisory",
                "fallback_reason": "router_unavailable",
                "active_modalities": active_modalities,
            }
            if _readiness is not None:
                result["perception_routing_readiness"] = _readiness
            return result

        try:
            from core.multi_llm_router import TaskType as _TaskType

            decision = router.route_multimodal_first(
                active_modalities=active_modalities,
                task_type=_TaskType.GENERAL,
                complexity_score=0.5,
            )
        except Exception as _rt_err:
            logger.debug("route_multimodal_first failed: %s", _rt_err)
            result = {
                "route_type": "advisory",
                "is_native_multimodal": False,
                "provider": "none",
                "model": "none",
                "route_reason": f"routing_error={_rt_err} degraded_to=advisory",
                "fallback_reason": str(_rt_err),
                "active_modalities": active_modalities,
            }
            if _readiness is not None:
                result["perception_routing_readiness"] = _readiness
            return result

        # Determine the tier from the decision reason prefix
        reason = decision.reason or ""
        if decision.provider == "none":
            result = {
                "route_type": "advisory",
                "is_native_multimodal": False,
                "provider": "none",
                "model": "none",
                "route_reason": reason,
                "fallback_reason": "no_providers_available",
                "active_modalities": active_modalities,
            }
            if _readiness is not None:
                result["perception_routing_readiness"] = _readiness
            return result

        is_tier1 = "tier=1" in reason
        if is_tier1:
            result = {
                "route_type": "native_multimodal",
                "is_native_multimodal": True,
                "provider": decision.provider,
                "model": decision.model,
                "route_reason": reason,
                "fallback_reason": "",
                "active_modalities": active_modalities,
            }
            if _readiness is not None:
                result["perception_routing_readiness"] = _readiness
            return result

        # Tier 2 — native multimodal unavailable; degrade to text-capable provider
        modality_str = "+".join(active_modalities) if active_modalities else "unknown"
        result = {
            "route_type": "partial_multimodal",
            "is_native_multimodal": False,
            "provider": decision.provider,
            "model": decision.model,
            "route_reason": reason,
            "fallback_reason": (
                f"native_multimodal_provider_unavailable "
                f"modalities=[{modality_str}] "
                f"degraded_to=text_capable_provider"
            ),
            "active_modalities": active_modalities,
        }
        if _readiness is not None:
            result["perception_routing_readiness"] = _readiness
        return result


    def _build_unified_control_plan(
        self,
        *,
        runtime_session_id: Optional[str] = None,
        trace_id: str = "",
        canonical_perception: Optional[Dict[str, Any]] = None,
        # PR-24: canonical model supply truth (PR-18) now forwarded into
        # the control plan so the unified artifact captures both perception
        # and model supply as authoritative inputs.
        canonical_model_supply: Optional[Dict[str, Any]] = None,
        continuum_state: Optional[Dict[str, Any]] = None,
        chosen_model: Optional[str] = None,
        chosen_provider: Optional[str] = None,
        is_native_multimodal: bool = False,
        execution_path: str = "local",
        delegation_point: Optional[str] = None,
        remote_execution_mode: Optional[str] = None,
        target_device_ids: Optional[List[str]] = None,
        orchestration_active: bool = False,
        fallback_level: str = "none",
        fallback_reason: Optional[str] = None,
        lifecycle_target: Optional[str] = None,
        execution_plan_summary: Optional[Dict[str, Any]] = None,
        diagnostics_summary: Optional[Dict[str, Any]] = None,
        # PR-21 — enriched execution decision
        execution_reason: Optional[str] = None,
        fallback_intent: Optional[str] = None,
        is_execution_downgrade: bool = False,
        preferred_execution_path: Optional[str] = None,
        # PR-21 — fallback governance record
        fallback_kinds: Optional[List[str]] = None,
        model_fallback_reason: Optional[str] = None,
        multimodal_downgrade_reason: Optional[str] = None,
        agent_to_command_reason: Optional[str] = None,
        remote_to_local_reason: Optional[str] = None,
        orchestration_downgrade_reason: Optional[str] = None,
        blocked_reason: Optional[str] = None,
        # PR-24 — canonical multimodal routing decision to embed in the plan
        multimodal_route_decision: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """PR-19 / PR-21 / PR-24: Build a canonical :class:`~core.schemas.unified_control_plan.UnifiedControlPlan` dict.

        OpenClawd is the **unified control core** — this method assembles the
        single canonical control artifact that captures perception truth, model
        supply truth, the chosen model and execution decisions, fallback intent,
        lifecycle target, diagnostics, and authority chain for this request.

        PR-21 enriches the plan with :class:`UnifiedExecutionDecision` (explicit
        execution rationale and downgrade tracking) and :class:`FallbackDecisionRecord`
        (canonical fallback/downgrade governance record).

        PR-24 wires ``canonical_model_supply`` (PR-18
        :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`)
        into the plan so the unified artifact is the single authoritative source
        for both perception and model-supply truth, eliminating the gap where
        model supply was built separately but not forwarded into the control plan.
        PR-24 also embeds the native multimodal routing decision directly into
        the plan via ``multimodal_route_decision``, eliminating the need for
        consumers to read the deprecated top-level ``multimodal_route_decision``
        metadata key, which is retained only for backward compatibility.

        The plan is additive and non-breaking: callers that do not read the
        ``unified_control_plan`` key in response metadata are unaffected.

        Returns:
            ``to_dict()`` output of the plan, or ``None`` on failure.
        """
        try:
            from core.schemas.unified_control_plan import build_unified_control_plan as _build_ucp

            _plan = _build_ucp(
                runtime_session_id=runtime_session_id,
                trace_id=trace_id,
                canonical_perception=canonical_perception,
                # PR-24: canonical model supply is now the authoritative supply
                # input to the control plan rather than being omitted.
                canonical_model_supply=canonical_model_supply,
                continuum_state=continuum_state,
                chosen_model=chosen_model,
                chosen_provider=chosen_provider,
                is_native_multimodal=is_native_multimodal,
                execution_path=execution_path,
                delegation_point=delegation_point,
                remote_execution_mode=remote_execution_mode,
                target_device_ids=target_device_ids or [],
                orchestration_active=orchestration_active,
                fallback_level=fallback_level,
                fallback_reason=fallback_reason,
                lifecycle_target=lifecycle_target,
                execution_plan_summary=execution_plan_summary,
                diagnostics_summary=diagnostics_summary,
                # PR-21
                execution_reason=execution_reason,
                fallback_intent=fallback_intent,
                is_execution_downgrade=is_execution_downgrade,
                preferred_execution_path=preferred_execution_path,
                fallback_kinds=fallback_kinds,
                model_fallback_reason=model_fallback_reason,
                multimodal_downgrade_reason=multimodal_downgrade_reason,
                agent_to_command_reason=agent_to_command_reason,
                remote_to_local_reason=remote_to_local_reason,
                orchestration_downgrade_reason=orchestration_downgrade_reason,
                blocked_reason=blocked_reason,
                # PR-24: embed routing decision in the canonical plan
                multimodal_route_decision=multimodal_route_decision,
            )
            return _plan.to_dict()
        except Exception as _ucp_err:
            logger.debug("_build_unified_control_plan failed (swallowed): %s", _ucp_err)
            return None

    @staticmethod
    def _determine_execution_path(
        entry_mode: str,
        execution_result: Dict[str, Any],
        cross_device_dispatched: bool = False,
    ) -> str:
        """Resolve the liminal execution branch taken by this request.

        This is OpenClawd's **decision core** output — it names which
        delegation point was activated for this request:

        - ``"local"``        — **local manifestation** delegation was taken:
                               execution confined to this Windows device via
                               System API (``DecisionExecutor``,
                               ``WindowsExecutionArbiter``).
        - ``"cross_device"`` — **single remote delegation** was taken:
                               execution expanded to a remote device via the
                               cross-device substrate (CommandRouter →
                               gateway).  This is a liminal domain expansion,
                               not a parallel system.
        - ``"hybrid"``       — both local and single-remote delegation ran
                               concurrently.
        - ``"none"``         — **no-op path**: subject responded without
                               acting (observe / hint action level, or no
                               suitable delegation target).

        Note: the ``"cross_device"`` label covers both single-remote
        delegation (*one* target device) and multi-device orchestration
        delegation (*many* devices via ``_dispatch_parallel_goal``).
        The ``delegation_point`` key in response metadata provides the
        finer-grained label when needed.

        The value is echoed in ``response.metadata.execution_path`` and
        ``response.metadata.runtime_domain`` so the runtime shell can log
        it against ``runtime_session_id`` for observability.

        Parameters
        ----------
        entry_mode:
            Normalised mode string (``"local"`` | ``"cross_device"`` |
            ``"hybrid"``).
        execution_result:
            Serialised dict returned by :meth:`_run_execution`.
        cross_device_dispatched:
            ``True`` when the request was forwarded to a remote device (i.e.
            ``metadata.remote_dispatch`` was set by the handler).

        Returns
        -------
        str
            One of ``"local"``, ``"cross_device"``, ``"hybrid"``, or ``"none"``.
        """
        action_taken = execution_result.get("action_taken", "none")
        local_executed = action_taken not in ("none", "noop", "error")

        if local_executed and cross_device_dispatched:
            return "hybrid"
        if cross_device_dispatched or entry_mode == "cross_device":
            return "cross_device"
        if entry_mode == "hybrid":
            return "hybrid"
        if local_executed:
            return "local"
        return "none"

    # ========================================================================
    # 主入口
    # ========================================================================

    async def process(
        self,
        message: str,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[List[Dict]] = None,
        required_capabilities: Optional[List[str]] = None,
        multimodal_context: Optional[Any] = None,
        runtime_session_id: Optional[str] = None,
        entry_mode: Optional[str] = None,
    ) -> dict:
        """Subject core entry point — invoked by DesktopPresenceRuntime during the LIMINAL phase.

        This method implements the four-stage subject core flow:

        1. **Ingest** — attach ``runtime_session_id`` as trace ID; fuse any
           request-bound ``multimodal_context`` via ``MultimodalBus.ingest``.
        2. **Liminal / Continuum** — ``ContinuumOrchestrator.run()`` evaluates
           intent, ``tri_state_phase``, ``runtime_domain``, and produces the
           ``state_continuum`` dict.
        3. **Branch** — ``_determine_execution_path()`` resolves which liminal
           execution loop to activate.
        4. **Manifest** — ``DecisionExecutor`` (local) and/or ``CommandRouter``
           (cross-device) execute the action; results are merged.

        This method is the **subject core** entry point.  It should always be
        invoked through :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
        (which provides the ``runtime_session_id`` and drives the outer tri-state
        lifecycle).  Direct callers that bypass the runtime shell lose session
        correlation and tri-state observability.

        Args:
            message: 用户输入的自然语言消息
            device_id: 设备 ID (可选，用于设备操控场景)
            session_id: 会话 ID (可选，用于上下文管理)
            context: 对话历史上下文（可选）
            required_capabilities: Phase 2 scheduler hint — list of device
                capabilities required.
            multimodal_context: Request-bound multi-modal payload bundle.
                Fused here via ``MultimodalBus.ingest``.  Distinct from the
                continuous ``PerceptionFrame`` stream owned by the runtime shell.
            runtime_session_id: Correlation ID propagated from
                :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
                Used as ``trace_id`` so all log entries within this request
                can be correlated back to the originating runtime session.
                Also echoed in ``response.metadata.runtime_session_id``.
            entry_mode: Execution mode from the shell
                (``"local"`` | ``"cross_device"`` | ``"hybrid"``).  Determines
                which liminal execution branch is activated.  Defaults to
                ``"local"`` for backward compatibility.

        Returns:
            统一响应 dict::

                {
                    "success": bool,
                    "response": str,
                    "intent": str,
                    "metadata": {
                        "session_id": str,
                        "mode": str,
                        "execution_path": str,     # local/cross_device/hybrid/none
                        "runtime_domain": str,     # from state_continuum
                        "state_continuum": dict,   # full continuum posture
                        "runtime_session_id": str, # echoed from shell
                        ...
                    },
                }
        """
        self._ensure_initialized()
        self._request_count += 1
        t0 = time.monotonic()
        request_id = uuid.uuid4().hex
        # trace_id is the stable end-to-end identifier for this request.
        # When a runtime_session_id is provided (routed through
        # DesktopPresenceRuntime) it is used as the trace_id so that every
        # downstream log entry carries the same correlation key.
        trace_id = runtime_session_id if runtime_session_id else request_id
        if runtime_session_id:
            logger.debug(
                "OpenClawd.process invoked via DesktopPresenceRuntime | runtime_session_id=%s",
                runtime_session_id,
            )

        # PR-1 EntryMode: normalise and log the resolved execution mode.
        # When not provided, fall back to "local" to maintain backward compat.
        _entry_mode: str = entry_mode or "local"
        logger.debug(
            "OpenClawd.process | entry_mode=%s trace_id=%s",
            _entry_mode,
            trace_id,
        )

        # PR-1 Block-1: stamp entry metadata via EntrypointRouter for observability.
        # This is a best-effort, non-blocking call; failures never affect the request.
        try:
            from core.unified.entrypoint_router import get_entrypoint_router as _get_er
            _get_er()._emit_routing_event({
                "entry_path": "canonical",
                "via_legacy_adapter": False,
                "source": "openclawd.process",
                "trace_id": trace_id,
                "routed_at": t0,
            })
        except Exception:
            pass

        # PR-8: store trace/session on self so _dispatch_tool_call can read them.
        self._current_trace_id = trace_id
        self._current_session_id = session_id
        self._current_device_id = device_id or ""

        # PR-001: Sync dispatcher context so per-call dispatch() calls inherit
        # the current request's device/session/trace without needing explicit kwargs.
        _dispatcher = getattr(self, "_capability_dispatcher", None)
        if _dispatcher is not None:
            _dispatcher.device_id = self._current_device_id
            _dispatcher.session_id = session_id or ""
            _dispatcher.trace_id = trace_id or ""

        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        # ── Multimodal Perception Bus (PR 1) ─────────────────────────────────
        # Run MultimodalBus.ingest() for every request (text-only requests
        # produce an empty fusion_summary and leave the message unchanged).
        # Base64 payloads are never stored in _mm_context_dict.
        _mm_context_dict: Optional[Dict[str, Any]] = None
        _fusion_suffix: str = ""
        try:
            from core.perception.multimodal_bus import MultimodalBus as _MMBus

            _bus = _MMBus()
            _mm_context_dict = _bus.ingest(
                message=message,
                multimodal_context=multimodal_context,
                device_metadata={"device_id": device_id, "session_id": session_id},
            )
            _fusion_suffix = _mm_context_dict.get("fusion_summary") or ""
        except Exception as _bus_err:  # broad catch: bus must never crash the main request flow
            logger.debug("MultimodalBus.ingest failed: %s", _bus_err)
            # Graceful fallback: serialise raw context if available
            if multimodal_context is not None:
                try:
                    _mm_context_dict = multimodal_context.model_dump()
                except Exception:  # model_dump may raise AttributeError / ValidationError
                    pass

        # ── PR-16: Canonical Perception State ─────────────────────────────────
        # Build the unified canonical perception truth that OpenClawd uses as
        # its primary perception input contract.  Combines continuous host
        # perception (runtime shell) and request-bound multimodal context.
        # Always succeeds — text-only requests receive a valid state.
        _canonical_perception: Optional[Dict[str, Any]] = self._build_canonical_perception_state(
            runtime_session_id=runtime_session_id,
            trace_id=trace_id,
            multimodal_context=multimodal_context,
            fused_context=_mm_context_dict,
        )

        # ── PR-24: Canonical Model Supply State ───────────────────────────────
        # Build the canonical model supply truth (PR-18) once per request and
        # forward it into the unified control plan so the plan becomes the
        # single authoritative source for both perception and model supply.
        # Previously, CanonicalModelSupplyState was built by PR-18 but not
        # wired into the control plan — this closes that gap.
        # Gracefully returns None when the router is unavailable.
        _canonical_model_supply: Optional[Dict[str, Any]] = self._build_canonical_model_supply_state()

        # ── PR-20: Native Multimodal-First Routing Decision ───────────────────
        # OpenClawd is the routing authority.  Determine the preferred route
        # tier (native_multimodal → partial_multimodal → advisory) based on
        # the canonical perception state.  This decision is recorded in every
        # response for diagnostics and future projection.
        _multimodal_route: Dict[str, Any] = self._select_multimodal_route(
            canonical_perception=_canonical_perception,
        )
        _is_native_multimodal: bool = _multimodal_route.get("is_native_multimodal", False)

        # ── PR-515 / GAP-512-009: Critical Path Harness — route-selection record ──
        # Record the routing decision in the canonical CriticalPathHarness layer
        # so that multi-model routing path is inspectable through operator surfaces,
        # not only through ContinuumState / TopologyRoutePlan projections.
        # Per HARNESS_NON_BLOCKING_POLICY, this block never aborts the primary path.
        try:
            from core.critical_path_harness import (
                record_route_selection as _harness_record_route,
                record_provider_switch as _harness_record_switch,
            )
            _harness_record_route(
                trace_id=trace_id or "",
                route_type=_multimodal_route.get("route_type", ""),
                provider=_multimodal_route.get("provider", ""),
                model=_multimodal_route.get("model", ""),
                route_reason=_multimodal_route.get("route_reason", ""),
                fallback_reason=_multimodal_route.get("fallback_reason", ""),
                active_modalities=list(_multimodal_route.get("active_modalities") or []),
                source="OpenClawd._select_multimodal_route",
            )
            _harness_provider = _multimodal_route.get("provider", "")
            _harness_model = _multimodal_route.get("model", "")
            _harness_fallback_reason = _multimodal_route.get("fallback_reason", "")
            if _harness_provider and _harness_provider != "none":
                _harness_record_switch(
                    trace_id=trace_id or "",
                    from_provider="none",
                    to_provider=_harness_provider,
                    to_model=_harness_model,
                    switch_reason=_harness_fallback_reason or "initial_selection",
                    is_fallback=bool(_harness_fallback_reason),
                    source="OpenClawd._select_multimodal_route",
                )
        except Exception as _hp_exc:
            logger.debug(
                "PR-515 harness route-selection record skipped: %s", _hp_exc
            )

        # ── PR-41: Routing Observability ──────────────────────────────────────
        # Emit a structured RoutingDecisionEvent from the canonical routing
        # decision.  This is the primary integration point for route/fallback
        # observability — events are derived from the canonical decision, not
        # inferred afterward from logs or metadata.
        _routing_decision_event: Optional[Dict[str, Any]] = self._emit_routing_decision_event(
            route_dict=_multimodal_route,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

        # ── PR-29: Degraded Operation Envelope ───────────────────────────────
        # Build the canonical degraded-operation envelope from the routing
        # decision.  This normalises provider failover and multimodal
        # degradation into an explicit, serialisable artifact so that
        # projection and diagnostics layers consume it without inventing their
        # own degradation semantics.
        _degraded_operation_envelope: Optional[Dict[str, Any]] = (
            self._build_degraded_operation_envelope(
                route_dict=_multimodal_route,
                supply_snapshot=_canonical_model_supply,
                trace_id=trace_id,
            )
        )

        # ── PR-30: Control-Loop Latency Budget ────────────────────────────────
        # Apply explicit latency-budget awareness: ingest cadence, control-plan
        # recompute throttling, projection refresh budgeting, provider-selection
        # latency, and text-only fast-path detection.  The resulting summary is
        # embedded in response metadata for structured latency accounting.
        # OpenClawd retains full authority over all decisions; this block only
        # shapes cadence and recomputation, never correctness.
        _latency_budget_summary: Optional[Dict[str, Any]] = self._apply_latency_budget(
            multimodal_context=multimodal_context,
            canonical_perception=_canonical_perception,
            multimodal_route=_multimodal_route,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id or "",
        )

        # ── PR-32: Permission / Trust / Safety Snapshot ───────────────────
        # Build the canonical permission visibility, trust-surface, and
        # control-safety snapshot for this control-loop iteration.  This
        # aggregates source registry health → permission status, routing
        # degradation → trust label, and execution plan → risk tier into one
        # authoritative artifact that projection and diagnostics layers consume
        # without inventing separate trust semantics.
        # Note: source_registry_snapshot is omitted here because the registry
        # is shell-owned (DesktopPresenceRuntime) and is not directly accessible
        # from OpenClawd.  The shell's permission_safety_summary() method builds
        # a supplementary snapshot with full registry data when needed.
        _permission_safety_state: Optional[Dict[str, Any]] = (
            self._build_permission_safety_state(
                source_registry_snapshot=None,  # registry is shell-owned; shell embeds it
                multimodal_route=_multimodal_route,
                execution_plan=None,  # plan not yet built at this stage
                degraded_operation_envelope=_degraded_operation_envelope,
                canonical_perception=_canonical_perception,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id or "",
            )
        )

        # ── PR-33: Operator Override Panel ────────────────────────────────────
        # Apply canonical operator overrides for source, model, and execution
        # policy.  This reads the active OperatorOverrideSet from the singleton
        # (committed by the runtime shell) and applies it to the multimodal route,
        # execution policy, and source selection inputs.  The resulting snapshot
        # is embedded in response metadata so projection and diagnostics layers
        # can surface operator-influenced decisions.
        # Note: _multimodal_route may be mutated in-place by this call when a
        # multimodal_mode override is active.  Downstream consumers should read
        # the route dict *after* this call to observe override effects.
        _operator_override_state: Optional[Dict[str, Any]] = (
            self._apply_operator_overrides(
                multimodal_route=_multimodal_route,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id or "",
            )
        )
        # Re-read is_native_multimodal after potential override mutation
        _is_native_multimodal = _multimodal_route.get("is_native_multimodal", False)

        # ── PR-34: Decision Timeline and Explainability Traces ────────────────
        # Record canonical decision events from the routing, override, and
        # safety state produced above into the process-wide timeline singleton,
        # then capture an ExplainabilitySnapshot for this iteration.  All
        # explanations derive from canonical artifacts — not from log text.
        _decision_timeline_snapshot: Optional[Dict[str, Any]] = (
            self._build_decision_timeline_snapshot(
                route_dict=_multimodal_route,
                degraded_operation_envelope=_degraded_operation_envelope,
                permission_safety_state=_permission_safety_state,
                operator_override_state=_operator_override_state,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id or "",
            )
        )

        # ── Scene Interpreter (PR 2) ──────────────────────────────────────
        # Run SceneInterpreter after perception fusion to select an
        # InteractionMode and produce UI/voice/avatar hints.  This is purely
        # additive: failures are logged and silently suppressed so that existing
        # text-only paths continue to work exactly as before.
        _interaction_dict: Optional[Dict[str, Any]] = None
        _interaction_mode_str: Optional[str] = None
        _decision = None
        try:
            from core.interaction.scene_interpreter import SceneInterpreter as _SceneInterpreter

            _interpreter = _SceneInterpreter()
            _decision = _interpreter.interpret(
                message=message,
                fused_context=_mm_context_dict,
                device_metadata={"device_id": device_id, "session_id": session_id},
                session_id=session_id,
            )
            _interaction_dict = _decision.to_dict()
            _interaction_mode_str = _decision.mode.value
        except Exception as _interp_err:
            logger.debug("SceneInterpreter.interpret failed: %s", _interp_err)

        # ── Persona / Spirit Engine (PR-3) ────────────────────────────────────
        # Retrieve current PersonaState for this session *before* processing.
        # We update it *after* the response is ready (see below).  On any
        # failure the persona block is silently skipped — text-only callers
        # see response.response unchanged.
        _persona_state_dict: Optional[Dict[str, Any]] = None
        try:
            from core.persona.state_store import get_state_store as _get_store
            _persona_store = _get_store()
            _pre_persona = _persona_store.get_state(session_id)
            _persona_state_dict = _pre_persona.to_dict()
        except Exception as _persona_pre_err:
            logger.debug("PersonaState pre-fetch failed: %s", _persona_pre_err)

        try:
            from core.task_logger import emit_task_log
            emit_task_log(
                "task_received",
                trace_id=trace_id,
                session_id=session_id,
                device_id=device_id,
                status="received",
            )
        except Exception:
            pass

        # ── Audit ledger: TASK_CREATED ────────────────────────────────────────
        task_id_for_trace = f"task_{uuid.uuid4().hex[:12]}"
        try:
            from core.control_plane.audit_ledger import EventType as _EvType
            self._emit_audit(
                _EvType.TASK_CREATED,
                trace_id=trace_id,
                task_id=task_id_for_trace,
                session_id=session_id,
                device_id=device_id,
                message="Intent received",
                payload={"message_preview": message[:120]},
            )
        except Exception:
            pass

        # 同步新设备能力（确保 OpenClawd 始终感知最新设备）
        try:
            self.sync_device_capabilities()
        except Exception:
            pass

        try:
            # ── Audit ledger: TASK_STARTED ────────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType2
                self._emit_audit(
                    _EvType2.TASK_STARTED,
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    message="Processing started",
                )
            except Exception:
                pass

            # Step 1: 通过内嵌 AgentKernel 进行认知/规划（OpenClawd 持有并调用 Kernel）
            # AgentKernel 作为认知层返回 KernelResponse（认知产物），
            # OpenClawd 负责解释该产物并决定后续执行/委托策略。
            kernel = self._get_kernel()
            if kernel is not None:
                try:
                    kernel_result = await kernel.handle_message(
                        message=message,
                        session_id=session_id,
                        device_id=device_id or "",
                        context=context or [],
                    )
                    api_dict = kernel_result.to_api_dict()
                    mode = kernel_result.mode
                    # 记录路由决策日志
                    router = self._get_router()
                    provider_info = {}
                    if router:
                        try:
                            provider_info = {
                                "provider": getattr(router, "_last_provider", ""),
                                "model": kernel_result.model or router.get_default_model(),
                                "available_providers": [
                                    p for p in getattr(router, "providers", {}).keys()
                                ],
                            }
                        except Exception:
                            pass
                    logger.info(
                        "OpenClawd request | request_id=%s session=%s mode=%s "
                        "provider=%s model=%s",
                        request_id,
                        session_id,
                        mode,
                        provider_info.get("provider", ""),
                        provider_info.get("model", ""),
                    )
                    # PR-2: Log primary decision authority (kernel path).
                    try:
                        from core.model_role_policy import get_policy as _get_policy_k
                        _get_policy_k().log_primary_authority(
                            "openclawd",
                            trace_id=trace_id,
                            model=kernel_result.model or provider_info.get("model", ""),
                            intent=kernel_result.intent.raw_intent if kernel_result.intent else "",
                        )
                    except Exception as _rp_k_err:
                        logger.debug("model_role_policy log (kernel) skipped: %s", _rp_k_err)
                    latency_ms = (time.monotonic() - t0) * 1000
                    await self._record_turn(session_id, "user", message)
                    await self._record_turn(session_id, "assistant", kernel_result.reply)
                    # ── Audit ledger: TASK_COMPLETED ──────────────────────────
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvType3
                        _ev = _EvType3.TASK_COMPLETED if kernel_result.success else _EvType3.TASK_FAILED
                        self._emit_audit(
                            _ev,
                            trace_id=trace_id,
                            task_id=task_id_for_trace,
                            session_id=session_id,
                            device_id=device_id,
                            message="AgentKernel completed",
                            payload={"latency_ms": round(latency_ms, 1), "handler": "agent_kernel"},
                        )
                    except Exception:
                        pass
                    # ── Persona / Spirit Engine update (PR-3) ─────────────────
                    try:
                        from core.persona.state_store import get_state_store as _get_store2
                        _ps, _delta = _get_store2().update_state(
                            session_id,
                            message=message,
                            interaction_mode=_interaction_mode_str,
                            task_success=kernel_result.success,
                        )
                        _persona_state_dict = _ps.to_dict()
                    except Exception as _pe:
                        logger.debug("PersonaState update (kernel path) failed: %s", _pe)
                    # ── InteractionEnvelope (PR-4) ────────────────────────────
                    _interaction_envelope_dict: Optional[Dict[str, Any]] = None
                    try:
                        from core.interaction.interaction_builder import InteractionBuilder as _IBuilder
                        _envelope = _IBuilder().build(
                            trace_id=trace_id,
                            session_id=session_id,
                            scene_decision=_decision,
                            persona_state=_persona_state_dict,
                            fused_context=_mm_context_dict,
                        )
                        _interaction_envelope_dict = _envelope.to_dict()
                    except Exception as _ie:
                        logger.debug("InteractionEnvelope build (kernel path) failed: %s", _ie)
                    # ── Output Orchestrator (PR-6) ────────────────────────────
                    _output_plan_dict: Optional[Dict[str, Any]] = None
                    try:
                        from core.output.orchestrator import OutputOrchestrator as _OOrch
                        _output_plan_dict = _OOrch().orchestrate(
                            interaction_envelope=_interaction_envelope_dict,
                            persona_state=_persona_state_dict,
                            response_text=kernel_result.reply,
                        )
                    except Exception as _op:
                        logger.debug("OutputOrchestrator (kernel path) failed: %s", _op)
                    # ── State Continuum (PR-5) ────────────────────────────────
                    _continuum_state_dict: Optional[Dict[str, Any]] = self._run_continuum(
                        trace_id=trace_id,
                        multimodal_context=multimodal_context,
                        runtime_session_id=runtime_session_id,
                    )
                    # ── Decision Execution (PR-8 / PR-4) ─────────────────────
                    _exec_result_k = self._run_execution(_continuum_state_dict, entry_mode=_entry_mode)
                    _exec_path_k = self._determine_execution_path(
                        entry_mode=_entry_mode,
                        execution_result=_exec_result_k,
                    )
                    # PR-4: structured observability log whenever execution_path is set.
                    logger.info(
                        "OpenClawd manifest | trace_id=%s entry_mode=%s execution_path=%s",
                        trace_id, _entry_mode, _exec_path_k,
                    )
                    if _exec_path_k == "none":
                        _exec_result_k.setdefault("skipped_reason", "no_execution")
                    # PR-11: build canonical execution plan (additive, non-breaking)
                    _plan_k = self._build_execution_plan(
                        execution_path=_exec_path_k,
                        delegation_point="local",
                        trace_id=trace_id,
                        session_id=session_id,
                        device_id=device_id,
                    )
                    # PR-12: advance plan lifecycle to terminal state
                    self._finalise_plan_lifecycle(_plan_k, success=kernel_result.success)
                    # PR-006: log delegation_hint advisory treatment so it is
                    # observable in logs without affecting execution logic.
                    # OpenClawd is the final decision authority; the hint is
                    # never automatically promoted to a binding directive.
                    if kernel_result.delegation_hint is not None:
                        logger.info(
                            "OpenClawd delegation_hint advisory | trace_id=%s "
                            "hint=%r decision=advisory_noted (OpenClawd retains authority)",
                            trace_id,
                            kernel_result.delegation_hint,
                        )
                    else:
                        logger.debug(
                            "OpenClawd delegation_hint advisory | trace_id=%s "
                            "hint=None decision=advisory_none",
                            trace_id,
                        )
                    # PR-19: build canonical unified control plan (additive, non-breaking)
                    _ucp_k = self._build_unified_control_plan(
                        runtime_session_id=runtime_session_id,
                        trace_id=trace_id,
                        canonical_perception=_canonical_perception,
                        # PR-24: wire canonical model supply into the unified control plan
                        canonical_model_supply=_canonical_model_supply,
                        continuum_state=_continuum_state_dict,
                        chosen_model=kernel_result.model if kernel_result else None,
                        chosen_provider=provider_info.get("provider") if provider_info else None,
                        is_native_multimodal=_is_native_multimodal,
                        execution_path=_exec_path_k,
                        delegation_point="local",
                        lifecycle_target=_plan_k.lifecycle_state if _plan_k else None,
                        execution_plan_summary=self._summarise_execution_plan(_plan_k),
                        # PR-24: embed canonical routing decision in the plan
                        multimodal_route_decision=_multimodal_route,
                    )
                    return {
                        "success": kernel_result.success,
                        "response": kernel_result.reply,
                        "intent": kernel_result.intent.raw_intent,
                        "error": kernel_result.error,
                        "trace_id": trace_id,
                        "runtime_session_id": runtime_session_id or trace_id,
                        "execution_path": _exec_path_k,
                        "execution_result": _exec_result_k,
                        # PR-11: canonical execution plan (may be None if schema unavailable)
                        "execution_plan": _plan_k.to_dict() if _plan_k else None,
                        "interaction": _interaction_dict,
                        "persona_state": _persona_state_dict,
                        "interaction_envelope": _interaction_envelope_dict,
                        "output_plan": _output_plan_dict,
                        "state_continuum": _continuum_state_dict,
                        "metadata": {
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "runtime_session_id": runtime_session_id or trace_id,
                            "session_id": session_id,
                            "device_id": device_id,
                            "latency_ms": round(latency_ms, 1),
                            "confidence": kernel_result.intent.confidence,
                            "mode": mode,
                            "model": kernel_result.model,
                            "handler": "agent_kernel",
                            "entry_mode": _entry_mode,
                            "execution_path": _exec_path_k,
                            # PR-1: authority_role stamps OpenClawd as subject decision
                            # authority in the kernel path, consistent with the
                            # direct-path (non-kernel) response for full observability.
                            "authority_role": "subject_decision_authority",
                            # PR-3: delegation_point names which boundary was used.
                            # AgentKernel is embedded in OpenClawd → always local.
                            "delegation_point": "local",
                            # PR-4: kernel_cognition_role makes the architectural
                            # boundary explicit — AgentKernel is the embedded
                            # cognition/planning layer; OpenClawd is the decision
                            # authority that interprets the KernelResponse artifact.
                            "kernel_cognition_role": "embedded_cognition_layer",
                            # PR-4: delegation_hint from KernelResponse lets the
                            # kernel suggest a delegation path; OpenClawd decides
                            # whether to adopt it.
                            "kernel_delegation_hint": kernel_result.delegation_hint,
                            # PR-006: delegation_hint_decision records how OpenClawd
                            # treated the kernel's advisory hint.  The hint is NEVER
                            # automatically promoted to a binding directive; OpenClawd
                            # always retains final decision authority.
                            # "advisory_noted" — hint was present and logged (advisory only).
                            # "advisory_none"  — no hint was provided by the kernel.
                            "delegation_hint_decision": (
                                "advisory_noted"
                                if kernel_result.delegation_hint is not None
                                else "advisory_none"
                            ),
                            # PR-006: soul_injection_phase from KernelResponse confirms
                            # which execution phase (if any) loaded SOUL policy.
                            # None means chat_only path; SOUL was never touched.
                            "soul_injection_phase": kernel_result.soul_injection_phase,
                            # PR-006: routing_authority from KernelResponse confirms
                            # that any routing suggestion from AgentKernel is advisory;
                            # final multi-model routing authority belongs to OpenClawd.
                            "kernel_routing_authority": kernel_result.routing_authority,
                            # PR-11: compact execution plan summary for diagnostics
                            "execution_plan_summary": self._summarise_execution_plan(_plan_k),
                            # PR-12: plan-level lifecycle state for observability
                            "execution_lifecycle_state": _plan_k.lifecycle_state if _plan_k else None,
                            **provider_info,
                            "agent_steps": api_dict["agent_steps"],
                            "tool_calls": api_dict["tool_calls"],
                            "task_result": api_dict["task_result"],
                            # PR-24 DEPRECATED-COMPAT: raw fused multimodal context
                            # from MultimodalBus.ingest().  New consumers should prefer
                            # ``canonical_perception_state`` (PR-16) as the authoritative
                            # perception source.  Retained only for backward compatibility;
                            # do not add new consumers of this key.
                            "multimodal_context": _mm_context_dict,
                            # PR-16: canonical perception state (primary perception contract)
                            "canonical_perception_state": _canonical_perception,
                            # PR-24: canonical model supply state (primary model supply
                            # contract, PR-18) — now forwarded from the unified control
                            # plan so the response carries the full canonical state chain.
                            "canonical_model_supply_state": _canonical_model_supply,
                            # PR-19: canonical unified control plan
                            "unified_control_plan": _ucp_k,
                            # PR-24 DEPRECATED-COMPAT: top-level routing decision dict.
                            # The canonical routing decision is now embedded inside
                            # unified_control_plan["multimodal_route_decision"].
                            # This key is retained only for backward compatibility.
                            "multimodal_route_decision": _multimodal_route,
                            # PR-41: structured routing observability event derived
                            # from the canonical routing decision (not inferred).
                            "routing_decision_event": _routing_decision_event,
                            # PR-29: canonical degraded-operation envelope (provider
                            # failover chain, fallback policy ladder, severity).
                            "degraded_operation_envelope": _degraded_operation_envelope,
                            # PR-30: control-loop latency budget summary (ingest cadence,
                            # recompute throttling, projection refresh, fast-path).
                            "latency_budget_summary": _latency_budget_summary,
                            # PR-32: canonical permission/trust/safety snapshot
                            # (permission visibility, trust labels, safety gating).
                            "permission_safety_state": _permission_safety_state,
                            # PR-33: canonical operator override snapshot
                            # (active source/model/execution-policy overrides).
                            "operator_override_state": _operator_override_state,
                            # PR-34: canonical decision timeline / explainability snapshot
                            # (route selection, fallback transitions, operator override
                            # influence, trust/safety gating — all correlated and replayable).
                            "decision_timeline_snapshot": _decision_timeline_snapshot,
                            # PR-36: production baseline status — confirms that the unified
                            # canonical control loop is active as the production baseline
                            # and reports coverage of canonical primary artifacts.
                            "production_baseline_summary": self._build_production_baseline_summary(
                                response_metadata={
                                    "canonical_perception_state": _canonical_perception,
                                    "canonical_model_supply_state": _canonical_model_supply,
                                    "unified_control_plan": _ucp_k,
                                    "degraded_operation_envelope": _degraded_operation_envelope,
                                    "latency_budget_summary": _latency_budget_summary,
                                    "permission_safety_state": _permission_safety_state,
                                    "operator_override_state": _operator_override_state,
                                    "decision_timeline_snapshot": _decision_timeline_snapshot,
                                }
                            ),
                            # PR-8: mainline convergence stamp — records that this
                            # response traversed the canonical OpenClawd authority
                            # stage, making the mainline path explicit and traceable.
                            "mainline_convergence": self._build_mainline_convergence_stamp(
                                trace_id=trace_id,
                                session_id=session_id,
                                task_id=task_id_for_trace,
                                execution_path=_exec_path_k,
                            ),
                        },
                        # PR-14: additive introspection hints (non-breaking)
                        "arch_layer_id": "subject_core",
                        "introspection_snapshot": {
                            "authority_role": "subject_decision_authority",
                            "delegation_point": "local",
                            "execution_mode": None,
                            "execution_path": _exec_path_k,
                            "lifecycle_state": _plan_k.lifecycle_state if _plan_k else None,
                            "execution_plan_summary": self._summarise_execution_plan(_plan_k),
                            "device_id": device_id,
                            "trace_id": trace_id,
                            "success": kernel_result.success,
                        },
                    }
                except Exception as e:
                    logger.warning("AgentKernel 处理异常，降级到 OpenClawd 直接处理: %s", e)

            # Step 2: AgentKernel 不可用时，OpenClawd 直接处理
            # Step 2a: 意图解析
            parsed_intent = await self._parse_intent(message, session_id)

            # Step 2b: 记录用户消息到会话记忆
            await self._record_turn(session_id, "user", message)

            # Step 2c: 根据意图路由到对应处理器
            intent_type = parsed_intent.intent if parsed_intent else "chat"
            handler_name = self._INTENT_HANDLER_MAP.get(intent_type, "_dispatch_chat")
            if not hasattr(self, handler_name):
                logger.warning(f"Handler {handler_name} not found, falling back to chat")
                handler_name = "_dispatch_chat"
            handler = getattr(self, handler_name)

            # Phase 2: if no device_id provided but required_capabilities given, auto-select
            effective_device_id = device_id
            if not effective_device_id and required_capabilities and intent_type in ("device_control", "task_manage"):
                selected = self._select_device_via_scheduler(required_capabilities)
                if selected:
                    logger.info(
                        "process: scheduler auto-selected device=%s for caps=%s",
                        selected, required_capabilities,
                    )
                    effective_device_id = selected

            result = await handler(
                message=f"{message}\n{_fusion_suffix}" if _fusion_suffix else message,
                intent=parsed_intent,
                device_id=effective_device_id,
                session_id=session_id,
                trace_id=trace_id,
            )

            # Step 2d: 记录路由决策
            router = self._get_router()
            provider_info = {}
            if router:
                try:
                    provider_info = {
                        "provider": getattr(router, "_last_provider", ""),
                        "model": router.get_default_model(),
                    }
                except Exception:
                    pass
            logger.info(
                "OpenClawd request | request_id=%s session=%s intent=%s "
                "provider=%s model=%s",
                request_id,
                session_id,
                intent_type,
                provider_info.get("provider", ""),
                provider_info.get("model", ""),
            )

            # PR-2: Log primary decision authority so observability confirms
            # that OpenClawd is the sole decision maker for this request.
            try:
                from core.model_role_policy import get_policy as _get_policy
                _get_policy().log_primary_authority(
                    "openclawd",
                    trace_id=trace_id,
                    model=provider_info.get("model", ""),
                    intent=intent_type,
                )
            except Exception as _rp_err:
                logger.debug("model_role_policy log skipped: %s", _rp_err)

            # Step 2e: 记录助手回复到会话记忆
            response_text = result.get("response", "")
            await self._record_turn(session_id, "assistant", response_text)

            latency_ms = (time.monotonic() - t0) * 1000

            # ── Audit ledger: TASK_COMPLETED ──────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType4
                _success_flag = result.get("success", True)
                self._emit_audit(
                    _EvType4.TASK_COMPLETED if _success_flag else _EvType4.TASK_FAILED,
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    message="Handler completed",
                    payload={"latency_ms": round(latency_ms, 1), "handler": handler_name, "intent": intent_type},
                )
            except Exception:
                pass

            # ── Persona / Spirit Engine update (PR-3) ─────────────────────────
            try:
                from core.persona.state_store import get_state_store as _get_store3
                _success_flag2 = result.get("success", True)
                _ps2, _delta2 = _get_store3().update_state(
                    session_id,
                    message=message,
                    interaction_mode=_interaction_mode_str,
                    task_success=_success_flag2,
                )
                _persona_state_dict = _ps2.to_dict()
            except Exception as _pe2:
                logger.debug("PersonaState update (direct path) failed: %s", _pe2)

            # ── InteractionEnvelope (PR-4) ────────────────────────────────────
            _interaction_envelope_dict2: Optional[Dict[str, Any]] = None
            try:
                from core.interaction.interaction_builder import InteractionBuilder as _IBuilder2
                _envelope2 = _IBuilder2().build(
                    trace_id=trace_id,
                    session_id=session_id,
                    scene_decision=_decision,
                    persona_state=_persona_state_dict,
                    fused_context=_mm_context_dict,
                )
                _interaction_envelope_dict2 = _envelope2.to_dict()
            except Exception as _ie2:
                logger.debug("InteractionEnvelope build (direct path) failed: %s", _ie2)

            # ── Output Orchestrator (PR-6) ────────────────────────────────────
            _output_plan_dict2: Optional[Dict[str, Any]] = None
            try:
                from core.output.orchestrator import OutputOrchestrator as _OOrch2
                _output_plan_dict2 = _OOrch2().orchestrate(
                    interaction_envelope=_interaction_envelope_dict2,
                    persona_state=_persona_state_dict,
                    response_text=response_text,
                )
            except Exception as _op2:
                logger.debug("OutputOrchestrator (direct path) failed: %s", _op2)

            # ── State Continuum (PR-5) ────────────────────────────────────────
            _continuum_state_dict2: Optional[Dict[str, Any]] = self._run_continuum(
                trace_id=trace_id,
                multimodal_context=multimodal_context,
                runtime_session_id=runtime_session_id,
            )
            # ── Decision Execution (PR-8 / PR-4) ─────────────────────────────
            _exec_result2 = self._run_execution(_continuum_state_dict2, entry_mode=_entry_mode)
            # Detect whether a cross-device dispatch occurred (set by handlers).
            _cross_device2 = bool(result.get("metadata", {}).get("remote_dispatch", False))
            _exec_path2 = self._determine_execution_path(
                entry_mode=_entry_mode,
                execution_result=_exec_result2,
                cross_device_dispatched=_cross_device2,
            )
            # PR-4: structured observability log whenever execution_path is set.
            logger.info(
                "OpenClawd manifest | trace_id=%s entry_mode=%s execution_path=%s",
                trace_id, _entry_mode, _exec_path2,
            )
            if _exec_path2 == "none":
                _exec_result2.setdefault("skipped_reason", "no_execution")
            # Attach cross-device summary when applicable.
            if _cross_device2:
                _exec_result2["cross_device_summary"] = {
                    "request_id": request_id,
                    "device_ids": [device_id] if device_id else [],
                    "status": "dispatched" if result.get("success") else "failed",
                }
            # PR-11: build canonical execution plan (additive, non-breaking)
            _delegation_point2 = result.get("metadata", {}).get("delegation_point")
            _remote_mode2 = result.get("metadata", {}).get("remote_execution_mode")
            _plan2 = self._build_execution_plan(
                execution_path=_exec_path2,
                delegation_point=_delegation_point2,
                trace_id=trace_id,
                session_id=session_id,
                device_id=device_id,
                remote_execution_mode=_remote_mode2,
            )
            # PR-12: advance plan lifecycle to terminal state
            self._finalise_plan_lifecycle(_plan2, success=bool(result.get("success", True)))
            # PR-19: build canonical unified control plan (additive, non-breaking)
            _ucp2 = self._build_unified_control_plan(
                runtime_session_id=runtime_session_id,
                trace_id=trace_id,
                canonical_perception=_canonical_perception,
                # PR-24: wire canonical model supply into the unified control plan
                canonical_model_supply=_canonical_model_supply,
                continuum_state=_continuum_state_dict2,
                chosen_model=provider_info.get("model") if provider_info else None,
                chosen_provider=provider_info.get("provider") if provider_info else None,
                is_native_multimodal=_is_native_multimodal,
                execution_path=_exec_path2,
                delegation_point=_delegation_point2,
                remote_execution_mode=_remote_mode2,
                lifecycle_target=_plan2.lifecycle_state if _plan2 else None,
                execution_plan_summary=self._summarise_execution_plan(_plan2),
                # PR-24: embed canonical routing decision in the plan
                multimodal_route_decision=_multimodal_route,
            )

            return {
                "success": result.get("success", True),
                "response": response_text,
                "intent": intent_type,
                "trace_id": trace_id,
                "runtime_session_id": runtime_session_id or trace_id,
                "execution_path": _exec_path2,
                "execution_result": _exec_result2,
                # PR-11: canonical execution plan (may be None if schema unavailable)
                "execution_plan": _plan2.to_dict() if _plan2 else None,
                "interaction": _interaction_dict,
                "persona_state": _persona_state_dict,
                "interaction_envelope": _interaction_envelope_dict2,
                "output_plan": _output_plan_dict2,
                "state_continuum": _continuum_state_dict2,
                "metadata": {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "runtime_session_id": runtime_session_id or trace_id,
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "confidence": parsed_intent.confidence if parsed_intent else 0.0,
                    "suggestions": parsed_intent.suggestions if parsed_intent else [],
                    "handler": handler_name,
                    "entry_mode": _entry_mode,
                    "execution_path": _exec_path2,
                    # PR-9: subject decision authority annotation (additive)
                    "authority_role": "subject_decision_authority",
                    # PR-11: compact execution plan summary for diagnostics
                    "execution_plan_summary": self._summarise_execution_plan(_plan2),
                    # PR-12: plan-level lifecycle state for observability
                    "execution_lifecycle_state": _plan2.lifecycle_state if _plan2 else None,
                    **provider_info,
                    **(result.get("metadata", {})),
                    # PR-24 DEPRECATED-COMPAT: raw fused multimodal context
                    # from MultimodalBus.ingest().  New consumers should prefer
                    # ``canonical_perception_state`` (PR-16) as the authoritative
                    # perception source.  Retained only for backward compatibility;
                    # do not add new consumers of this key.
                    "multimodal_context": _mm_context_dict,
                    # PR-16: canonical perception state (primary perception contract)
                    "canonical_perception_state": _canonical_perception,
                    # PR-24: canonical model supply state (primary model supply
                    # contract, PR-18) — now forwarded from the unified control
                    # plan so the response carries the full canonical state chain.
                    "canonical_model_supply_state": _canonical_model_supply,
                    # PR-19: canonical unified control plan
                    "unified_control_plan": _ucp2,
                    # PR-24 DEPRECATED-COMPAT: top-level routing decision dict.
                    # The canonical routing decision is now embedded inside
                    # unified_control_plan["multimodal_route_decision"].
                    # This key is retained only for backward compatibility.
                    "multimodal_route_decision": _multimodal_route,
                    # PR-41: structured routing observability event derived
                    # from the canonical routing decision (not inferred).
                    "routing_decision_event": _routing_decision_event,
                    # PR-29: canonical degraded-operation envelope.
                    "degraded_operation_envelope": _degraded_operation_envelope,
                    # PR-30: control-loop latency budget summary (ingest cadence,
                    # recompute throttling, projection refresh, fast-path).
                    "latency_budget_summary": _latency_budget_summary,
                    # PR-32: canonical permission/trust/safety snapshot
                    # (permission visibility, trust labels, safety gating).
                    "permission_safety_state": _permission_safety_state,
                    # PR-33: canonical operator override snapshot
                    # (active source/model/execution-policy overrides).
                    "operator_override_state": _operator_override_state,
                    # PR-34: canonical decision timeline / explainability snapshot
                    # (route selection, fallback transitions, operator override
                    # influence, trust/safety gating — all correlated and replayable).
                    "decision_timeline_snapshot": _decision_timeline_snapshot,
                    # PR-36: production baseline status — confirms that the unified
                    # canonical control loop is active as the production baseline
                    # and reports coverage of canonical primary artifacts.
                    "production_baseline_summary": self._build_production_baseline_summary(
                        response_metadata={
                            "canonical_perception_state": _canonical_perception,
                            "canonical_model_supply_state": _canonical_model_supply,
                            "unified_control_plan": _ucp2,
                            "degraded_operation_envelope": _degraded_operation_envelope,
                            "latency_budget_summary": _latency_budget_summary,
                            "permission_safety_state": _permission_safety_state,
                            "operator_override_state": _operator_override_state,
                            "decision_timeline_snapshot": _decision_timeline_snapshot,
                        }
                    ),
                    # PR-8: mainline convergence stamp — records that this
                    # response traversed the canonical OpenClawd authority
                    # stage, making the mainline path explicit and traceable.
                    "mainline_convergence": self._build_mainline_convergence_stamp(
                        trace_id=trace_id,
                        session_id=session_id,
                        execution_path=_exec_path2,
                    ),
                },
                # PR-14: additive introspection hints (non-breaking; callers ignoring
                # this field are unaffected).
                "introspection_snapshot": {
                    "authority_role": "subject_decision_authority",
                    "delegation_point": _delegation_point2,
                    "execution_mode": _remote_mode2,
                    "execution_path": _exec_path2,
                    "lifecycle_state": _plan2.lifecycle_state if _plan2 else None,
                    "execution_plan_summary": self._summarise_execution_plan(_plan2),
                    "device_id": device_id,
                    "trace_id": trace_id,
                    "success": bool(result.get("success", True)),
                },
            }

        except Exception as e:
            self._error_count += 1
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error(f"OpenClawd.process 失败: {e}", exc_info=True)
            # ── Audit ledger: TASK_FAILED ─────────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType5, Severity as _Sev5
                from core.control_plane._globals import get_audit_ledger
                get_audit_ledger().append(
                    _EvType5.TASK_FAILED,
                    severity=_Sev5.ERROR,
                    source="openclawd",
                    message=f"process() raised: {e}",
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    payload={"error": str(e)},
                )
            except Exception:
                pass
            return {
                "success": False,
                "response": f"处理请求时发生错误: {str(e)}",
                "intent": "error",
                "trace_id": trace_id,
                "execution_path": "none",
                "execution_result": {
                    "action_taken": "none",
                    "success": False,
                    "skipped_reason": f"process_error: {e}",
                },
                "metadata": {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "entry_mode": _entry_mode,
                    "execution_path": "none",
                    "error": str(e),
                },
            }

    # ========================================================================
    # 意图解析
    # ========================================================================

    async def _parse_intent(self, message: str, session_id: str):
        """解析用户意图 (懒加载 IntentParser)"""
        try:
            from core.ai_intent import get_intent_parser

            parser = get_intent_parser()

            # 构建上下文
            context = None
            session_history = self._session_memory.get(session_id, [])
            if session_history:
                context = {"history": session_history[-10:]}

            parsed = await parser.parse(message, context)
            logger.info(
                f"意图解析: intent={parsed.intent}, "
                f"confidence={parsed.confidence:.2f}, "
                f"command={parsed.command}"
            )
            return parsed

        except Exception as e:
            logger.warning(f"意图解析失败，降级到默认 chat 意图: {e}")
            return None

    # ========================================================================
    # 分派处理器
    # ========================================================================

    async def _dispatch_chat(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """纯聊天分派"""
        return await self.handle_chat(message, session_id or "default")

    async def _dispatch_device(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """设备操控分派 — 经由 send_gateway_command → CommandRouter → trace"""
        if not device_id:
            # Phase 2: try to auto-select a device via the smart scheduler
            required_caps = getattr(intent, "required_capabilities", None) if intent else None
            selected = self._select_device_via_scheduler(required_caps)
            if selected:
                logger.info(
                    "_dispatch_device: no device_id provided; scheduler selected %s", selected
                )
                device_id = selected
            else:
                return {
                    "success": False,
                    "response": "设备操控需要指定 device_id，请连接设备后重试。",
                }
        command = intent.command if intent else "device_control"
        params = intent.params if intent else {}
        result = await self.send_gateway_command(
            device_id=device_id,
            command=command,
            payload=params,
            session_id=session_id,
        )
        # 统一响应字段（send_gateway_command 返回 response/success，保持 handle_device_command 兼容）
        if "response" not in result:
            if result.get("success"):
                result["response"] = result.get("result") or f"设备命令 '{command}' 已发送到 {device_id}"
            else:
                result["response"] = result.get("result") or f"无法向设备 {device_id} 发送命令 '{command}'"
        return result

    # ========================================================================
    # PR-3: Explicit Delegation Boundary Helpers
    # =========================================================================
    # OpenClawd is the subject core / decision core.  These helpers name the
    # three execution delegation points it can activate.  They are thin wrappers
    # that make the boundary explicit in code and callable from tests.
    #
    # Delegation hierarchy (inside OpenClawd):
    #   _delegate_local_manifestation()         — stays on this device
    #   _delegate_single_remote()               — one named remote device
    #   _delegate_multi_device_orchestration()  — fan-out to many devices
    # =========================================================================

    async def _delegate_local_manifestation(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Delegation point: **local manifestation**.

        Executes the intent on this host via the embedded ``AgentKernel``
        and local System API tools.  This is the subject's direct expression
        on the local Windows device; no cross-device substrate is involved.

        Called by :meth:`_dispatch_agent` when the effective target is the
        local device (or no target is specified).

        Returns
        -------
        dict
            Standard handler response with ``delegation_point="local"`` in
            ``metadata``.
        """
        result = await self.handle_agent_task(
            message, intent,
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
        )
        result.setdefault("metadata", {})
        result["metadata"]["delegation_point"] = "local"
        return result

    async def _delegate_single_remote(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Delegation point: **single remote device delegation**.

        Forwards the intent to one named remote device via the cross-device
        substrate (``CommandRouter`` → gateway / WebSocket).  OpenClawd
        remains the decision core; it delegates *execution* to the remote
        device, it does not become the transport substrate itself.

        Called by :meth:`_dispatch_agent` when ``effective_target`` is a
        non-local device ID.

        Returns
        -------
        dict
            Standard handler response with ``delegation_point="single_remote"``
            in ``metadata``.
        """
        result = await self._dispatch_remote_agent(
            message=message,
            intent=intent,
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
        )
        result.setdefault("metadata", {})
        result["metadata"]["delegation_point"] = "single_remote"
        return result

    async def _delegate_multi_device_orchestration(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Delegation point: **multi-device orchestration delegation**.

        PR-8: This method is the hand-off from the OpenClawd decision core to
        the **multi-device orchestration layer**.

        Architectural contract
        ~~~~~~~~~~~~~~~~~~~~~~
        * OpenClawd (decision core) decides that multi-device orchestration is
          needed and calls this method.
        * This method delegates to :meth:`_dispatch_parallel_goal`, which in
          turn invokes the orchestration layer
          (:class:`~core.swarm_coordinator.SwarmCoordinator`).
        * The orchestration layer makes device-selection / coordination
          decisions (above the substrate).
        * The substrate (:class:`~core.command_router.CommandRouter`) handles
          transport/execution after the orchestration layer has selected targets.

        OpenClawd is NOT the multi-device orchestration layer itself; it is the
        subject decision core that *delegates* to the orchestration layer.
        The orchestration layer is NOT the substrate; it coordinates *above* it.

        Returns
        -------
        dict
            Standard handler response with
            ``delegation_point="multi_device_orchestration"`` in ``metadata``.
        """
        result = await self._dispatch_parallel_goal(
            message=message,
            intent=intent,
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
        )
        result.setdefault("metadata", {})
        result["metadata"]["delegation_point"] = "multi_device_orchestration"
        return result

    async def _dispatch_agent(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Agent 任务分派 — routes to the correct delegation boundary.

        PR-3: This method is the **decision core** branch selector for
        agent tasks.  It resolves which of the three delegation boundaries
        to activate:

        - **local manifestation** (:meth:`_delegate_local_manifestation`) —
          no remote target, or target is the local device.
        - **single remote delegation** (:meth:`_delegate_single_remote`) —
          a non-local ``device_id`` / ``intent.target_device`` is specified.

        Multi-device orchestration delegation is handled separately via
        :meth:`_dispatch_parallel_goal` (intent ``parallel_goal``).

        PR155: 支持远程设备分发；PR154: trace 贯穿。
        """
        # Resolve effective execution target
        target_device = None
        if intent is not None:
            target_device = getattr(intent, "target_device", None)
        # Also accept an externally provided remote device_id
        effective_target = target_device or device_id

        # Route to single-remote delegation when a non-local device is named
        if effective_target and not _is_local_device(effective_target):
            return await self._delegate_single_remote(
                message=message,
                intent=intent,
                device_id=effective_target,
                session_id=session_id,
                trace_id=trace_id,
            )

        # Default: local manifestation delegation
        return await self._delegate_local_manifestation(
            message=message,
            intent=intent,
            device_id=effective_target,
            session_id=session_id,
            trace_id=trace_id,
        )

    # ========================================================================
    # _dispatch_remote_agent — PR155: 远程 Agent 分发
    # ========================================================================

    async def _dispatch_remote_agent(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """将 Agent 任务通过 CommandRouter 分发到远程设备执行（PR155）。

        PR-2：在入口立即构造 TaskEnvelope，统一内部路由格式。
        链路：OpenClawd → TaskEnvelope → CommandRouter.dispatch_agent_remote →
              gateway/WS → device agent_execute handler → result backflow

        如果设备离线或 CommandRouter 返回错误，自动降级到本地执行并在
        返回值中标注 ``remote_fallback=True``。

        Parameters
        ----------
        message:
            用户原始指令（透传给远程设备 Agent）。
        intent:
            已解析的意图对象（可为 None）。
        device_id:
            目标设备 ID。
        session_id / trace_id:
            跟踪字段，贯穿整条链路。

        Returns
        -------
        dict
            含 ``success``、``response``、``metadata``（agent_id / task_id /
            trace_id / device_id / remote_dispatch）的标准响应。
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        agent_id = f"remote_agent_{uuid.uuid4().hex[:8]}"
        agent_template = (
            getattr(intent, "intent", None) or "coordinator"
        )

        # PR-2: construct TaskEnvelope immediately at entry for unified internal routing.
        # PR-6: resolve execution mode via DeviceExecutionProfile + RemoteExecutionModeResolver
        # instead of hardcoding agent_runtime so thin/unknown devices fall back gracefully.
        _remote_mode_str: str = "agent_runtime"  # default; overridden by resolver below
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
            from core.schemas.remote_execution import RemoteExecutionMode as _REM

            # PR-6: build execution profile and resolve mode; defaults to agent_runtime
            # for rich devices and command_only for thin/unknown (conservative fallback).
            # This block is entirely non-fatal: any failure leaves _resolved_rem as
            # agent_runtime (preserving the original behaviour).
            _resolved_rem = _REM.agent_runtime
            _mode_resolution_source = "default"
            _profile_class_label = None
            try:
                from core.device_execution_profile import build_profile_from_device_info
                from core.remote_execution_mode_resolver import resolve_mode as _resolve_mode

                _device_info: dict = {}
                try:
                    from core.routes._shared import connection_manager as _cm
                    _all_devices = _cm.get_all_devices()
                    _device_info = _all_devices.get(device_id, {}) if device_id else {}
                except Exception:
                    pass
                _exec_profile = build_profile_from_device_info(_device_info, device_id=device_id)
                _mode_result = _resolve_mode(
                    profile=_exec_profile,
                    task_intent="agent_execute",
                    dispatch_context={
                        "agent_template": agent_template,
                        "session_id": session_id or "",
                    },
                )
                _resolved_rem = _REM(_mode_result.mode)
                _remote_mode_str = _mode_result.mode
                _mode_resolution_source = _mode_result.resolution_source
                _profile_class_label = _mode_result.profile_class
                logger.debug(
                    "OpenClawd._dispatch_remote_agent mode resolved: mode=%s source=%s device_id=%s",
                    _mode_result.mode,
                    _mode_result.resolution_source,
                    device_id,
                )
            except Exception as _pr6_err:
                logger.debug(
                    "_dispatch_remote_agent: PR-6 mode resolution non-fatal: %s — "
                    "defaulting to agent_runtime",
                    _pr6_err,
                )

            _remote_envelope = _TaskEnvelope(
                task_id=task_id,
                trace_id=trace_id,
                source="openclawd._dispatch_remote_agent",
                targets=[device_id] if device_id else [],
                tool_name="agent_remote",
                args={
                    "message": message,
                    "agent_template": agent_template,
                    "session_id": session_id or "",
                },
                # PR-7: always stamp agent_runtime for the agent dispatch path.
                # The PR-6 resolver result is recorded in metadata for
                # observability but does not override the substrate mode here —
                # _dispatch_remote_agent is specifically the agent execution path.
                remote_execution_mode=_REM.agent_runtime,
                metadata={
                    "agent_id": agent_id,
                    "device_id": device_id or "",
                    "session_id": session_id or "",
                    "execution_mode_source": _mode_resolution_source,
                    "profile_class": _profile_class_label,
                    "resolver_mode": _remote_mode_str,
                },
            )
            logger.debug(
                "OpenClawd._dispatch_remote_agent envelope | task_id=%s trace_id=%s agent_id=%s",
                _remote_envelope.task_id,
                _remote_envelope.trace_id,
                agent_id,
            )
        except Exception as _env_err:
            logger.debug("_dispatch_remote_agent: TaskEnvelope construction skipped — %s", _env_err)

        logger.info(
            "OpenClawd._dispatch_remote_agent | trace_id=%s task_id=%s "
            "agent_id=%s device_id=%s template=%s",
            trace_id, task_id, agent_id, device_id, agent_template,
        )

        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            cr_result = await cr.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template=agent_template,
                task=message,
                session_id=session_id or "",
                trace_id=trace_id,
                task_id=task_id,
                context={
                    "intent": getattr(intent, "intent", "") if intent else "",
                    "params": getattr(intent, "params", {}) if intent else {},
                },
            )
        except Exception as cr_exc:
            logger.warning(
                "OpenClawd._dispatch_remote_agent: CommandRouter 不可用，降级本地 | "
                "trace_id=%s error=%s",
                trace_id, cr_exc,
            )
            # Fallback: local execution
            local_result = await self.handle_agent_task(
                message, intent,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )
            local_result.setdefault("metadata", {})
            local_result["metadata"]["remote_fallback"] = True
            local_result["metadata"]["fallback_reason"] = str(cr_exc)
            return local_result

        remote_success = cr_result.get("success", False)
        remote_error_code = cr_result.get("error_code")

        # Fallback when device offline / timeout / disconnect
        if not remote_success and remote_error_code in (
            "DEVICE_OFFLINE",
            "DEVICE_NOT_FOUND",
            "COMMAND_TIMEOUT",
            "DISCONNECT",
        ):
            logger.warning(
                "OpenClawd._dispatch_remote_agent: 远程失败(%s)，降级本地执行 | "
                "trace_id=%s device_id=%s",
                remote_error_code, trace_id, device_id,
            )
            local_result = await self.handle_agent_task(
                message, intent,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )
            local_result.setdefault("metadata", {})
            local_result["metadata"]["remote_fallback"] = True
            local_result["metadata"]["fallback_reason"] = remote_error_code
            local_result["metadata"]["remote_error"] = cr_result.get("error_message", "")
            return local_result

        # Remote execution returned a structured result
        raw_result = cr_result.get("result") or {}
        if isinstance(raw_result, str):
            response_text = raw_result
        elif isinstance(raw_result, dict):
            response_text = raw_result.get("response") or raw_result.get("output") or str(raw_result)
        else:
            response_text = str(raw_result) if raw_result else "远程 Agent 任务已完成"

        # PR155: 结果回流到 TaskMemory
        try:
            from core.openclawd_memory_backflow import store_task_result
            await store_task_result(
                task_id=task_id,
                device_id=device_id or "remote",
                route_mode="remote_agent",
                result={
                    "status": "completed" if remote_success else "error",
                    "task_type": "agent_execute",
                    "task_description": message[:200],
                    "result_summary": response_text[:200],
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                },
                session_id=session_id,
            )
        except Exception as _bf_err:
            logger.warning(
                "_dispatch_remote_agent: memory backflow 失败（非致命）: %s", _bf_err
            )

        return {
            "success": remote_success,
            "response": response_text if remote_success else (
                cr_result.get("error_message") or "远程 Agent 执行失败"
            ),
            "metadata": {
                "agent_id": agent_id,
                "agent_template": agent_template,
                "task_id": task_id,
                "trace_id": trace_id,
                "device_id": device_id or "",
                "session_id": session_id or "",
                "remote_dispatch": True,
                # PR-7: take mode from the substrate result (cr_result carries the
                # mode that was stamped in the TaskEnvelope by dispatch_agent_remote
                # via route_envelope).  Fall back to agent_runtime because this code
                # path is always an agent dispatch — the PR-6 conservative resolver
                # default of command_only is not appropriate here.
                "remote_execution_mode": cr_result.get("remote_execution_mode") or "agent_runtime",
                "latency_ms": cr_result.get("latency_ms", 0.0),
                "error_code": remote_error_code,
            },
        }

    async def _dispatch_tool(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """工具调用分派"""
        return await self.handle_tool_call(intent)

    async def _dispatch_status(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """系统状态分派"""
        status = await self.get_status()
        # 将状态格式化为可读文本
        provider_count = status.get("llm_router", {}).get("total_providers", 0)
        agent_count = status.get("agent_factory", {}).get("total_agents", 0)
        mcp_count = status.get("mcp", {}).get("server_count", 0)
        skill_count = status.get("skills", {}).get("loaded_skills", 0)

        summary_lines = [
            "Galaxy 系统状态概览:",
            f"  LLM 提供商: {provider_count} 个",
            f"  活跃 Agent: {agent_count} 个",
            f"  MCP 服务器: {mcp_count} 个",
            f"  已加载技能: {skill_count} 个",
            f"  总请求数: {self._request_count}",
            f"  错误数: {self._error_count}",
            f"  运行时间: {int(time.time() - self._start_time)}s",
        ]
        return {
            "success": True,
            "response": "\n".join(summary_lines),
            "metadata": {"status_detail": status},
        }

    @staticmethod
    def _pick_autonomous_device_id(
        device_id: Optional[str],
        capability_key: str = "goal_execution_enabled",
    ) -> Optional[str]:
        """
        Select the best device for autonomous execution.

        Priority order:
          1. Explicit ``device_id`` if provided (caller takes responsibility for
             the device being capable).
          2. CapabilityRegistry autonomous__* entries matching ``capability_key``
             (Phase-3 SSOT, preferred over raw UDM when no explicit device is given).
          3. UnifiedDeviceManager.get_autonomous_devices() (UDM-based fallback).

        Returns None when no suitable device can be identified so the caller
        can degrade gracefully.
        """
        # 1. Caller-supplied device_id takes highest priority
        if device_id:
            logger.debug(
                "_pick_autonomous_device_id: using caller-supplied device_id=%s", device_id,
            )
            return device_id

        # 2. Try CapabilityRegistry (autonomous__* prefix = Phase-3 SSOT)
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            items = [
                item for item in reg.list_tools(source="autonomous")
                if item.available
                and capability_key in item.name
            ]
            if items:
                selected_id = items[0].metadata.get("device_id") or items[0].source_id
                logger.info(
                    "_pick_autonomous_device_id: CapabilityRegistry selected device=%s (cap=%s)",
                    selected_id, capability_key,
                )
                return selected_id
        except Exception as exc:
            logger.debug("_pick_autonomous_device_id: CapabilityRegistry lookup failed: %s", exc)

        # 3. Fallback to UDM
        try:
            from core.unified.device_manager import get_unified_device_manager
            auto_devices = get_unified_device_manager().get_autonomous_devices()
            if auto_devices:
                selected_id = auto_devices[0].device_id
                logger.info(
                    "_pick_autonomous_device_id: UDM selected device=%s", selected_id,
                )
                return selected_id
        except Exception as exc:
            logger.debug("_pick_autonomous_device_id: UDM lookup failed: %s", exc)

        return None

    async def _dispatch_goal_execution(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Priority D: 高层自治目标执行分派。

        流程：
          1. 优先从 CapabilityRegistry autonomous__* 条目选择支持
             goal_execution_enabled 的设备（Phase-3 SSOT）。
          2. 若 CapabilityRegistry 无结果，回退到 UnifiedDeviceManager 自治设备列表。
          3. 若仍无可用自治设备，降级到普通 _dispatch_agent 并记录明确消息。
        """
        from core.task_logger import emit_task_log

        goal = message
        params = {}
        if intent:
            goal = getattr(intent, "goal", None) or getattr(intent, "command", None) or message
            params = getattr(intent, "params", {}) or {}

        # 确定目标设备（自治能力感知）
        target_device_id = self._pick_autonomous_device_id(
            device_id, capability_key="goal_execution_enabled"
        )

        if not target_device_id:
            logger.info(
                "goal_execution: 无可用自治设备（CapabilityRegistry autonomous__* 和 UDM 均未返回结果），"
                "降级为 agent 执行"
            )
            return await self._dispatch_agent(message, intent, device_id, session_id)

        # Generate a task_id so callers can cancel before / during execution
        task_id = f"goal_{uuid.uuid4().hex[:12]}"

        # ── Cancel check before dispatch ──────────────────────────────────
        if self._is_cancelled(task_id):
            logger.info("goal_execution: task %s cancelled before dispatch", task_id)
            emit_task_log(
                "task_cancelled",
                task_id=task_id,
                trace_id=trace_id,
                device_id=target_device_id,
                task_type="goal_execution",
                status="cancelled",
            )
            return {
                "success": False,
                "response": f"目标任务 '{goal}' 已被取消（取消发生在执行前）",
                "intent": "goal_execution",
                "task_id": task_id,
                "trace_id": trace_id,
                "cancelled": True,
            }

        emit_task_log(
            "task_dispatched",
            task_id=task_id,
            trace_id=trace_id,
            device_id=target_device_id,
            task_type="goal_execution",
            status="dispatched",
        )
        t_dispatch = time.monotonic()

        try:
            result = await _asyncio_module.wait_for(
                self.send_gateway_command(
                    device_id=target_device_id,
                    command="goal_execution",
                    payload={
                        "task_type": "goal_execution",
                        "goal": goal,
                        "task_id": task_id,
                        "trace_id": trace_id,
                        **params,
                    },
                    task_id=task_id,
                    session_id=session_id,
                ),
                timeout=self.GOAL_EXECUTION_TIMEOUT,
            )
        except _asyncio_module.TimeoutError:
            latency_ms = (time.monotonic() - t_dispatch) * 1000
            logger.warning(
                "goal_execution timed out after %.1fs | device=%s task_id=%s",
                self.GOAL_EXECUTION_TIMEOUT, target_device_id, task_id,
            )
            emit_task_log(
                "task_timeout",
                task_id=task_id,
                trace_id=trace_id,
                device_id=target_device_id,
                task_type="goal_execution",
                latency_ms=round(latency_ms, 1),
                status="timeout",
            )
            return {
                "success": False,
                "response": (
                    f"目标任务 '{goal}' 执行超时（超过 {self.GOAL_EXECUTION_TIMEOUT:.0f} 秒），"
                    "请稍后重试或检查设备状态。"
                ),
                "intent": "goal_execution",
                "task_id": task_id,
                "trace_id": trace_id,
                "timed_out": True,
            }

        latency_ms = (time.monotonic() - t_dispatch) * 1000
        if "response" not in result:
            result["response"] = (
                result.get("result")
                or f"目标任务 '{goal}' 已提交至设备 {target_device_id}"
            )
        result["intent"] = "goal_execution"
        result.setdefault("task_id", task_id)
        result.setdefault("trace_id", trace_id)
        success = result.get("success", False)
        logger.info(
            "goal_execution dispatched | device=%s success=%s",
            target_device_id,
            success,
        )
        emit_task_log(
            "task_completed" if success else "task_failed",
            task_id=task_id,
            trace_id=trace_id,
            device_id=target_device_id,
            task_type="goal_execution",
            latency_ms=round(latency_ms, 1),
            status="success" if success else "failed",
        )
        return result

    async def _dispatch_parallel_goal(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Priority E: 多设备并行任务拆分与下发（Phase-3 状态机 + 重试）。

        流程：
          1. 优先从 CapabilityRegistry 选择声明 autonomous__* / parallel_execution_enabled
             能力的设备；回退到 UDM get_autonomous_devices()。
          2. 若无可用设备，降级并返回明确降级消息（不走 goal_execution）。
          3. 使用 ParallelGroupTracker 追踪每个子任务状态。
          4. 对失败子任务执行最多 1 次指数退避重试（上限 30 s）。
          5. 所有子任务完成后聚合 ParallelResult 并返回统一结构。
        """
        from core.task_logger import emit_task_log

        goal = message
        params = {}
        if intent:
            goal = getattr(intent, "goal", None) or getattr(intent, "command", None) or message
            params = getattr(intent, "params", {}) or {}

        # 查找支持并行执行的设备（autonomous__* 优先）
        parallel_devices = []
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            # devices with parallel_execution_enabled in autonomous__* items
            auto_items = [
                item for item in reg.list_tools(source="autonomous")
                if item.available and "parallel_execution_enabled" in item.name
            ]
            seen_ids: set = set()
            for item in auto_items:
                did = item.metadata.get("device_id") or item.source_id
                if did and did not in seen_ids:
                    seen_ids.add(did)
                    parallel_devices.append(did)
        except Exception as exc:
            logger.debug("parallel_goal: CapabilityRegistry 查询失败: %s", exc)

        # Fallback: UDM
        if not parallel_devices:
            try:
                from core.unified.device_manager import get_unified_device_manager
                udm = get_unified_device_manager()
                devs = udm.get_devices_with_capability("parallel_execution_enabled")
                if not devs:
                    devs = udm.get_autonomous_devices()
                parallel_devices = [d.device_id for d in devs]
            except Exception as exc:
                logger.debug("parallel_goal: UDM 设备查询失败: %s", exc)

        if not parallel_devices:
            logger.info(
                "parallel_goal: 无支持并行执行的自治设备（autonomous__* 和 UDM 均无结果），"
                "降级：无法执行并行任务"
            )
            return {
                "success": False,
                "response": (
                    "当前无支持并行执行的自治设备。"
                    "请确保至少一台设备注册了 parallel_execution_enabled 能力后重试。"
                ),
                "intent": "parallel_goal",
                "metadata": {"parallel_group": None, "device_count": 0},
            }

        subtasks = params.get("subtasks") or [goal] * len(parallel_devices)
        task_id_base = uuid.uuid4().hex[:8]

        # ── 初始化状态追踪 ──
        tracker = ParallelGroupTracker()
        entries: List[_SubtaskEntry] = []
        for idx, dev_id in enumerate(parallel_devices):
            sub_task_id = f"{task_id_base}_sub{idx}"
            entries.append(_SubtaskEntry(
                task_id=sub_task_id,
                group_id=task_id_base,
                subtask_index=idx,
                device_id=dev_id,
                subtask=subtasks[idx % len(subtasks)],
            ))
        tracker.register_group(task_id_base, entries)

        t_parallel_start = time.monotonic()

        async def _execute_entry(entry: _SubtaskEntry) -> None:
            """Execute one subtask with retry/backoff, timeout, and cancel support."""
            while True:
                # ── Cancel check (before each attempt) ──────────────────────
                if self._is_cancelled(entry.task_id, entry.group_id):
                    logger.info(
                        "parallel_goal: subtask %d on device %s cancelled",
                        entry.subtask_index, entry.device_id,
                    )
                    tracker.mark_cancelled(entry.group_id, entry.task_id)
                    emit_task_log(
                        "task_cancelled",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        status="cancelled",
                    )
                    return

                tracker.mark_running(entry.group_id, entry.task_id)
                emit_task_log(
                    "task_dispatched",
                    task_id=entry.task_id,
                    trace_id=trace_id,
                    device_id=entry.device_id,
                    group_id=entry.group_id,
                    subtask_index=entry.subtask_index,
                    task_type="parallel_subtask",
                    status="dispatched",
                )
                t_sub = time.monotonic()
                try:
                    r = await _asyncio_module.wait_for(
                        self.send_gateway_command(
                            device_id=entry.device_id,
                            command="goal_execution",
                            payload={
                                "task_type": "parallel_subtask",
                                "goal": entry.subtask,
                                "parallel_group": entry.group_id,
                                "subtask_index": entry.subtask_index,
                                "trace_id": trace_id,
                            },
                            task_id=entry.task_id,
                            session_id=session_id,
                        ),
                        timeout=self.PARALLEL_SUBTASK_TIMEOUT,
                    )
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    # Propagate command_id / task_id / trace_id into result
                    r.setdefault("command_id", "")
                    r.setdefault("task_id", entry.task_id)
                    r.setdefault("trace_id", trace_id)
                    success = bool(r.get("success"))
                    tracker.mark_done(entry.group_id, entry.task_id, r, success=success)
                    emit_task_log(
                        "task_completed" if success else "task_failed",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="success" if success else "failed",
                    )
                    if not success and tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        logger.warning(
                            "parallel_goal: subtask %d on device %s failed, "
                            "retry in %.1fs (attempt %d/%d)",
                            entry.subtask_index, entry.device_id,
                            delay, entry.retry_count + 1, ParallelGroupTracker._MAX_RETRIES,
                        )
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    return
                except _asyncio_module.TimeoutError:
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    logger.warning(
                        "parallel_goal: subtask %d on device %s timed out after %.1fs",
                        entry.subtask_index, entry.device_id, self.PARALLEL_SUBTASK_TIMEOUT,
                    )
                    tracker.mark_timeout(entry.group_id, entry.task_id)
                    emit_task_log(
                        "task_timeout",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="timeout",
                    )
                    if tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    return
                except Exception as exc:
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    err_result = {
                        "success": False,
                        "response": str(exc),
                        "task_id": entry.task_id,
                        "trace_id": trace_id,
                        "device_id": entry.device_id,
                    }
                    tracker.mark_done(entry.group_id, entry.task_id, err_result, success=False)
                    emit_task_log(
                        "task_failed",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="failed",
                        error=str(exc),
                    )
                    if tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        logger.warning(
                            "parallel_goal: subtask %d on device %s raised %s, "
                            "retry in %.1fs",
                            entry.subtask_index, entry.device_id, exc, delay,
                        )
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    logger.warning(
                        "parallel_goal: subtask %d on device %s permanently failed: %s",
                        entry.subtask_index, entry.device_id, exc,
                    )
                    return

        await _asyncio_module.gather(
            *[_execute_entry(e) for e in entries],
            return_exceptions=True,
        )

        parallel_result = tracker.aggregate(task_id_base)
        cancelled_count = parallel_result.cancelled
        parallel_latency_ms = (time.monotonic() - t_parallel_start) * 1000
        summary_text = (
            f"并行任务 '{goal}' 已分发至 {len(parallel_devices)} 台设备："
            f"{parallel_result.succeeded} 成功，"
            f"{parallel_result.failed} 失败，"
            f"{cancelled_count} 已取消。"
        )
        logger.info(
            "parallel_goal done | group=%s devices=%d succeeded=%d failed=%d cancelled=%d status=%s",
            task_id_base,
            len(parallel_devices),
            parallel_result.succeeded,
            parallel_result.failed,
            cancelled_count,
            parallel_result.summary_status,
        )
        emit_task_log(
            "aggregation_done",
            trace_id=trace_id,
            group_id=task_id_base,
            task_type="parallel_goal",
            total=parallel_result.total,
            succeeded=parallel_result.succeeded,
            failed=parallel_result.failed,
            cancelled=cancelled_count,
            latency_ms=round(parallel_latency_ms, 1),
            status=parallel_result.summary_status,
        )
        return {
            "success": parallel_result.succeeded > 0,
            "response": summary_text,
            "intent": "parallel_goal",
            "trace_id": trace_id,
            "metadata": {
                "parallel_group": task_id_base,
                "subtask_results": parallel_result.device_results,
                "device_count": len(parallel_devices),
                "parallel_result": parallel_result.to_dict(),
                "cancelled_count": cancelled_count,
                "trace_id": trace_id,
            },
        }

    def _collect_tools(self) -> List[Dict]:
        """统一收集三层工具（MCP / Skill / Node），转为 OpenAI function calling 格式

        返回格式: [{"type": "function", "function": {"name": "mcp__server__tool", ...}}, ...]
        前缀约定:
          - mcp__<server_id>__<tool_name>   → MCP 协议工具
          - skill__<skill_id>               → Skill 技能
          - node__<node_id>__<action>       → Node 节点操作

        执行链路（按优先级排序）:
          1. CapabilityResolver (canonical read path, contract-validated) — PREFERRED
             a. MCP/Skill tools via CapabilityResolver
             b. Node tools via NodeFabricRegistry.sync_capabilities_to_registry()
                → CapabilityRegistry → CapabilityResolver (CapabilitySource.NODE)
                Only healthy CAPABILITY_NODE nodes are surfaced; SERVICE /
                LEGACY_ORCHESTRATOR / EXPERIMENTAL / ARCHIVED nodes are excluded.
          2. CapabilityRegistry direct read (compatibility fallback when resolver cache is empty)
          3. Direct scan: mcp_loader / skill_loader (legacy compatibility fallback only)
          4. Node direct scan: node_registry.json + fusion_entry discovery (legacy fallback,
             deduplicates against canonical node tools already collected in step 1b)

        MCP/Skill 工具优先通过 CapabilityResolver 取，这是规范的消费者接口；
        Resolver 在返回前对所有 CapabilityContract 做 schema 校验，确保只有合法条目
        进入 LLM 工具列表。仅当 Resolver 和 Registry 均无结果时才回退直接加载路径。
        Node 工具通过 NodeFabricRegistry 规范同步路径纳入能力总线，传统直接扫描路径
        作为兜底回退（对规范路径未覆盖的节点补充）。
        """
        tools: List[Dict] = []

        # ── 主路径: CapabilityResolver (canonical consumer interface, contract-validated) ──
        # CapabilityResolver is the preferred read path per the canonical capability catalog
        # architecture.  It validates all CapabilityContract entries before returning them,
        # ensuring only schema-valid capabilities reach the LLM tool list.
        # Phase-A consolidation: NODE source added here so that node capabilities already
        # cached in the resolver are included in the primary collection pass, not just the
        # secondary NodeFabricRegistry sync pass (Layer 2).
        _catalog_loaded = False
        try:
            from core.unified.capability_resolver import get_capability_resolver
            from core.unified.capability_contract import CapabilitySource
            resolver = get_capability_resolver()
            catalog_tools = resolver.collect_tool_schemas(
                sources=[CapabilitySource.MCP, CapabilitySource.SKILL, CapabilitySource.NODE]
            )
            if catalog_tools:
                tools.extend(catalog_tools)
                _catalog_loaded = True
                logger.debug(
                    "_collect_tools: CapabilityResolver (canonical) returned %d tools "
                    "(MCP + Skill + Node)",
                    len(catalog_tools),
                )
        except Exception as e:
            logger.debug("CapabilityResolver unavailable, falling back to CapabilityRegistry: %s", e)

        # ── 层 2: 规范节点工具同步路径 (NodeFabricRegistry → CapabilityRegistry → Resolver) ──
        # CANONICAL NODE PATH — preferred over the legacy direct-scan path (Layer 4 below).
        # NodeFabricRegistry.sync_capabilities_to_registry() pushes eligible CAPABILITY_NODE
        # entries into CapabilityRegistry with contract-validated naming:
        #   node__<node_id>__<action>
        # Only healthy CAPABILITY_NODE nodes are surfaced; SERVICE_NODE /
        # LEGACY_ORCHESTRATOR_NODE / EXPERIMENTAL_NODE / ARCHIVED_NODE are excluded by
        # NodeFabricRegistry._CAPABILITY_SYNC_ELIGIBLE (architectural classification filter).
        #
        # Phase-A consolidation: node tools are now ALWAYS collected from the resolver after
        # sync, regardless of whether _synced_count > 0.  This ensures that nodes whose
        # capabilities were synced in a previous call are still included when the registry
        # already has their entries.  Deduplication against Layer 1 is handled below.
        _node_catalog_tool_names: set = set()
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            from core.unified.capability_resolver import get_capability_resolver
            from core.unified.capability_contract import CapabilitySource

            _fabric_registry = get_node_fabric_registry()
            _synced_count = _fabric_registry.sync_capabilities_to_registry()
            _node_resolver = get_capability_resolver()
            if _synced_count > 0:
                # New capabilities were just written; invalidate the cache so the
                # resolver picks them up on the next read.
                _node_resolver.invalidate_cache()
            _node_catalog_schemas = _node_resolver.collect_tool_schemas(
                sources=[CapabilitySource.NODE]
            )
            if _node_catalog_schemas:
                _existing_names = {t["function"]["name"] for t in tools}
                _new_node_tools = [
                    t for t in _node_catalog_schemas
                    if t["function"]["name"] not in _existing_names
                ]
                for _t in _new_node_tools:
                    _node_catalog_tool_names.add(_t["function"]["name"])
                tools.extend(_new_node_tools)
                logger.debug(
                    "_collect_tools: canonical node path (NodeFabricRegistry) "
                    "returned %d node tools (synced %d registry entries)",
                    len(_new_node_tools),
                    _synced_count,
                )
        except Exception as e:
            logger.debug("Canonical node tool path (NodeFabricRegistry) unavailable: %s", e)

        if not _catalog_loaded:
            # ── 兼容回退: CapabilityRegistry 直接读取 ──
            # COMPATIBILITY FALLBACK — used when the resolver cache is empty but the
            # registry already has items (e.g. first call before cache warm-up).
            # Prefer the resolver path above for all normal operation.
            try:
                from core.agent.capability_registry import CapabilityRegistry
                reg = CapabilityRegistry.get_instance()
                bus_tools = [
                    item.to_tool_schema()
                    for item in reg.list_tools()
                    if item.source in ("mcp", "skill")
                ]
                if bus_tools:
                    tools.extend(bus_tools)
                    _catalog_loaded = True
                    logger.debug(
                        "_collect_tools: CapabilityRegistry direct read returned %d MCP/Skill tools",
                        len(bus_tools),
                    )
            except Exception as e:
                logger.debug("CapabilityRegistry unavailable, falling back to direct scan: %s", e)

        if not _catalog_loaded:
            # ── LEGACY COMPATIBILITY FALLBACK: MCP direct scan ──
            # DERIVED-ONLY — not the intended long-term primary path.
            # Used only when both CapabilityResolver and CapabilityRegistry are
            # unavailable or empty.  New MCP servers should register via
            # mcp_loader → CapabilityRegistry → CapabilityResolver instead.
            try:
                from core.mcp_loader import mcp_loader

                for server_info in mcp_loader.list_servers():
                    server_id = server_info.get("id", "")
                    if server_info.get("status") != "running":
                        continue
                    # list_tools 是 async，但 _collect_tools 是 sync
                    # 使用已缓存的 tools 列表（如果可用）
                    cached_tools = server_info.get("tools", [])
                    for tool in cached_tools:
                        tool_name = tool.get("name", "")
                        if not tool_name:
                            continue
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": f"mcp__{server_id}__{tool_name}",
                                "description": tool.get("description", f"MCP tool: {tool_name}"),
                                "parameters": tool.get("inputSchema", tool.get("parameters", {
                                    "type": "object", "properties": {}
                                })),
                            },
                        })
            except Exception as e:
                logger.debug(f"收集 MCP 工具失败: {e}")

            # ── LEGACY COMPATIBILITY FALLBACK: Skill direct scan ──
            # DERIVED-ONLY — not the intended long-term primary path.
            # Used only when both CapabilityResolver and CapabilityRegistry are
            # unavailable or empty.  New Skills should register via
            # skill_loader → CapabilityRegistry → CapabilityResolver instead.
            try:
                from core.skill_loader import skill_loader

                for skill_info in skill_loader.list_skills():
                    skill_id = skill_info.get("id", "")
                    if not skill_id or skill_info.get("status") == "error":
                        continue
                    # 使用 to_mcp_tool_schema 获取正确的 JSON Schema
                    mcp_schema = skill_loader.to_mcp_tool_schema(skill_id)
                    params = mcp_schema.get("inputSchema", _DEFAULT_SKILL_SCHEMA) if mcp_schema else _DEFAULT_SKILL_SCHEMA
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"skill__{skill_id}",
                            "description": skill_info.get("description", f"Skill: {skill_id}"),
                            "parameters": params,
                        },
                    })
            except Exception as e:
                logger.debug(f"收集 Skill 工具失败: {e}")

        # ── 层 1.5: MCP Gateway 自造工具 (始终收集，不在能力总线) ──
        try:
            from core.mcp_gateway import get_mcp_gateway
            gateway = get_mcp_gateway()
            for tool in gateway.list_generated_tools():
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"mcp__gateway__{tool_name}",
                        "description": tool.get("description", f"Generated tool: {tool_name}"),
                        "parameters": tool.get("parameters", {
                            "type": "object", "properties": {}
                        }),
                    },
                })
        except Exception as e:
            logger.debug(f"收集 MCP Gateway 工具失败: {e}")

        # ── 层 3: Node 节点操作 (静态 action 目录 + 动态发现全量节点) ──
        try:
            import json as _json
            import os as _os
            registry_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(__file__)), "config", "node_registry.json"
            )
            # 加载注册表获取节点名称和 node_key 映射
            registry_names: Dict[str, str] = {}  # node_id → node_name
            if _os.path.exists(registry_path):
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = _json.load(f)
                for node_key, node_info in registry.get("nodes", {}).items():
                    nid = node_info.get("id", "")
                    if nid and node_info.get("status") == "active" and node_info.get("has_main"):
                        registry_names[nid] = node_info.get("name", nid)
                        self._node_id_to_key[nid] = node_key

            # 已注册的工具名集合，避免重复添加
            # 预置规范路径已收集的节点工具名，防止与 Layer 2 规范路径重复
            _registered_tool_names: set = set(_node_catalog_tool_names)

            # 从静态目录生成工具列表（_CORE_NODE_ACTIONS 作为高优先级回退）
            for node_id, actions_map in self._CORE_NODE_ACTIONS.items():
                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in actions_map.items():
                    tool_name_key = f"node__{node_id}__{action_name}"
                    if tool_name_key not in _registered_tool_names:
                        _registered_tool_names.add(tool_name_key)
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": tool_name_key,
                                "description": f"Node {node_name}: {action_desc}",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "params": {"type": "object", "description": "操作参数"}
                                    },
                                },
                            },
                        })

            # 动态发现：遍历注册表中所有节点，尝试从 fusion_entry.py 获取 actions
            # 已在 _CORE_NODE_ACTIONS 中覆盖的节点仍可通过动态发现补充额外 action
            _DYNAMIC_SCAN_LIMIT = self.NODE_DYNAMIC_TOOL_LIMIT  # LLM function calling 建议上限
            _dynamic_added = 0
            for node_id, node_key in list(self._node_id_to_key.items()):
                if _dynamic_added >= _DYNAMIC_SCAN_LIMIT:
                    break
                # 先检查缓存
                if node_id in self._node_actions_cache:
                    discovered = self._node_actions_cache[node_id]
                else:
                    try:
                        discovered = self._discover_node_actions(node_id, node_key)
                        self._node_actions_cache[node_id] = discovered
                    except Exception as _e:
                        logger.debug(f"动态发现节点 {node_id} actions 失败: {_e}")
                        self._node_actions_cache[node_id] = {}
                        discovered = {}

                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in discovered.items():
                    tool_name_key = f"node__{node_id}__{action_name}"
                    if tool_name_key not in _registered_tool_names:
                        _registered_tool_names.add(tool_name_key)
                        _dynamic_added += 1
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": tool_name_key,
                                "description": f"Node {node_name}: {action_desc}",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "params": {"type": "object", "description": "操作参数"}
                                    },
                                },
                            },
                        })

            logger.debug(
                "Node 工具收集: 静态 %d + 动态发现 %d，注册表节点 %d 个",
                len(self._CORE_NODE_ACTIONS),
                _dynamic_added,
                len(self._node_id_to_key),
            )
        except Exception as e:
            logger.debug(f"收集 Node 工具失败: {e}")

        logger.info(f"工具总线收集完成: {len(tools)} 个工具")

        # ── GitHub 插件工具 (始终收集) ─────────────────────────────────────
        tools.extend(_GITHUB_BUILTIN_TOOLS)

        # ── Academic 学术检索工具 (始终收集) ─────────────────────────────
        tools.extend(_ACADEMIC_BUILTIN_TOOLS)

        # ── Engineering loop tools (始终收集, PR-6) ─────────────────────
        tools.extend(_ENGINEER_BUILTIN_TOOLS)

        # ── Governed system resource layer tools (始终收集, PR-7) ─────────
        tools.extend(_RESOURCE_BUILTIN_TOOLS)

        return tools

    async def _dispatch_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """根据工具名前缀分发到对应执行器

        PR-001: This method now delegates to :class:`~core.capabilities.canonical_dispatcher.CanonicalDispatcher`
        as the single canonical execution path.  The inline dispatch logic
        below is retained as a compatibility fallback when the dispatcher is
        unavailable.

        Args:
            tool_name: 格式为 "mcp__server__tool" / "skill__id" / "node__id__action"
            arguments: 工具参数

        Returns:
            {"success": bool, "result": Any, "error": Optional[str]}
        """
        # PR-001: Primary path — delegate to CanonicalDispatcher.
        _dispatcher = getattr(self, "_capability_dispatcher", None)
        if _dispatcher is not None:
            try:
                _dr = await _dispatcher.dispatch(
                    tool_name,
                    arguments,
                    device_id=getattr(self, "_current_device_id", "") or "",
                    session_id=getattr(self, "_current_session_id", "") or "",
                    trace_id=getattr(self, "_current_trace_id", "") or "",
                )
                return _dr.as_legacy_dict()
            except Exception as _exc:
                logger.warning(
                    "CanonicalDispatcher.dispatch raised unexpectedly [%s]: %s — falling back to inline path",
                    tool_name,
                    _exc,
                )
                # Fall through to the compatibility inline path below.

        # PR-001: Compatibility/fallback inline path.
        # This block remains authoritative only when the canonical dispatcher
        # is unavailable (e.g. import error during startup).  It is explicitly
        # secondary to the dispatcher above.
        # PR-8: emit SKILL_INVOKED before dispatch so the trace is recorded
        # even if the call fails.
        _pr8_trace_id = getattr(self, "_current_trace_id", None)
        _pr8_session_id = getattr(self, "_current_session_id", None)
        try:
            from core.state_event_bus import emit as _seb_emit, StateEventType
            _seb_emit(
                StateEventType.SKILL_INVOKED,
                source="openclawd",
                payload={"tool_name": tool_name},
                trace_id=_pr8_trace_id,
                runtime_session_id=_pr8_session_id,
            )
        except Exception:
            pass

        # Phase 9: 工具调用权限检查
        if self._tool_permission_checker:
            try:
                check = self._tool_permission_checker.check(
                    tool_name=tool_name,
                    session_id=getattr(self, "_current_session_id", ""),
                    device_id=getattr(self, "_current_device_id", ""),
                )
                if not check.allowed:
                    logger.warning(f"工具调用被拒绝: {tool_name} — {check.reason}")
                    return {"success": False, "error": f"权限拒绝: {check.reason}"}
                if check.requires_confirmation:
                    return {
                        "success": False,
                        "needs_confirmation": True,
                        "tool": tool_name,
                        "risk_level": check.risk_level,
                        "error": f"操作 [{tool_name}] 需要用户确认（风险等级: {check.risk_level}）",
                    }
            except Exception as e:
                logger.debug(f"权限检查异常（放行）: {e}")

        try:
            if tool_name.startswith("mcp__"):
                parts = tool_name.split("__", 2)
                if len(parts) < 3:
                    return {"success": False, "error": f"无效 MCP 工具名: {tool_name}"}
                server_id, mcp_tool_name = parts[1], parts[2]

                # Emit contract-level observability for every MCP call.
                from core.skill_contract import (
                    SkillRequest as _SkillRequest,
                    SkillMetrics as _SkillMetrics,
                    SkillResponse as _SkillResponse,
                    SkillErrorCode as _SkillErrorCode,
                )
                from core.skill_registry import get_skill_registry as _get_registry
                import time as _time

                _mcp_req = _SkillRequest(
                    skill_name=tool_name,
                    inputs=arguments,
                    device_id=getattr(self, "_current_device_id", ""),
                    runtime_session_id=getattr(self, "_current_session_id", ""),
                    caller="openclawd",
                )
                _mcp_metrics = _SkillMetrics(started_at=_time.time(), executor=f"mcp:{server_id}")

                # 特殊处理 gateway 自造工具
                if server_id == "gateway":
                    try:
                        from core.mcp_gateway import get_mcp_gateway
                        gateway = get_mcp_gateway()
                        result = await gateway.execute_tool(mcp_tool_name, arguments)
                        _mcp_metrics.finish()
                        _get_registry()._emit_log(
                            _mcp_req,
                            _SkillResponse.success(tool_name, _mcp_req.trace_id, result, _mcp_metrics),
                        )
                        return {"success": True, "result": result}
                    except Exception as e:
                        _mcp_metrics.finish()
                        _get_registry()._emit_log(
                            _mcp_req,
                            _SkillResponse.failure(tool_name, _mcp_req.trace_id, _SkillErrorCode.EXECUTION_ERROR, str(e), metrics=_mcp_metrics),
                        )
                        return {"success": False, "error": f"Gateway 工具执行失败: {e}"}

                from core.mcp_loader import mcp_loader
                try:
                    result = await mcp_loader.call_tool(server_id, mcp_tool_name, arguments)
                    _mcp_metrics.finish()
                    _get_registry()._emit_log(
                        _mcp_req,
                        _SkillResponse.success(tool_name, _mcp_req.trace_id, result, _mcp_metrics),
                    )
                    return {"success": True, "result": result}
                except Exception as e:
                    _mcp_metrics.finish()
                    _get_registry()._emit_log(
                        _mcp_req,
                        _SkillResponse.failure(tool_name, _mcp_req.trace_id, _SkillErrorCode.EXECUTION_ERROR, str(e), metrics=_mcp_metrics),
                    )
                    raise

            elif tool_name.startswith("skill__"):
                skill_id = tool_name[7:]  # len("skill__") == 7
                # Route all skill invocations through the unified Skill Registry
                # so every call is validated, permission-checked, and observed.
                from core.skill_contract import SkillRequest as _SkillRequest
                from core.skill_registry import get_skill_registry as _get_registry
                from core.skill_loader import skill_loader as _skill_loader

                _registry = _get_registry()

                # Lazily register an adapter for this skill if needed.
                if not _registry.has_skill(tool_name):
                    def _make_skill_adapter(_sid: str):
                        async def _adapter(**kwargs):
                            return await _skill_loader.execute(_sid, **kwargs)
                        return _adapter
                    _registry.register_skill(
                        name=tool_name,
                        handler=_make_skill_adapter(skill_id),
                        source="skill_loader_lazy",
                        description=f"Adapter for skill_loader skill '{skill_id}'",
                    )

                _req = _SkillRequest(
                    skill_name=tool_name,
                    inputs=arguments,
                    device_id=getattr(self, "_current_device_id", ""),
                    runtime_session_id=getattr(self, "_current_session_id", ""),
                    caller="openclawd",
                )
                _resp = await _registry.invoke(_req)
                if _resp.ok:
                    return {"success": True, "result": _resp.outputs}
                _err = _resp.first_error
                return {
                    "success": False,
                    "error": _err.message if _err else "Skill invocation failed",
                }

            elif tool_name.startswith("node__"):
                parts = tool_name.split("__", 2)
                if len(parts) < 3:
                    return {"success": False, "error": f"无效 Node 工具名: {tool_name}"}
                node_id, action_name = parts[1], parts[2]
                # 通过已验证的 fusion_entry 执行路径
                from core.routes._helpers import _load_node, _execute_node, nodes_root
                import os as _os

                node_key = self._find_node_key(node_id)
                if not node_key:
                    return {"success": False, "error": f"节点 {node_id} 未在注册表中"}

                node_dir = _os.path.join(nodes_root, node_key)
                fusion_path = _os.path.join(node_dir, "fusion_entry.py")
                if not _os.path.exists(fusion_path):
                    return {"success": False, "error": f"节点 {node_id} 无 fusion_entry.py"}

                node_info = _load_node(node_id, node_dir, fusion_path)
                if not node_info:
                    return {"success": False, "error": f"节点 {node_id} 加载失败"}

                params = arguments.get("params", arguments)
                result = await _execute_node(
                    node_info, action_name, params if isinstance(params, dict) else {}
                )
                return {"success": True, "result": result}

            elif tool_name.startswith("github__"):
                # GitHub addon tools: github__install, github__uninstall, github__list
                action = tool_name[8:]  # strip "github__"
                return await self._dispatch_github_tool(action, arguments)

            elif tool_name.startswith("academic__"):
                # Academic system resource tools: academic__search, academic__ingest, academic__recall
                action = tool_name[10:]  # strip "academic__"
                return await self._dispatch_academic_tool(action, arguments)

            elif tool_name.startswith("engineer__"):
                # Mediated engineering loop tools (PR-6): engineer__diagnose, __plan, __apply, etc.
                action = tool_name[10:]  # strip "engineer__"
                return await self._dispatch_engineer_tool(action, arguments)

            elif tool_name.startswith("resource__"):
                # Governed system resource layer tools (PR-7): resource__list, __status, etc.
                action = tool_name[10:]  # strip "resource__"
                return await self._dispatch_resource_tool(action, arguments)

            else:
                return {"success": False, "error": f"未知工具前缀: {tool_name}"}

        except Exception as e:
            logger.warning(f"工具执行失败 [{tool_name}]: {e}")
            # PR-8: emit SKILL_FAILED on unhandled exception.
            try:
                from core.state_event_bus import emit as _seb_emit, StateEventType
                _seb_emit(
                    StateEventType.SKILL_FAILED,
                    source="openclawd",
                    payload={"tool_name": tool_name, "error": str(e)},
                    trace_id=_pr8_trace_id,
                    runtime_session_id=_pr8_session_id,
                )
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    # ========================================================================
    # GitHub Addon Tools — github__install / github__uninstall / github__list
    # ========================================================================

    async def _dispatch_github_tool(self, action: str, arguments: dict) -> dict:
        """Dispatch GitHub system resource tool calls.

        GitHub is a first-class system resource with three roles:
        1. **Addon source** — install/uninstall/list GitHub-sourced MCP tools
           and Skills.  Handled by ``GitHubInstaller``.
        2. **Knowledge source** — ingest repo content into the unified
           Knowledge Core.  Handled by ``GitHubRepoIngester.ingest_repo()``.
        3. **Engineering context source** — retrieve structured repo context
           for planning/coding flows.  Handled by
           ``GitHubRepoIngester.get_repo_context()``.

        Supported actions:
            install   — install MCP tool or Skill from GitHub URL.
            uninstall — uninstall addon by name.
            list      — list all installed GitHub addons.
            status    — installer status.
            ingest    — ingest repo content into Knowledge Core.
            context   — retrieve engineering context from a GitHub repo.

        Args:
            action:    Action name (strip of ``github__`` prefix).
            arguments: Tool arguments from LLM tool_calls.

        Returns:
            ``{"success": bool, "result": Any, "error": Optional[str]}``
        """
        try:
            from core.github_installer import get_github_installer
            installer = get_github_installer()

            if action == "install":
                url = arguments.get("url", "")
                if not url:
                    return {"success": False, "error": "github__install requires 'url' argument"}
                result = await installer.install(
                    url=url,
                    ref=arguments.get("ref"),
                    addon_type=arguments.get("type"),
                    dry_run=bool(arguments.get("dry_run", False)),
                )
                return result

            elif action == "uninstall":
                name = arguments.get("name", "")
                if not name:
                    return {"success": False, "error": "github__uninstall requires 'name' argument"}
                return await installer.uninstall(name)

            elif action == "list":
                return installer.list_installed()

            elif action == "status":
                return installer.get_status()

            elif action == "ingest":
                url = arguments.get("url", "")
                if not url:
                    return {"success": False, "error": "github__ingest requires 'url' argument"}
                from core.github_installer import get_github_ingester
                ingester = get_github_ingester()
                return await ingester.ingest_repo(
                    url=url,
                    ref=arguments.get("ref"),
                    include_code=bool(arguments.get("include_code", False)),
                )

            elif action == "context":
                url = arguments.get("url", "")
                if not url:
                    return {"success": False, "error": "github__context requires 'url' argument"}
                from core.github_installer import get_github_ingester
                ingester = get_github_ingester()
                return ingester.get_repo_context(
                    url=url,
                    ref=arguments.get("ref"),
                )

            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown github action: '{action}'. "
                        "Valid actions: install, uninstall, list, status, ingest, context."
                    ),
                }
        except Exception as exc:
            logger.warning("_dispatch_github_tool '%s' failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

    # ========================================================================
    # Academic System Resource Tools — academic__search / __ingest / __recall
    # ========================================================================

    async def _dispatch_academic_tool(self, action: str, arguments: dict) -> dict:
        """Dispatch academic system resource tool calls.

        Academic search is a first-class system resource with three roles:
        1. **Search source** — query arXiv/Semantic Scholar/PubMed/IEEE Xplore.
           Handled by ``AcademicRetriever.search()``.
        2. **Knowledge source** — ingest paper metadata/abstracts into the
           unified Knowledge Core.  Handled by
           ``AcademicRetriever.ingest_paper()``.
        3. **Recall source** — retrieve previously-ingested academic knowledge
           via the unified RAG path.  Handled by
           ``AcademicRetriever.recall()``.

        Supported actions:
            search  — search academic databases, optionally ingest results.
            ingest  — ingest a single paper dict into Knowledge Core.
            recall  — recall academic knowledge from Knowledge Core.

        Args:
            action:    Action name (strip of ``academic__`` prefix).
            arguments: Tool arguments from LLM tool_calls.

        Returns:
            ``{"success": bool, "result": Any, "error": Optional[str]}``
        """
        try:
            from core.academic_retrieval import get_academic_retriever
            retriever = get_academic_retriever()

            if action == "search":
                query = arguments.get("query", "")
                if not query:
                    return {"success": False, "error": "academic__search requires 'query' argument"}
                try:
                    max_results = int(arguments.get("max_results", 10))
                except (TypeError, ValueError):
                    max_results = 10
                result = await retriever.search(
                    query=query,
                    source=arguments.get("source", "all"),
                    max_results=max_results,
                    ingest=bool(arguments.get("ingest", True)),
                )
                return result

            elif action == "ingest":
                paper = arguments.get("paper")
                if not paper or not isinstance(paper, dict):
                    return {"success": False, "error": "academic__ingest requires 'paper' argument (dict)"}
                entry_id = retriever.ingest_paper(paper)
                return {
                    "success": True,
                    "entry_id": entry_id,
                    "paper_id": paper.get("paper_id", ""),
                    "title": paper.get("title", ""),
                    "source_type": "academic",
                    "source": f"academic://{paper.get('source', 'unknown')}/{paper.get('paper_id', '')}",
                }

            elif action == "recall":
                query = arguments.get("query", "")
                if not query:
                    return {"success": False, "error": "academic__recall requires 'query' argument"}
                try:
                    top_k = int(arguments.get("top_k", 5))
                except (TypeError, ValueError):
                    top_k = 5
                return retriever.recall(
                    query=query,
                    top_k=top_k,
                )

            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown academic action: '{action}'. "
                        "Valid actions: search, ingest, recall."
                    ),
                }
        except Exception as exc:
            logger.warning("_dispatch_academic_tool '%s' failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

    # ========================================================================
    # Engineering Loop Tools — PR-6 mediated self-healing
    # engineer__diagnose / __context / __plan / __apply / __validate /
    # __record / __status
    # ========================================================================

    async def _dispatch_engineer_tool(self, action: str, arguments: dict) -> dict:
        """Dispatch ``engineer__*`` tool calls to :class:`~core.self_improvement.SelfHealingLoop`.

        All self-healing and code-improvement actions flow through the mediated
        engineering loop rather than direct mutation paths.

        Args:
            action:    Action name (strip of ``engineer__`` prefix).
            arguments: Tool arguments dict from the LLM function call.

        Returns:
            ``{"success": bool, ...}``
        """
        try:
            from core.self_improvement import get_self_healing_loop

            loop = get_self_healing_loop()

            if action == "diagnose":
                issue_summary = arguments.get("issue_summary", "")
                if not issue_summary:
                    return {"success": False, "error": "engineer__diagnose requires 'issue_summary' argument"}
                source = arguments.get("source", "openclawd")
                proposal = loop.submit_diagnosis(
                    issue_summary=issue_summary,
                    source=source,
                    metadata=arguments.get("metadata", {}),
                )
                return {
                    "success": True,
                    "proposal_id": proposal.proposal_id,
                    "stage": proposal.stage.value,
                    "issue_summary": proposal.issue_summary,
                    "source": proposal.source,
                }

            elif action == "context":
                proposal_id = arguments.get("proposal_id", "")
                if not proposal_id:
                    return {"success": False, "error": "engineer__context requires 'proposal_id' argument"}
                context = arguments.get("context", {})
                if not isinstance(context, dict):
                    logger.warning(
                        "_dispatch_engineer_tool 'context': expected dict for 'context', got %s — wrapping",
                        type(context).__name__,
                    )
                    context = {"raw": str(context)}
                return loop.attach_context(proposal_id=proposal_id, context=context)

            elif action == "plan":
                proposal_id = arguments.get("proposal_id", "")
                patch_content = arguments.get("patch_content", "")
                if not proposal_id:
                    return {"success": False, "error": "engineer__plan requires 'proposal_id' argument"}
                if not patch_content:
                    return {"success": False, "error": "engineer__plan requires 'patch_content' argument"}
                return loop.plan_patch(
                    proposal_id=proposal_id,
                    patch_content=patch_content,
                    target_files=arguments.get("target_files", []),
                )

            elif action == "apply":
                proposal_id = arguments.get("proposal_id", "")
                if not proposal_id:
                    return {"success": False, "error": "engineer__apply requires 'proposal_id' argument"}
                return loop.apply_patch(
                    proposal_id=proposal_id,
                    apply_metadata=arguments.get("apply_metadata", {}),
                )

            elif action == "validate":
                proposal_id = arguments.get("proposal_id", "")
                if not proposal_id:
                    return {"success": False, "error": "engineer__validate requires 'proposal_id' argument"}
                passed = bool(arguments.get("passed", True))
                notes = arguments.get("notes", "")
                return loop.validate(proposal_id=proposal_id, validation_notes=notes, passed=passed)

            elif action == "record":
                proposal_id = arguments.get("proposal_id", "")
                if not proposal_id:
                    return {"success": False, "error": "engineer__record requires 'proposal_id' argument"}
                return loop.record_outcome(proposal_id=proposal_id)

            elif action == "status":
                snap = loop.snapshot()
                return {"success": True, **snap.to_dict()}

            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown engineer action: '{action}'. "
                        "Valid actions: diagnose, context, plan, apply, validate, record, status."
                    ),
                }
        except Exception as exc:
            logger.warning("_dispatch_engineer_tool '%s' failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

    # ========================================================================
    # Governed System Resource Layer Tools — PR-7
    # resource__list / resource__status / resource__health / resource__lookup
    # ========================================================================

    async def _dispatch_resource_tool(self, action: str, arguments: dict) -> dict:
        """Dispatch ``resource__*`` tool calls to :class:`~core.system_resource.SystemResourceRegistry`.

        The governed system resource layer provides OpenClawd with a unified
        view of all external and semi-external system-facing resources
        (GitHub, academic, device, local tools, engineering loop, etc.)
        through a single canonical registry.

        Supported actions:
            list    — list all registered resources, optionally filtered by type.
            status  — registry-level status snapshot (counts / health summary).
            health  — update health/availability for a specific resource.
            lookup  — look up a resource by resource_id or source URI.

        Args:
            action:    Action name (stripped of ``resource__`` prefix).
            arguments: Tool arguments dict from the LLM function call.

        Returns:
            ``{"success": bool, ...}``
        """
        try:
            from core.system_resource import (
                get_system_resource_registry,
                SystemResourceType,
                SystemResourceHealth,
                SystemResourceAvailability,
            )

            registry = get_system_resource_registry()

            if action == "list":
                type_filter = arguments.get("resource_type")
                if type_filter:
                    try:
                        rtype = SystemResourceType(type_filter)
                    except ValueError:
                        return {
                            "success": False,
                            "error": (
                                f"Unknown resource_type: '{type_filter}'. "
                                "Valid values: github, academic, device, local_tool, "
                                "engineering, mcp, skill, node, builtin, unknown."
                            ),
                        }
                    records = registry.list_by_type(rtype)
                else:
                    records = registry.list_all()
                return {
                    "success": True,
                    "resources": [r.to_dict() for r in records],
                    "count": len(records),
                }

            elif action == "status":
                snap = registry.snapshot()
                return {"success": True, **snap.to_dict()}

            elif action == "health":
                resource_id = arguments.get("resource_id", "")
                if not resource_id:
                    return {
                        "success": False,
                        "error": "resource__health requires 'resource_id' argument",
                    }
                health_str = arguments.get("health", "")
                if not health_str:
                    return {
                        "success": False,
                        "error": "resource__health requires 'health' argument",
                    }
                try:
                    health = SystemResourceHealth(health_str)
                except ValueError:
                    return {
                        "success": False,
                        "error": (
                            f"Unknown health value: '{health_str}'. "
                            "Valid values: healthy, degraded, unavailable, unknown."
                        ),
                    }
                availability_update: Optional[SystemResourceAvailability] = None
                avail_str = arguments.get("availability")
                if avail_str:
                    try:
                        availability_update = SystemResourceAvailability(avail_str)
                    except ValueError:
                        pass  # ignore invalid availability; health update still proceeds
                updated = registry.set_health(
                    resource_id=resource_id,
                    health=health,
                    availability=availability_update,
                )
                if not updated:
                    return {
                        "success": False,
                        "error": f"resource_id '{resource_id}' not found in registry",
                    }
                return {
                    "success": True,
                    "resource_id": resource_id,
                    "health": health.value,
                    "availability": availability_update.value if availability_update is not None else None,
                }

            elif action == "lookup":
                resource_id = arguments.get("resource_id")
                source = arguments.get("source")
                if resource_id:
                    record = registry.lookup(resource_id)
                elif source:
                    record = registry.lookup_by_source(source)
                else:
                    return {
                        "success": False,
                        "error": (
                            "resource__lookup requires either 'resource_id' or 'source' argument"
                        ),
                    }
                if record is None:
                    return {"success": False, "error": "Resource not found"}
                return {"success": True, "resource": record.to_dict()}

            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown resource action: '{action}'. "
                        "Valid actions: list, status, health, lookup."
                    ),
                }
        except Exception as exc:
            logger.warning("_dispatch_resource_tool '%s' failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

    # ========================================================================
    # Node 辅助方法
    # ========================================================================

    def _find_node_key(self, node_id: str) -> Optional[str]:
        """根据 node_id 在注册表/缓存中查找 node_key (如 'Node_06_Filesystem')"""
        # 先查内存缓存
        if node_id in self._node_id_to_key:
            return self._node_id_to_key[node_id]
        # 回退到文件读取
        try:
            import json, os
            registry_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config", "node_registry.json"
            )
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for key, info in registry.get("nodes", {}).items():
                if info.get("id") == node_id:
                    self._node_id_to_key[node_id] = key
                    return key
        except Exception:
            pass
        return None

    def _discover_node_actions(self, node_id: str, node_key: str) -> Dict[str, str]:
        """通过加载 fusion_entry 发现节点的可用 actions

        Returns:
            {action_name: description} — 不含 status/help 元操作
        """
        try:
            from core.routes._helpers import _load_node, nodes_root
            import os
            import inspect
            import asyncio

            node_dir = os.path.join(nodes_root, node_key)
            fusion_path = os.path.join(node_dir, "fusion_entry.py")
            if not os.path.exists(fusion_path):
                return {}

            node_info = _load_node(node_id, node_dir, fusion_path)
            if not node_info:
                return {}

            def _call_sync(action: str):
                """调用 execute，处理 sync/async 两种模式"""
                try:
                    if node_info["type"] == "function":
                        func = node_info["execute"]
                        if inspect.iscoroutinefunction(func):
                            # 尝试在新事件循环中运行（仅在非 async 上下文有效）
                            try:
                                loop = asyncio.get_running_loop()
                                # 已在运行的 loop 中 → asyncio.run 会崩溃，跳过
                                return None
                            except RuntimeError:
                                return asyncio.run(func(action, {}))
                        else:
                            return func(action, {})
                    else:
                        method = node_info["instance"].execute
                        if inspect.iscoroutinefunction(method):
                            try:
                                loop = asyncio.get_running_loop()
                                return None
                            except RuntimeError:
                                return asyncio.run(method(action))
                        else:
                            return method(action)
                except Exception:
                    return None

            _skip = {"status", "help"}

            # 优先尝试 help → 获取带描述的 actions dict
            try:
                help_result = _call_sync("help")
                if isinstance(help_result, dict):
                    actions_map = help_result.get("actions", {})
                    if isinstance(actions_map, dict) and actions_map:
                        return {k: str(v) for k, v in actions_map.items() if k not in _skip}
            except Exception:
                pass

            # 退化到 status → 获取 available_actions 列表
            try:
                status_result = _call_sync("status")
                if isinstance(status_result, dict):
                    actions = status_result.get("available_actions", status_result.get("actions", []))
                    if isinstance(actions, dict):
                        return {k: str(v) for k, v in actions.items() if k not in _skip}
                    if isinstance(actions, list):
                        return {a: f"Execute {a}" for a in actions
                                if isinstance(a, str) and a not in _skip}
            except Exception:
                pass

            return {}
        except Exception as e:
            logger.debug(f"发现节点 {node_id} ({node_key}) actions 失败: {e}")
            return {}

    # ========================================================================
    # ReAct 工具调用循环
    # ========================================================================

    async def _react_loop(
        self,
        messages: List[Dict],
        tools: List[Dict],
        max_iterations: int = 10,
        task_type: Optional[str] = None,
        timeout: float = 120.0,
    ) -> dict:
        """ReAct 工具调用循环 (含总超时保护)

        循环流程:
          1. 调用 LLM（带 tools）
          2. 如果 LLM 返回 tool_calls → 执行每个工具 → 追加结果到 messages → 继续
          3. 如果 LLM 返回纯文本（无 tool_calls） → break，返回最终文本

        Args:
            timeout: 总超时秒数，防止工具挂起导致系统永久阻塞

        Returns:
            dict 兼容格式 (内部使用 ToolCallRecord 结构化记录)
        """
        import asyncio as _asyncio
        import time as _time
        from core.multi_llm_router import get_llm_router
        from core.schemas.tool_call import ToolCallRecord, ToolCallStatus

        router = get_llm_router()

        tool_records: List[ToolCallRecord] = []
        last_response = None
        total_tokens = 0

        # Phase 9: 频率限制计数器
        _total_tool_calls = 0
        _MAX_TOOL_CALLS = 20  # 单次请求最大工具调用次数
        _consecutive_same: Dict[str, int] = {}  # 连续同名工具计数
        _last_tool_name = ""

        async def _inner_loop():
            nonlocal last_response, total_tokens
            nonlocal _total_tool_calls, _last_tool_name

            for iteration in range(max_iterations):
                response = await router.chat(
                    messages=messages,
                    tools=tools if tools else None,
                    task_type=task_type,
                    max_tokens=4096,
                )
                last_response = response
                total_tokens += (response.input_tokens + response.output_tokens)

                if not response.tool_calls:
                    # 无工具调用 → 最终回复
                    break

                # 先把 assistant 的 tool_calls 消息追加到 messages
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                }
                if response.tool_calls:
                    assistant_msg["tool_calls"] = response.tool_calls
                messages.append(assistant_msg)

                for tc in response.tool_calls:
                    tc_func = tc.get("function", {})
                    tc_name = tc_func.get("name", "")
                    tc_id = tc.get("id", f"call_{tc_name}")

                    # 解析参数
                    try:
                        import json as _json
                        tc_args = _json.loads(tc_func.get("arguments", "{}"))
                    except (ValueError, TypeError):
                        tc_args = {}

                    logger.info(f"ReAct 迭代 {iteration+1}: 调用工具 {tc_name}")

                    # Phase 9: 频率限制检查
                    _total_tool_calls += 1
                    if _total_tool_calls > _MAX_TOOL_CALLS:
                        logger.warning(
                            f"ReAct 工具调用总次数超限 ({_MAX_TOOL_CALLS})，强制终止"
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"[系统] 工具调用次数已达上限 ({_MAX_TOOL_CALLS})，请直接给出最终回答",
                        })
                        break

                    # 连续同一工具检查
                    if tc_name == _last_tool_name:
                        _consecutive_same[tc_name] = _consecutive_same.get(tc_name, 1) + 1
                        if _consecutive_same[tc_name] >= 3:
                            logger.warning(
                                f"连续调用同一工具 {tc_name} 达 3 次，疑似幻觉循环，终止"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"[系统] 检测到重复调用 {tc_name}，请直接给出最终回答",
                            })
                            break
                    else:
                        _consecutive_same.clear()
                    _last_tool_name = tc_name

                    # 执行工具 (带计时 + 单工具超时)
                    t0 = _time.time()
                    try:
                        result = await _asyncio.wait_for(
                            self._dispatch_tool_call(tc_name, tc_args),
                            timeout=30.0  # 单个工具调用最多 30 秒
                        )
                    except _asyncio.TimeoutError:
                        result = {"success": False, "error": f"工具 {tc_name} 执行超时 (30s)"}
                    elapsed_ms = (_time.time() - t0) * 1000

                    # 构造结构化记录
                    layer = ToolCallRecord.classify_layer(tc_name)
                    status = ToolCallStatus.SUCCESS if result.get("success", True) else ToolCallStatus.ERROR
                    result_str = str(result.get("result", result.get("error", "")))
                    tool_records.append(ToolCallRecord(
                        tool_name=tc_name,
                        layer=layer,
                        arguments=tc_args,
                        result=result_str[:2000],
                        status=status,
                        error=result.get("error") if not result.get("success", True) else None,
                        latency_ms=round(elapsed_ms, 1),
                        iteration=iteration,
                    ))

                    # 追加 tool result 到 messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str[:4000],
                    })

        try:
            await _asyncio.wait_for(_inner_loop(), timeout=timeout)
        except _asyncio.TimeoutError:
            logger.warning(f"ReAct 循环总超时 ({timeout}s)，返回已有内容")

        final_text = last_response.content if last_response else ""
        timed_out = last_response is None  # 如果整个循环超时还没拿到 response

        # 返回兼容 dict (同时携带结构化 tool_records)
        return {
            "response": final_text if not timed_out else "处理超时，请稍后重试",
            "tool_calls_log": [r.model_dump() for r in tool_records],
            "tool_records": tool_records,  # 结构化版本
            "iterations": len(tool_records),
            "provider": last_response.provider if last_response else "",
            "model": last_response.model if last_response else "",
            "total_tokens": total_tokens,
            "timeout": timed_out,
        }

    # ========================================================================
    # handle_chat — 对话（带 ReAct 工具调用能力）
    # ========================================================================

    async def handle_chat(self, message: str, session_id: str) -> dict:
        """对话处理 — 使用 ReAct 循环，支持自动工具调用

        流程: 构建 messages → 收集 tools → _react_loop() → 返回结果
        如果没有可用工具，退化为普通 LLM 对话。

        Args:
            message: 用户消息
            session_id: 会话 ID

        Returns:
            响应 dict
        """
        try:
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()

            if not router.is_available():
                return {
                    "success": False,
                    "response": (
                        "LLM 服务未配置。请设置 API Key "
                        "(OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY)。"
                    ),
                }

            # 构建消息列表
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是 Galaxy 智能助手 (OpenClawd)，一个桌面级超级 AI 智能体。\n"
                        "你可以帮助用户进行对话、任务管理、设备控制、代码执行等操作。\n"
                        "当你需要执行操作时，请使用提供的工具。\n"
                        "如果没有合适的工具，直接用文字回答。"
                    ),
                },
            ]

            # Block-3: Inject long-term memory preferences as an additive system
            # context message.  Best-effort — failures must not block the chat path.
            try:
                from core.cognitive.long_term_memory import get_long_term_memory
                _ltm = get_long_term_memory()
                _prefs = _ltm.retrieve_all(namespace="preferences")
                if _prefs:
                    _pref_lines = [
                        f"- {e['key']}: {e['value']}" for e in _prefs[:10]
                    ]
                    messages.append({
                        "role": "system",
                        "content": (
                            "[Long-term memory — user preferences]\n"
                            + "\n".join(_pref_lines)
                        ),
                    })
            except Exception as _ltm_err:
                logger.debug("LongTermMemory inject failed (non-fatal): %s", _ltm_err)

            # Block-3: Use working memory entries when available; fall back to
            # _session_memory so all existing behaviour is preserved.
            _wm_entries = []
            try:
                from core.cognitive.working_memory import get_working_memory
                _wm_entries = get_working_memory().get(
                    session_id=session_id, last_n=10
                )
            except Exception as _wm_err:
                logger.debug("WorkingMemory.get failed (non-fatal): %s", _wm_err)

            # 添加会话历史
            session_history = self._session_memory.get(session_id, [])
            # Block-3: prefer working memory entries; fall back to session_memory preserving
            # original dict structure for full backward compatibility.
            if _wm_entries:
                for turn in _wm_entries:
                    messages.append({"role": turn["role"], "content": turn["content"]})
            else:
                for turn in session_history[-10:]:
                    messages.append(turn)

            messages.append({"role": "user", "content": message})

            # 收集可用工具
            tools = self._collect_tools()

            # 计算复杂度 (结构化向量)
            cv = router._compute_complexity_vector(messages, tools if tools else None)

            # 使用 ReAct 循环
            result = await self._react_loop(messages, tools)

            # 构建层级使用统计
            tool_records = result.get("tool_records", [])
            layers_used = list(set(r.layer.value for r in tool_records)) if tool_records else []

            return {
                "success": True,
                "response": result["response"],
                "metadata": {
                    "provider": result.get("provider", ""),
                    "model": result.get("model", ""),
                    "iterations": result.get("iterations", 1),
                    "tool_calls": len(result.get("tool_calls_log", [])),
                    "tool_calls_log": result.get("tool_calls_log", []),
                    "total_tokens": result.get("total_tokens", 0),
                    "complexity_score": cv.weighted_score,
                    "model_tier": cv.tier.value,
                    "complexity_vector": cv.model_dump(),
                    "layers_used": layers_used,
                    "hit_max_iterations": result.get("hit_max_iterations", False),
                },
            }

        except Exception as e:
            logger.error(f"handle_chat 失败: {e}")
            return {
                "success": False,
                "response": f"聊天处理失败: {str(e)}",
            }

    # ========================================================================
    # handle_device_command — 设备操控
    # ========================================================================

    async def handle_device_command(self, intent, device_id: str) -> dict:
        """设备操控 — 通过 DeviceOrchestrator 执行设备命令

        Args:
            intent: 解析后的意图 (ParsedIntent)
            device_id: 目标设备 ID

        Returns:
            执行结果 dict
        """
        command = intent.command if intent else "device_control"
        params = intent.params if intent else {}

        # 尝试使用 DeviceOrchestrator
        try:
            from core.device_orchestrator import get_device_orchestrator

            orchestrator = get_device_orchestrator()
            result = await orchestrator.execute_command(
                device_id=device_id,
                command=command,
                params=params,
            )

            success = result.get("success", False) if isinstance(result, dict) else bool(result)
            response_text = (
                result.get("message", "设备命令已执行")
                if isinstance(result, dict)
                else str(result)
            )

            return {
                "success": success,
                "response": response_text,
                "metadata": {
                    "device_id": device_id,
                    "command": command,
                    "result": result if isinstance(result, dict) else {"output": str(result)},
                },
            }

        except ImportError:
            logger.warning("DeviceOrchestrator 不可用，尝试直接设备通信")
        except Exception as e:
            logger.warning(f"DeviceOrchestrator 执行失败: {e}")

        # 降级: 尝试通过 WebSocket 直接发送命令
        try:
            from core.routes._shared import connection_manager

            sent = await connection_manager.send_to_device(
                device_id,
                {
                    "type": "task",
                    "task_type": command,
                    "payload": params,
                },
            )

            if sent:
                return {
                    "success": True,
                    "response": f"设备命令已通过 WebSocket 发送到 {device_id}",
                    "metadata": {"device_id": device_id, "command": command, "via": "websocket"},
                }

        except Exception as e:
            logger.debug(f"WebSocket 发送失败: {e}")

        return {
            "success": False,
            "response": f"无法向设备 {device_id} 发送命令 '{command}'，设备可能未连接。",
            "metadata": {"device_id": device_id, "command": command},
        }

    # ========================================================================
    # handle_agent_task — 复杂任务 (Agent 协作)
    # ========================================================================

    async def handle_agent_task(
        self,
        message: str,
        intent,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """复杂任务处理 — 使用 AgentFactory 创建 Agent，必要时组建团队

        PR-2：在入口立即构造 TaskEnvelope，统一 task_id/trace_id 贯穿链路。
        内部唯一任务格式：TaskEnvelope。

        Args:
            message: 用户消息
            intent: 解析后的意图 (ParsedIntent)
            device_id: 设备 ID（PR154: 贯穿 trace）
            session_id: 会话 ID（PR154: 贯穿 trace）
            trace_id: 请求追踪 ID（PR154: 贯穿 trace）

        Returns:
            Agent 执行结果 dict（含 task_id / trace_id）
        """
        try:
            from core.agent_factory import get_agent_factory
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            factory = get_agent_factory(router)

            # PR-2: 在入口立即构造 TaskEnvelope，task_id/trace_id 贯穿整条执行链路。
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            _envelope_trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
                _agent_envelope = _TaskEnvelope(
                    task_id=task_id,
                    trace_id=_envelope_trace_id,
                    source="openclawd.handle_agent_task",
                    targets=[device_id] if device_id else [],
                    tool_name="agent_task",
                    args={
                        "message": message,
                        "intent": intent.intent if intent else "general",
                    },
                    metadata={
                        "session_id": session_id or "",
                        "device_id": device_id or "",
                    },
                )
                logger.debug(
                    "OpenClawd.handle_agent_task envelope | task_id=%s trace_id=%s",
                    _agent_envelope.task_id,
                    _agent_envelope.trace_id,
                )
            except Exception as _env_err:
                logger.debug("handle_agent_task: TaskEnvelope construction skipped — %s", _env_err)

            # 判断是否需要团队协作 (复杂度驱动)
            tools = self._collect_tools()
            cv = router._compute_complexity_vector(
                [{"role": "user", "content": message}],
                tools if tools else None,
            )
            targets = intent.targets if intent else []
            is_complex = (
                cv.weighted_score >= 0.6
                or len(targets) > 2
                or (intent and intent.intent in ("workflow", "batch_task", "multi_device"))
            )

            if is_complex:
                # 复杂任务 -> 团队协作
                team_result = await self._execute_team_task(message, intent, factory, router)
                # PR154: 将 task_id / trace_id 注入团队协作结果 metadata
                meta = team_result.get("metadata", {})
                meta.setdefault("task_id", task_id)
                meta.setdefault("trace_id", _envelope_trace_id)
                meta.setdefault("device_id", device_id or "")
                team_result["metadata"] = meta
                return team_result

            # 普通 Agent 任务
            # 根据意图匹配模板
            template = self._select_agent_template(intent)

            try:
                agent = factory.create_from_template(template)
            except ValueError:
                agent = factory.create_from_template("coordinator")

            # 构建任务
            task_payload = {
                "task": message,
                "intent": intent.intent if intent else "general",
                "params": intent.params if intent else {"message": message},
            }

            result = await factory.execute_agent_task(agent.id, task_payload)

            # 防御: result 可能为 None
            if not result or not isinstance(result, dict):
                result = {"status": "error", "results": [{"error": "Agent 任务执行返回空结果"}]}

            # 提取输出
            outputs = []
            for r in result.get("results", []):
                if isinstance(r, dict):
                    if "output" in r:
                        outputs.append(r["output"])
                    elif "error" in r:
                        outputs.append(f"[错误] {r['error']}")

            reply = "\n".join(outputs) if outputs else "Agent 任务已完成"
            success = result.get("status") != "error"

            # 清理 Agent
            factory.terminate_agent(agent.id)

            # PR154: 将任务结果写入 TaskMemory（记忆回流）
            try:
                from core.openclawd_memory_backflow import store_task_result
                await store_task_result(
                    task_id=task_id,
                    device_id=device_id or "openclawd",
                    route_mode="agent",
                    result={
                        "status": "completed" if success else "error",
                        "task_type": "agent_task",
                        "task_description": message[:200],
                        "result_summary": reply[:200],
                    },
                    session_id=session_id,
                )
            except Exception as _bf_err:
                logger.warning("handle_agent_task: memory backflow 失败（非致命）: %s", _bf_err)

            return {
                "success": success,
                "response": reply,
                "metadata": {
                    "agent_id": agent.id,
                    "agent_role": agent.config.role.value,
                    "template": template,
                    "result_count": len(result.get("results", [])),
                    "task_id": task_id,
                    # PR-2: use envelope trace_id (guaranteed non-empty)
                    "trace_id": _envelope_trace_id,
                    "device_id": device_id or "",
                    "session_id": session_id or "",
                },
            }

        except Exception as e:
            logger.error(f"handle_agent_task 失败: {e}")
            # 降级到纯聊天
            return await self.handle_chat(message, "fallback")

    async def _execute_team_task(self, message: str, intent, factory, router) -> dict:
        """执行团队协作任务 — 复杂度驱动策略 + 工具注入 + Manifest 记录"""
        try:
            from core.agent_team import TeamManager, TeamStrategy
            from core.schemas.agent import TeamManifestSchema, TeamMemberSchema, TeamStrategyEnum

            manager = TeamManager(agent_factory=factory, llm_router=router)

            # 收集工具 & 计算复杂度向量
            tools = self._collect_tools()
            cv = router._compute_complexity_vector(
                [{"role": "user", "content": message}],
                tools if tools else None,
            )

            # 复杂度驱动策略选择
            if cv.weighted_score >= 0.7:
                strategy = "specialized"
            elif cv.weighted_score >= 0.4:
                strategy = "parallel"
            else:
                strategy = "parallel"

            # 意图覆写
            if intent and intent.intent == "workflow":
                strategy = "specialized"
            elif intent and hasattr(intent, "targets") and len(intent.targets) > 5:
                strategy = "swarm"

            # 创建团队 (传复杂度)
            team = await manager.create_team(
                strategy=strategy, task_hint=message,
                complexity_score=cv.weighted_score,
            )

            # 注入工具能力
            team.set_tools(tools, dispatch_fn=self._dispatch_tool_call)

            # 生成 Manifest 记录
            manifest = TeamManifestSchema(
                team_id=team.team_id,
                strategy=TeamStrategyEnum(strategy),
                task=message,
                members=[TeamMemberSchema.from_dataclass(m) for m in team.members],
                complexity_score=cv.weighted_score,
            )

            team_result = await team.execute(message)

            # 解散团队释放资源
            manager.disband_team(team.team_id)

            return {
                "success": True,
                "response": team_result.synthesized,
                "metadata": {
                    "team_id": team_result.team_id,
                    "strategy": team_result.strategy,
                    "member_count": len(team_result.member_results),
                    "total_latency_ms": round(team_result.total_latency_ms, 1),
                    "total_tokens": team_result.total_tokens,
                    "manifest": manifest.model_dump(),
                    "complexity_vector": cv.model_dump(),
                    "model_tier": cv.tier.value,
                },
            }

        except Exception as e:
            logger.warning(f"团队协作失败，降级到单 Agent: {e}")
            try:
                agent = factory.create_from_template("coordinator")
                result = await factory.execute_agent_task(
                    agent.id, {"task": message}
                )
                outputs = []
                for r in result.get("results", []):
                    if isinstance(r, dict) and "output" in r:
                        outputs.append(r["output"])
                factory.terminate_agent(agent.id)
                return {
                    "success": True,
                    "response": "\n".join(outputs) if outputs else "任务已完成",
                    "metadata": {"fallback": "single_agent"},
                }
            except Exception as inner_e:
                return {
                    "success": False,
                    "response": f"任务执行失败: {str(inner_e)}",
                }

    def _select_agent_template(self, intent) -> str:
        """根据意图选择最佳 Agent 模板"""
        if not intent:
            return "coordinator"

        template_map = {
            "task_manage": "coordinator",
            "file_operation": "code_executor",
            "search": "research",
            "code": "code_executor",
            "network": "device_controller",
            "ocr": "research",
            "device_control": "device_controller",
        }
        return template_map.get(intent.intent, "coordinator")

    # ========================================================================
    # handle_tool_call — MCP / Skill 工具调用
    # ========================================================================

    async def handle_tool_call(self, intent) -> dict:
        """MCP / Skill 工具调用

        Args:
            intent: 解析后的意图 (ParsedIntent)

        Returns:
            工具执行结果 dict
        """
        command = intent.command if intent else ""
        params = intent.params if intent else {}
        tool_name = params.get("tool_name", "")
        tool_args = params.get("arguments", params)

        # 尝试 MCP 工具调用
        mcp_result = await self._try_mcp_tool(tool_name, tool_args)
        if mcp_result is not None:
            return mcp_result

        # 尝试 Skill 调用
        skill_result = await self._try_skill_execute(command, params)
        if skill_result is not None:
            return skill_result

        # 两者都不可用，降级到 Agent 处理
        return {
            "success": False,
            "response": (
                f"未找到匹配的 MCP 工具或 Skill 来处理命令 '{command}'。"
                "请确认工具已加载或使用其他方式处理。"
            ),
            "metadata": {"command": command, "params": params},
        }

    async def _try_mcp_tool(self, tool_name: str, arguments: dict) -> Optional[dict]:
        """尝试通过 MCP 调用工具

        .. deprecated::
            PR-001 — This helper is a **compatibility/fallback** path kept only for
            ``handle_tool_call()`` consumers that do not yet use the canonical
            ``mcp__<server>__<tool>`` naming convention.  New code should invoke
            capabilities through :meth:`_dispatch_tool_call` or directly via
            ``self._capability_dispatcher.dispatch(...)``.
        """
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            if not servers:
                return None

            # 遍历所有 MCP 服务器查找匹配的工具
            for server_info in servers:
                server_id = server_info.get("id", "")
                if server_info.get("status") != "running":
                    continue

                tools = await mcp_loader.list_tools(server_id)
                for tool in tools:
                    if tool.get("name") == tool_name:
                        result = await mcp_loader.call_tool(
                            server_id, tool_name, arguments
                        )
                        return {
                            "success": result.get("success", False),
                            "response": str(result.get("result", result.get("error", "MCP 工具调用完成"))),
                            "metadata": {
                                "source": "mcp",
                                "server_id": server_id,
                                "tool_name": tool_name,
                                "result": result,
                            },
                        }

        except ImportError:
            logger.debug("MCP Loader 不可用")
        except Exception as e:
            logger.warning(f"MCP 工具调用失败: {e}")

        return None

    async def _try_skill_execute(self, skill_name: str, params: dict) -> Optional[dict]:
        """尝试通过 SkillLoader 执行技能

        .. deprecated::
            PR-001 — This helper is a **compatibility/fallback** path kept only for
            ``handle_tool_call()`` consumers that do not yet use the canonical
            ``skill__<id>`` naming convention.  New code should invoke skills
            through :meth:`_dispatch_tool_call` or directly via
            ``self._capability_dispatcher.dispatch(...)``.
        """
        try:
            from core.skill_loader import skill_loader

            skills = skill_loader.list_skills()
            if not skills:
                return None

            # 查找匹配的技能
            target_skill = None
            for skill_info in skills:
                if (
                    skill_info.get("name") == skill_name
                    or skill_info.get("id") == skill_name
                ):
                    target_skill = skill_info
                    break

            if not target_skill:
                # 搜索匹配
                search_results = skill_loader.search(skill_name)
                if search_results:
                    target_skill = search_results[0]

            if target_skill:
                skill_id = target_skill.get("id", "")
                # 过滤掉非技能参数
                exec_params = {
                    k: v
                    for k, v in params.items()
                    if k not in ("tool_name", "arguments", "instruction", "message")
                }
                result = await skill_loader.execute(skill_id, **exec_params)
                return {
                    "success": result.get("success", False),
                    "response": str(result.get("result", result.get("error", "技能执行完成"))),
                    "metadata": {
                        "source": "skill",
                        "skill_id": skill_id,
                        "skill_name": target_skill.get("name", ""),
                        "result": result,
                    },
                }

        except ImportError:
            logger.debug("Skill Loader 不可用")
        except Exception as e:
            logger.warning(f"Skill 执行失败: {e}")

        return None

    # ========================================================================
    # get_status — 系统状态
    # ========================================================================

    async def get_status(self) -> dict:
        """系统状态概览 — 聚合所有子模块状态

        Returns:
            系统状态 dict
        """
        status = {
            "openclawd": {
                "initialized": self._initialized,
                "request_count": self._request_count,
                "error_count": self._error_count,
                "uptime_seconds": int(time.time() - self._start_time),
                "active_sessions": len(self._session_memory),
            },
        }

        # LLM Router 状态
        try:
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            router_status = router.get_status()
            status["llm_router"] = {
                "available": router.is_available(),
                "total_providers": router_status.get("total_providers", 0),
                "healthy_providers": router_status.get("healthy_providers", 0),
                "total_calls": router_status.get("total_calls", 0),
                "providers": list(router_status.get("providers", {}).keys()),
            }
        except Exception as e:
            status["llm_router"] = {"available": False, "error": str(e)}

        # Agent Factory 状态
        try:
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory()
            factory_status = factory.get_status()
            status["agent_factory"] = {
                "total_agents": factory_status.get("total_agents", 0),
                "by_state": factory_status.get("by_state", {}),
                "templates": factory_status.get("templates", []),
            }
        except Exception as e:
            status["agent_factory"] = {"total_agents": 0, "error": str(e)}

        # MCP 状态
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            running = sum(1 for s in servers if s.get("status") == "running")
            total_tools = sum(s.get("tools_count", 0) for s in servers)
            status["mcp"] = {
                "server_count": len(servers),
                "running_count": running,
                "total_tools": total_tools,
            }
        except Exception as e:
            status["mcp"] = {"server_count": 0, "error": str(e)}

        # Skill 状态
        try:
            from core.skill_loader import skill_loader

            stats = skill_loader.get_stats()
            status["skills"] = {
                "loaded_skills": stats.get("loaded_skills", 0),
                "total_executions": stats.get("total_executions", 0),
                "successful_executions": stats.get("successful_executions", 0),
                "failed_executions": stats.get("failed_executions", 0),
            }
        except Exception as e:
            status["skills"] = {"loaded_skills": 0, "error": str(e)}

        # 意图解析器状态
        try:
            from core.ai_intent import get_intent_parser

            parser = get_intent_parser()
            status["intent_parser"] = {
                "cache_size": len(parser._parse_cache),
                "supported_intents": list(parser.RULE_PATTERNS.keys()),
            }
        except Exception as e:
            status["intent_parser"] = {"error": str(e)}

        return status

    # ========================================================================
    # 会话记忆管理
    # ========================================================================

    async def _record_turn(self, session_id: str, role: str, content: str):
        """记录对话轮次到内部会话记忆"""
        if session_id not in self._session_memory:
            self._session_memory[session_id] = []

        self._session_memory[session_id].append({
            "role": role,
            "content": content,
        })

        # 限制会话长度
        if len(self._session_memory[session_id]) > 40:
            self._session_memory[session_id] = self._session_memory[session_id][-20:]

        # 同步到 ConversationMemory (如果可用)
        try:
            from core.ai_intent import get_conversation_memory

            memory = get_conversation_memory()
            await memory.add_turn(session_id, role, content)
        except Exception:
            pass

        # Block-3: mirror the turn into working memory for continuous cognition.
        try:
            from core.cognitive.working_memory import get_working_memory
            trace_id = getattr(self, "_current_trace_id", "") or ""
            get_working_memory().add(
                session_id=session_id,
                role=role,
                content=content,
                trace_id=trace_id,
            )
        except Exception:
            pass

    async def clear_session(self, session_id: str):
        """清除会话记忆"""
        self._session_memory.pop(session_id, None)
        try:
            from core.ai_intent import get_conversation_memory

            memory = get_conversation_memory()
            await memory.clear_session(session_id)
        except Exception:
            pass

    def get_session_history(self, session_id: str, max_turns: int = 20) -> List[Dict]:
        """获取会话历史"""
        history = self._session_memory.get(session_id, [])
        return history[-max_turns:]

    def list_sessions(self) -> List[Dict]:
        """列出所有活跃会话"""
        sessions = []
        for sid, turns in self._session_memory.items():
            sessions.append({
                "session_id": sid,
                "turn_count": len(turns),
                "last_message": turns[-1]["content"][:100] if turns else "",
            })
        return sessions

    # ========================================================================
    # 设备感知 — PR86: 设备注册可见性，新设备自动进入 capability bus
    # ========================================================================

    def sync_device_capabilities(self) -> int:
        """将设备能力同步为 CapabilityRegistry 条目。

        Priority A: 使用 UnifiedDeviceManager 作为 SSOT。
        Fallback B: 当 UnifiedDeviceManager 不可用或为空时，回退到 DeviceRegistry
        （保证向后兼容，同时确保新设备能力能正确注册到能力总线）。
        包括低层设备能力和高层自治能力（metadata 声明）。
        返回同步的能力条目数量。
        """
        _AUTONOMOUS_CAPABILITY_KEYS = (
            "goal_execution_enabled",
            "local_task_planning",
            "local_ui_reasoning",
            "cross_device_coordination",
            "parallel_execution_enabled",
            "local_model_enabled",
        )
        count = 0
        try:
            from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

            reg = CapabilityRegistry.get_instance()

            # ── Priority A: UnifiedDeviceManager ────────────────────────────
            devices = []
            try:
                from core.unified.device_manager import get_unified_device_manager
                udm = get_unified_device_manager()
                devices = udm.list_devices() or []
            except (ImportError, AttributeError, RuntimeError) as _udm_err:
                logger.debug("UnifiedDeviceManager unavailable: %s", _udm_err)

            # ── Fallback B: DeviceRegistry ───────────────────────────────────
            if not devices:
                try:
                    from core.device_registry import DeviceRegistry
                    dr = DeviceRegistry.get_instance()
                    raw = dr.list_devices()
                    # list_devices may return a dict {id: obj} or a list
                    if isinstance(raw, dict):
                        devices = list(raw.values())
                    else:
                        devices = list(raw or [])
                except (ImportError, AttributeError, RuntimeError) as _dr_err:
                    logger.debug("DeviceRegistry fallback unavailable: %s", _dr_err)

            if not devices:
                return 0

            for device in devices:
                # Accept both object attributes and dict keys
                if isinstance(device, dict):
                    device_id = device.get("device_id", "")
                    d_name = device.get("device_name", device_id)
                    d_type = str(device.get("device_type", "unknown"))
                    caps = device.get("capabilities", [])
                    meta: Dict[str, Any] = device.get("metadata", {}) or {}
                else:
                    device_id = getattr(device, "device_id", "")
                    d_name = getattr(device, "device_name", None) or device_id
                    d_type = str(getattr(device, "device_type", "unknown"))
                    caps = getattr(device, "capabilities", []) or []
                    meta = getattr(device, "metadata", {}) or {}

                # 低层设备能力
                for cap in caps:
                    cap_name = cap if isinstance(cap, str) else str(cap)
                    key = f"gateway__{device_id}__{cap_name}"
                    reg.register(CapabilityItem(
                        name=key,
                        description=f"[Gateway:{d_name}({d_type})] 设备能力: {cap_name}",
                        source="gateway",
                        source_id=device_id,
                        available=True,
                        metadata={"device_name": d_name, "device_type": d_type},
                    ))
                    count += 1

                # Priority C: 高层自治能力（从 metadata 声明）
                for cap_key in _AUTONOMOUS_CAPABILITY_KEYS:
                    if meta.get(cap_key):
                        key = f"autonomous__{device_id}__{cap_key}"
                        reg.register(CapabilityItem(
                            name=key,
                            description=f"[Autonomous:{d_name}] {cap_key}",
                            source="autonomous",
                            source_id=device_id,
                            available=True,
                            metadata={
                                "device_id": device_id,
                                "device_name": d_name,
                                "device_type": d_type,
                                "capability_key": cap_key,
                            },
                        ))
                        count += 1

            if count:
                logger.info(
                    "OpenClawd: 已同步 %d 个设备能力到 CapabilityRegistry",
                    count,
                )
        except Exception as e:
            logger.debug("sync_device_capabilities 失败: %s", e)
        return count

    # ========================================================================
    # 网关统一命令路径 — PR-1: OpenClawd -> TaskEnvelope -> route_envelope -> device -> result
    # ========================================================================

    async def send_gateway_command(
        self,
        device_id: str,
        command: str,
        payload: Optional[Dict] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict:
        """统一网关命令路径（带 trace ID）。

        链路：OpenClawd → TaskEnvelope → route_envelope → gateway/device_router → device → result

        构造 TaskEnvelope 并经由 CommandRouter.route_envelope() 进入内部路由链路。
        保留所有原入口参数与返回字段，与旧调用者完全兼容。
        """
        command_id = uuid.uuid4().hex
        task_id = task_id or uuid.uuid4().hex
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        t0 = time.monotonic()
        logger.info(
            "OpenClawd.send_gateway_command | command_id=%s task_id=%s trace_id=%s "
            "session_id=%s device_id=%s command=%s",
            command_id, task_id, trace_id, session_id, device_id, command,
        )

        result: Dict = {
            "success": False,
            "command_id": command_id,
            "task_id": task_id,
            "session_id": session_id,
            "device_id": device_id,
            "command": command,
        }

        # 尝试通过 command_router.route_envelope 发送（PR-1: 统一入口）
        try:
            from core.command_router import get_command_router
            from core.schemas.task_envelope import TaskEnvelope
            from core.schemas.remote_execution import RemoteExecutionMode

            cr = get_command_router()
            # 构造 TaskEnvelope，携带 session_id 和 command_id 进入统一链路
            envelope = TaskEnvelope(
                task_id=task_id,
                trace_id=trace_id,
                source="openclawd",
                targets=[device_id],
                tool_name=command,
                args=payload or {},
                remote_execution_mode=RemoteExecutionMode.command_only,
                metadata={
                    "command_id": command_id,
                    "session_id": session_id,
                    "source": "openclawd",
                },
            )
            cr_result = await cr.route_envelope(envelope)
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": cr_result.get("success", False),
                "response": cr_result.get("response") or cr_result.get("result"),
                "latency_ms": round(latency_ms, 1),
                "via": "command_router",
            })
            logger.info(
                "OpenClawd.send_gateway_command done | command_id=%s success=%s latency=%.1fms",
                command_id, result["success"], latency_ms,
            )
            return result
        except Exception as e:
            logger.debug("command_router 不可用，尝试 DeviceOrchestrator: %s", e)

        # 降级：DeviceOrchestrator
        try:
            from core.device_orchestrator import get_device_orchestrator
            orch = get_device_orchestrator()
            orch_result = await orch.execute_command(
                device_id=device_id,
                command=command,
                params=payload or {},
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": orch_result.get("success", False) if isinstance(orch_result, dict) else bool(orch_result),
                "response": orch_result.get("message", "") if isinstance(orch_result, dict) else str(orch_result),
                "latency_ms": round(latency_ms, 1),
                "via": "device_orchestrator",
            })
            return result
        except Exception as e:
            logger.debug("DeviceOrchestrator 不可用，尝试 WebSocket: %s", e)

        # 最终降级：WebSocket
        try:
            from core.routes._shared import connection_manager
            sent = await connection_manager.send_to_device(
                device_id,
                {
                    "type": "command",
                    "command": command,
                    "payload": payload or {},
                    "command_id": command_id,
                    "task_id": task_id,
                },
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": sent,
                "response": f"命令已通过 WebSocket 发送到 {device_id}" if sent else f"设备 {device_id} 未连接",
                "latency_ms": round(latency_ms, 1),
                "via": "websocket",
            })
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": False,
                "response": f"无法向设备 {device_id} 发送命令: {e}",
                "latency_ms": round(latency_ms, 1),
                "error": str(e),
            })

        logger.info(
            "OpenClawd.send_gateway_command done | command_id=%s success=%s via=%s latency=%.1fms",
            command_id, result.get("success"), result.get("via", "none"),
            result.get("latency_ms", 0),
        )
        return result


# ============================================================================
# 单例
# ============================================================================

_openclawd_instance: Optional[OpenClawd] = None


def get_openclawd() -> OpenClawd:
    """获取 OpenClawd 全局单例"""
    global _openclawd_instance
    if _openclawd_instance is None:
        _openclawd_instance = OpenClawd()
    return _openclawd_instance
