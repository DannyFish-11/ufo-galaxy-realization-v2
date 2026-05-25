"""
Galaxy - 自主调度器 (Autonomous Scheduler)
==============================================

核心 ReAct Loop:
  用户自然语言 → LLM 思考 → tool_call 调用节点 → 观察结果 → 继续思考 → 完成

工具发现策略:
  1. 从 nodes/ 目录扫描 config.json (精确描述)
  2. 从 nodes/ 目录扫描 main.py 的 docstring 和 @app.post (自动推断)
  3. 注入内置设备操作工具 (send_to_device, screenshot, etc.)
  4. 运行时注入已连接设备的动态工具
"""

import os
import re
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

logger = logging.getLogger("scheduler")

# PR-2: Affirms that this scheduler delegates correlation-field stamping to
# the canonical message interop layer (core.message_interop.extract_correlation).
SCHEDULER_MESSAGE_INTEROP_APPLIED: str = "SCHEDULER_MESSAGE_INTEROP_V1"

# PR-3: Execution Spine Integration.
# Affirms that the scheduler's built-in tool paths (send_to_device,
# relay_to_device, mesh_send) route execution through the canonical spine:
#   ExecutionIngressAdapter → CommandRouter.route_envelope
# Callers may import this sentinel to assert that the scheduler is wired
# into the execution spine rather than dispatching independently.
SCHEDULER_ROUTES_COMMAND_ROUTER: str = "SCHEDULER_ROUTES_COMMAND_ROUTER_V1"

# PR-507: Canonical task front-loading — _exec_send_to_device() now calls
# adapt_to_canonical_task() before normalize_ingress_to_envelope() so that
# CanonicalTask is the primary ontology object at scheduler ingress.
CANONICAL_TASK_SCHEDULER_FRONT_LOADED: str = (
    "CANONICAL_TASK_SCHEDULER_V1: core/scheduler.py _exec_send_to_device() "
    "calls adapt_to_canonical_task() before envelope normalization."
)

# PR-513 / GAP-512-002: Scheduler relay and mesh paths now register the
# CanonicalTask in TaskGraphRuntime before dispatch so that task-graph
# realization (PR-508) covers these codepaths.
SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED: str = (
    "SCHEDULER_TASK_GRAPH_RELAY_MESH_V1: core/scheduler.py _exec_relay() "
    "and _exec_mesh_send() register CanonicalTask in TaskGraphRuntime before "
    "dispatch (GAP-512-002)."
)

# PR-B: Legacy Ingress Convergence — spine routing sentinel.
# Affirms that _exec_relay() and _exec_mesh_send() now attempt canonical
# spine routing via CommandRouter.route_envelope() before falling back to
# ProxyRelay / MeshCoordinator respectively.  This convergence ensures all
# scheduler dispatch paths (send_to_device, relay_to_device, mesh_send) enter
# the execution spine as the primary routing path.
SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE: str = (
    "SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE_V1: "
    "_exec_relay() and _exec_mesh_send() attempt CommandRouter.route_envelope() "
    "before ProxyRelay / MeshCoordinator fallback; "
    "ingress is normalized via core.execution_spine."
)

# Post-1290 convergence hardening:
# Relay/Mesh legacy fallback paths are now explicitly non-canonical and blocked
# by default unless a caller opts in via runtime flag/context.
SCHEDULER_LEGACY_RELAY_MESH_FALLBACK_GATED: str = (
    "SCHEDULER_LEGACY_RELAY_MESH_FALLBACK_GATED_V1: "
    "_exec_relay()/_exec_mesh_send() require canonical CommandRouter routing by "
    "default; ProxyRelay/MeshCoordinator fallback is blocked unless explicitly "
    "enabled by allow_legacy_scheduler_fallback or "
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK=true."
)

# Phase-A consolidation: canonical tool naming is now the PRIMARY exposed
# naming scheme for MCP and Skill tools injected by this scheduler.
#
# Canonical prefixes (double-underscore separator):
#   mcp__<server_id>__<tool_name>   — MCP server tools
#   skill__<skill_id>               — Skill tools
#   node__<node_id>__<action>       — Node capability tools
#
# Legacy prefixes (single underscore) are retained ONLY as compatibility
# aliases in the dispatch path (_dispatch_tool_call).  New tools MUST use
# the canonical double-underscore form.
SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY: str = (
    "SCHEDULER_CANONICAL_TOOL_NAMING_V1: inject_mcp_tools() emits "
    "mcp__<server>__<tool>; inject_skill_tools() emits skill__<id>; "
    "legacy mcp_/skill_/call_ prefixes are compat aliases only."
)

# Stage 10: Broadcast path task-graph convergence.
# _exec_broadcast() now registers its root CanonicalTask in TaskGraphRuntime
# before delegating per-device calls to _exec_send_to_device(), closing the
# gap that existed vs. _exec_relay() and _exec_mesh_send() (PR-513/GAP-512-002).
SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED: str = (
    "SCHEDULER_BROADCAST_TASK_GRAPH_V1: core/scheduler.py _exec_broadcast() "
    "registers CanonicalTask in TaskGraphRuntime before per-device dispatch "
    "(Stage 10 convergence — mirrors relay/mesh_send graph registration)."
)

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]


# ============================================================================
# 内置工具定义 — 不依赖节点目录，始终可用
# ============================================================================

_BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_to_device",
            "description": (
                "Send a task/command to a connected device via WebSocket. "
                "Use this to control phones, tablets, PCs etc. "
                "Common task_types: open_app, click, swipe, type_text, screenshot, "
                "shell_command, install_apk, key_event, get_device_info, "
                "start_recording, stop_recording, get_battery"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The device ID to send to (from connected devices list)"
                    },
                    "task_type": {
                        "type": "string",
                        "description": "The type of task: open_app, click, swipe, type_text, screenshot, shell_command, install_apk, key_event, get_device_info, get_battery, etc."
                    },
                    "payload": {
                        "type": "object",
                        "description": "Task parameters. For open_app: {app_name: 'WeChat'}. For click: {x: 100, y: 200}. For type_text: {text: 'hello'}. For shell_command: {command: 'ls'}."
                    }
                },
                "required": ["device_id", "task_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast_to_all_devices",
            "description": "Send the same command to ALL connected devices simultaneously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "description": "The task type to broadcast"
                    },
                    "payload": {
                        "type": "object",
                        "description": "Task parameters"
                    }
                },
                "required": ["task_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "relay_to_device",
            "description": (
                "Relay a message from one device to another via the server. "
                "Use this for device-to-device communication when one device "
                "needs to send a task or command to another device."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_device": {
                        "type": "string",
                        "description": "Source device ID"
                    },
                    "target_device": {
                        "type": "string",
                        "description": "Target device ID"
                    },
                    "payload_type": {
                        "type": "string",
                        "description": "Type of payload: task, command, chat"
                    },
                    "payload": {
                        "type": "object",
                        "description": "Message payload"
                    }
                },
                "required": ["source_device", "target_device", "payload_type", "payload"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": (
                "Execute code in a secure sandbox. Supports Python, JavaScript, "
                "and Bash. Use when you need to compute, process data, verify logic, "
                "generate scripts, or perform calculations programmatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Source code to execute"
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "bash"],
                        "description": "Programming language"
                    }
                },
                "required": ["code", "language"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mesh_send",
            "description": (
                "Send a message to a device via the P2P mesh network. "
                "Automatically selects the best route: LAN direct (P2P) if available, "
                "otherwise falls back to server relay. Use this for low-latency "
                "device-to-device communication."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_device": {
                        "type": "string",
                        "description": "Target device ID"
                    },
                    "payload": {
                        "type": "object",
                        "description": "Message payload to send"
                    },
                    "payload_type": {
                        "type": "string",
                        "description": "Type of payload: task, command, chat",
                        "default": "task"
                    },
                    "source_device": {
                        "type": "string",
                        "description": "Source device ID (optional, defaults to server)"
                    }
                },
                "required": ["target_device", "payload"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_device",
            "description": (
                "Find a connected device by type or name. Returns the device_id and info. "
                "Use this when the user refers to a device by type (手机/phone, 电脑/PC, 平板/tablet) "
                "instead of exact device_id. "
                "Types: android, windows, ios, linux, macos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_type": {
                        "type": "string",
                        "description": "Device type to search: android, windows, ios, linux, macos"
                    },
                    "device_name": {
                        "type": "string",
                        "description": "Device name or alias to search for"
                    }
                }
            }
        }
    },
]


class AutonomousScheduler:
    def __init__(self, nodes_dir: str):
        self.nodes_dir = nodes_dir
        self.tools_cache: List[Dict[str, Any]] = []
        self._load_tools()

    def _load_tools(self):
        """多策略工具发现"""
        self.tools_cache = list(_BUILTIN_TOOLS)  # 先加入内置工具

        if not os.path.isdir(self.nodes_dir):
            logger.warning(f"节点目录不存在: {self.nodes_dir}")
            return

        loaded_nodes = set()

        for name in sorted(os.listdir(self.nodes_dir)):
            node_dir = os.path.join(self.nodes_dir, name)
            if not os.path.isdir(node_dir):
                continue

            # 策略1: 从 config.json 加载
            config_file = os.path.join(node_dir, "config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    description = config.get("description", f"Execute actions on node {name}")
                    self._add_node_tool(name, description)
                    loaded_nodes.add(name)
                    continue
                except Exception as e:
                    logger.debug(f"config.json 解析失败 {name}: {e}")

            # 策略2: 从 main.py docstring 推断
            main_py = os.path.join(node_dir, "main.py")
            if os.path.exists(main_py) and name not in loaded_nodes:
                description = self._infer_description_from_main(main_py, name)
                if description:
                    self._add_node_tool(name, description)
                    loaded_nodes.add(name)

        logger.info(
            f"Scheduler 工具发现完成: {len(self.tools_cache)} 工具 "
            f"({len(_BUILTIN_TOOLS)} 内置 + {len(loaded_nodes)} 节点)"
        )
        # 注入已加载的 MCP 工具
        self.inject_mcp_tools()
        # 注入已注册的 Skill 工具
        self.inject_skill_tools()

    def _infer_description_from_main(self, main_py_path: str, node_name: str) -> Optional[str]:
        """从 main.py 的头部注释/docstring 推断节点描述"""
        try:
            with open(main_py_path, "r", encoding="utf-8") as f:
                head = f.read(2000)

            # 尝试提取模块 docstring
            match = re.search(r'"""(.*?)"""', head, re.DOTALL)
            if match:
                doc = match.group(1).strip()
                # 取前两行作为描述
                lines = [l.strip() for l in doc.split("\n") if l.strip() and not l.strip().startswith("=")]
                if lines:
                    return " ".join(lines[:2])[:200]

            # 尝试从 #注释 提取
            for line in head.split("\n")[:10]:
                line = line.strip()
                if line.startswith("#") and len(line) > 5:
                    return line.lstrip("#").strip()[:200]

            return f"Node {node_name} - execute actions"
        except Exception:
            return None

    def _add_node_tool(self, node_name: str, description: str):
        """添加一个节点工具到缓存"""
        tool = {
            "type": "function",
            "function": {
                "name": f"call_{node_name}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "The action to perform on this node"
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameters for the action"
                        }
                    },
                    "required": ["action"]
                }
            }
        }
        self.tools_cache.append(tool)

    def get_tools(self) -> List[Dict[str, Any]]:
        return self.tools_cache

    def get_tool_definitions(self) -> List["ToolDefinition"]:
        """返回统一的 ToolDefinition 注册表

        将 tools_cache 中 4 种来源的工具全部转为 ToolDefinition 格式，
        供 Agent 系统统一查询。
        """
        try:
            from core.schemas.node_protocol import ToolDefinition
        except ImportError:
            logger.debug("ToolDefinition 不可用，跳过统一注册")
            return []

        definitions: List[ToolDefinition] = []
        for tool in self.tools_cache:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            params = func.get("parameters", {})

            # 推断来源和节点 ID
            source = "config"
            node_id = ""
            category = "general"
            requires_device = False

            if name.startswith("mcp__"):
                # Canonical MCP tool.
                source = "mcp"
                category = "mcp"
            elif name.startswith("skill__"):
                # Canonical Skill tool.
                source = "skill"
                category = "skill"
            elif name.startswith("node__"):
                # Canonical Node tool.
                source = "canonical"
                parts = name.split("__")
                if len(parts) >= 2:
                    node_id = parts[1]
                category = "node"
            elif name.startswith("mcp_"):
                # Legacy compat alias — still recognized for config-loaded tools.
                source = "mcp"
                category = "mcp"
            elif name.startswith("skill_"):
                # Legacy compat alias — still recognized for config-loaded tools.
                source = "skill"
                category = "skill"
            elif name.startswith("call_Node_"):
                # Legacy compat alias for node tools.
                source = "config"
                parts = name.replace("call_", "").split("_")
                if len(parts) >= 2:
                    node_id = f"{parts[0]}_{parts[1]}"
                category = "node"
            definitions.append(ToolDefinition(
                name=name,
                description=desc,
                node_id=node_id,
                parameters=params,
                category=category,
                requires_device=requires_device,
                source=source,
            ))

        return definitions

    def inject_mcp_tools(self):
        """将 mcp_loader 中已加载的所有 MCP 工具注入到工具列表（可在加载新 MCP Server 后调用）

        Phase-A: Tools are exposed under the canonical double-underscore prefix:
            mcp__<server_id>__<tool_name>
        The legacy single-underscore form (``mcp_<server_id>_<tool_name>``) is no
        longer injected here; the dispatch path provides a compat alias for it.
        """
        try:
            from core.mcp_loader import mcp_loader, MCPServerStatus
            injected = 0
            existing_names = {t["function"]["name"] for t in self.tools_cache}
            for server_id, server in mcp_loader.servers.items():
                if server.status != MCPServerStatus.RUNNING:
                    continue
                for tool in server.tools:
                    # Canonical double-underscore form.
                    func_name = f"mcp__{server_id}__{tool.name}"
                    if func_name in existing_names:
                        continue
                    self.tools_cache.append({
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "description": f"[MCP:{server.name}] {tool.description}",
                            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                        },
                    })
                    existing_names.add(func_name)
                    injected += 1
            if injected:
                logger.info(f"注入 {injected} 个 MCP 工具到调度器 (canonical mcp__ prefix)")
        except Exception as e:
            logger.warning(f"注入 MCP 工具失败: {e}")

    def inject_skill_tools(self):
        """将 skill_loader 中已加载的 Skill 注入为可用工具

        Phase-A: Skills are exposed under the canonical double-underscore prefix:
            skill__<skill_id>
        The legacy single-underscore form (``skill_<name>``) is no longer injected
        here; the dispatch path provides a compat alias for it.
        """
        try:
            from core.skill_loader import skill_loader as loader
            if not loader:
                return
            existing_names = {t["function"]["name"] for t in self.tools_cache}
            injected = 0
            for skill in loader.list_skills():
                if not skill.get("name"):
                    continue
                # Canonical double-underscore form.
                func_name = f"skill__{skill['name']}"
                if func_name in existing_names:
                    continue
                self.tools_cache.append({
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": f"[Skill] {skill.get('description', skill['name'])}",
                        "parameters": skill.get("params_schema") or {"type": "object", "properties": {}},
                    },
                })
                existing_names.add(func_name)
                injected += 1
            if injected:
                logger.info(f"注入 {injected} 个 Skill 工具到调度器")
        except Exception as e:
            logger.debug(f"注入 Skill 工具跳过: {e}")

    async def plan_and_execute(
        self,
        instruction: str,
        llm_manager: Any,
        context: Dict[str, Any] = None,
        max_turns: int = 5,
    ) -> Dict[str, Any]:
        """
        核心 ReAct Loop:
        1. 接收自然语言指令
        2. 注入动态设备上下文 + 可用工具
        3. LLM 思考 → tool_call → 执行 → 观察 → 循环
        4. LLM 认为完成 → 返回最终回复
        """
        # 1. 构建动态设备上下文
        device_context = "No devices connected."
        if context and "devices" in context:
            devices = context["devices"]
            if devices:
                device_lines = []
                for did, d in devices.items():
                    if isinstance(d, dict):
                        dtype = d.get("device_type", "unknown")
                        dname = d.get("device_name", did)
                        caps = d.get("capabilities", [])
                        status = d.get("status", "unknown")
                        device_lines.append(
                            f"  - ID: {did}, Name: {dname}, Type: {dtype}, "
                            f"Status: {status}, Capabilities: {caps}"
                        )
                if device_lines:
                    device_context = (
                        "Connected Devices (use send_to_device tool to control them):\n"
                        + "\n".join(device_lines)
                    )

        # RAG 增强: 注入相似经验和知识
        rag_context = ""
        try:
            from core.rag_memory import get_rag_memory
            rag = get_rag_memory()
            rag_context = await rag.enhance_agent_prompt(
                instruction, device_id=context.get("device_id", "") if context else ""
            )
        except Exception as e:
            logger.debug(f"RAG enhancement skipped: {e}")

        # 来源设备信息
        source_device_id = context.get("device_id", "") if context else ""
        source_device_info = ""
        if source_device_id:
            source_device_info = (
                f"SOURCE DEVICE: You are currently talking to the user on device: {source_device_id}\n"
                f"If the user says '本机/this device/当前设备/本设备', target this device_id.\n"
            )

        system_prompt = f"""You are the central AI scheduler of UFO Galaxy, a multi-device agent operating system.
Your goal: satisfy the user's request by calling the available tools.
You operate in a ReAct loop: Think → Act (call tools) → Observe results → Think again.

RULES:
1. For device operations (open app, click, swipe, type, screenshot): use 'send_to_device' tool with the target device_id.
2. For system operations (file, web, shell, OCR): use the appropriate 'node__<node_id>__<action>' tool.
3. Always explain what you're doing before calling tools.
4. After tool execution, interpret the result and decide next steps.
5. When the task is fully done, provide a clear summary in the user's language.

TOOL NAMING (canonical form):
- MCP tools:   mcp__<server_id>__<tool_name>
- Skill tools: skill__<skill_id>
- Node tools:  node__<node_id>__<action>

DEVICE CONTEXT:
{device_context}
{source_device_info}
COMMON DEVICE OPERATIONS:
- open_app: {{"app_name": "微信"}} or {{"package": "com.tencent.mm"}}
- click: {{"x": 500, "y": 800}}
- type_text: {{"text": "hello"}}
- screenshot: {{}}
- shell_command: {{"command": "ls /sdcard"}}
- key_event: {{"key": "BACK"}} / "HOME" / "RECENT"
- get_device_info: {{}}
- get_battery: {{}}

CROSS-DEVICE:
- Use 'relay_to_device' to send messages between devices (server relay).
- Use 'mesh_send' for P2P mesh delivery — auto-selects LAN direct or relay fallback.
- Use 'execute_code' to run Python/JS/Bash code in a safe sandbox.
{rag_context}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction},
        ]

        # 限制工具数量避免 token 爆炸 — 选择最相关的工具
        active_tools = self._select_relevant_tools(instruction)

        executed_steps = []
        final_reply = ""

        try:
            for turn in range(max_turns):
                logger.info(f"ReAct Loop Turn {turn + 1}/{max_turns}")

                response = await llm_manager.chat_completion(
                    messages=messages,
                    tools=active_tools if active_tools else None,
                    tool_choice="auto",
                    task_type="AGENT_CONTROL",
                )

                message = response.choices[0].message
                messages.append(message)

                tool_calls = message.tool_calls

                if not tool_calls:
                    final_reply = message.content or ""
                    break

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}

                    logger.info(f"ReAct 执行: {function_name}({json.dumps(function_args, ensure_ascii=False)[:200]})")

                    # 执行工具
                    tool_result_content = await self._execute_tool(
                        function_name, function_args, context
                    )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": tool_result_content,
                    })

                    executed_steps.append({
                        "node_id": function_name.replace("call_", ""),
                        "action": function_args.get("action") or function_args.get("task_type", ""),
                        "result": tool_result_content[:500],
                    })

            # 记录执行经验到 RAG Memory
            try:
                from core.rag_memory import get_rag_memory
                rag = get_rag_memory()
                rag.log_experience(
                    agent_name="scheduler_react",
                    instruction=instruction,
                    steps=executed_steps,
                    final_output=final_reply or "Task completed.",
                    success=True,
                    device_id=context.get("device_id", "") if context else "",
                )
            except Exception:
                pass

            return {
                "success": True,
                "steps": executed_steps,
                "reply": final_reply or "Task completed.",
            }

        except Exception as e:
            logger.error(f"ReAct 调度失败: {e}")
            # 记录失败经验
            try:
                from core.rag_memory import get_rag_memory
                rag = get_rag_memory()
                rag.log_experience(
                    agent_name="scheduler_react",
                    instruction=instruction,
                    steps=executed_steps,
                    final_output=str(e),
                    success=False,
                )
            except Exception:
                pass

            return {
                "success": False,
                "error": str(e),
                "steps": executed_steps,
                "reply": f"调度失败: {str(e)}",
            }

    async def _execute_tool(
        self, function_name: str, args: Dict, context: Dict
    ) -> str:
        """统一工具执行入口"""
        try:
            executor = context.get("executor") if context else None

            # 内置工具: send_to_device
            if function_name == "send_to_device":
                return await self._exec_send_to_device(args, context)

            # 内置工具: broadcast
            if function_name == "broadcast_to_all_devices":
                return await self._exec_broadcast(args, context)

            # 内置工具: relay_to_device (Phase 2)
            if function_name == "relay_to_device":
                return await self._exec_relay(args, context)

            # 内置工具: execute_code (Phase 4)
            if function_name == "execute_code":
                return await self._exec_code(args)

            # 内置工具: find_device
            if function_name == "find_device":
                return await self._exec_find_device(args, context)

            # 内置工具: mesh_send (Phase 5)
            if function_name == "mesh_send":
                return await self._exec_mesh_send(args)

            # ── CANONICAL tool dispatch (double-underscore prefix) ────────────
            # Primary path: canonical prefixes (mcp__/skill__/node__).

            # MCP 工具 (canonical): mcp__<server_id>__<tool_name>
            if function_name.startswith("mcp__"):
                return await self._exec_mcp_tool(function_name, args)

            # Skill 工具 (canonical): skill__<skill_id>
            if function_name.startswith("skill__"):
                return await self._exec_skill_tool(function_name, args)

            # Node 工具 (canonical): node__<node_id>__<action>
            if function_name.startswith("node__"):
                parts = function_name.split("__", 2)
                if len(parts) >= 3:
                    node_id_part, action_part = parts[1], parts[2]
                    if executor:
                        result = await executor(node_id_part, action_part, args)
                        return json.dumps(result, ensure_ascii=False)
                return json.dumps({"error": f"node__ tool dispatch unavailable for: {function_name}"})

            # ── COMPAT ALIAS dispatch (legacy single-underscore prefix) ───────
            # Compatibility aliases only — not the primary exposed form.
            # New integrations MUST use canonical double-underscore prefixes above.

            # MCP 工具 (legacy compat alias): mcp_<server_id>_<tool_name>
            if function_name.startswith("mcp_"):
                logger.debug(
                    "Scheduler: legacy mcp_ prefix used for '%s'; "
                    "prefer canonical mcp__<server>__<tool> form.",
                    function_name,
                )
                return await self._exec_mcp_tool(function_name, args)

            # 节点工具 (legacy compat alias): call_Node_xxx
            if function_name.startswith("call_"):
                logger.debug(
                    "Scheduler: legacy call_ prefix used for '%s'; "
                    "prefer canonical node__<id>__<action> form.",
                    function_name,
                )
                node_id = function_name.replace("call_", "")
                action = args.get("action", "execute")
                params = args.get("params", {})

                if executor:
                    result = await executor(node_id, action, params)
                    return json.dumps(result, ensure_ascii=False)
                return json.dumps({"error": "No executor available"})

            # Skill 工具 (legacy compat alias): skill_<name>
            if function_name.startswith("skill_"):
                logger.debug(
                    "Scheduler: legacy skill_ prefix used for '%s'; "
                    "prefer canonical skill__<id> form.",
                    function_name,
                )
                return await self._exec_skill_tool(function_name, args)

            return json.dumps({"error": f"Unknown tool: {function_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _exec_send_to_device(self, args: Dict, context: Dict) -> str:
        """发送任务到指定设备

        PR-3: Execution Spine Integration.
        Ingress is recorded in the execution spine log via
        ``core.execution_spine.record_legacy_ingress`` so that operator
        tooling can trace scheduler dispatches back to the canonical spine.
        When a ``CommandRouter`` is available in *context* the request is
        routed through ``CommandRouter.route_envelope`` (canonical spine);
        otherwise the existing WS / ADB fallback paths are used unchanged.
        """
        import uuid as _uuid
        device_id = args.get("device_id", "")
        task_type = args.get("task_type", "")
        payload = args.get("payload", {})
        # PR-2: Use canonical interop layer to extract/stamp correlation fields
        # so every dispatch carries consistent task_id / trace_id / session_id.
        try:
            from core.message_interop import extract_correlation as _extract_corr
            _corr = _extract_corr(args)
            task_id = _corr.task_id
            trace_id = _corr.trace_id
        except Exception:
            task_id = args.get("task_id") or f"task_{_uuid.uuid4().hex[:16]}"
            trace_id = args.get("trace_id") or f"trace_{_uuid.uuid4().hex[:12]}"

        # PR-507: Front-load CanonicalTask creation — establish task ontology
        # before recording ingress or normalizing to envelope.
        try:
            from core.task_adapter import adapt_to_canonical_task as _adapt
            from core.canonical_task import TaskOrigin as _TaskOrigin
            _canonical = _adapt(
                {
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "tool_name": task_type,
                    "targets": [device_id] if device_id else [],
                    "args": payload or {},
                },
                origin=_TaskOrigin.SCHEDULER,
            )
            # Propagate canonical identity so all downstream steps share ids.
            task_id = _canonical.identity.task_id
            trace_id = _canonical.identity.trace_id
            logger.debug(
                "_exec_send_to_device: CanonicalTask front-loaded task_id=%s trace_id=%s",
                task_id, trace_id,
            )
        except Exception as _ct_err:
            logger.debug(
                "_exec_send_to_device: CanonicalTask front-load unavailable "
                "(graceful degradation — continuing with existing ids): %s", _ct_err
            )

        # PR-3: Record ingress in execution spine log.
        try:
            from core.execution_spine import (
                ExecutionIngressSource,
                record_legacy_ingress,
            )
            record_legacy_ingress(
                ExecutionIngressSource.SCHEDULER,
                {**args, "task_id": task_id, "trace_id": trace_id},
                reason="scheduler._exec_send_to_device → canonical spine",
            )
        except Exception:
            pass

        # PR-3: Attempt canonical spine routing via CommandRouter when available.
        cmd_router = (context.get("command_router") if context else None)
        if cmd_router is None:
            try:
                from core.command_router import get_command_router as _gcr
                cmd_router = _gcr()
            except Exception:
                cmd_router = None

        if cmd_router is not None:
            try:
                from core.execution_spine import (
                    ExecutionIngressSource,
                    normalize_ingress_to_envelope,
                )
                _envelope = normalize_ingress_to_envelope(
                    {
                        "task_id": task_id,
                        "trace_id": trace_id,
                        "tool_name": task_type,
                        "targets": [device_id] if device_id else [],
                        "args": payload,
                    },
                    source=ExecutionIngressSource.SCHEDULER,
                )
                result = await cmd_router.route_envelope(_envelope)
                return json.dumps(result, ensure_ascii=False)
            except Exception as _spine_err:
                logger.debug(
                    "_exec_send_to_device: spine routing failed (%s); "
                    "falling back to direct WS/ADB path",
                    _spine_err,
                )

        # 通过 WebSocket connection_manager 发送
        ws_sender = context.get("ws_sender") if context else None
        if ws_sender:
            try:
                result = await ws_sender(device_id, {
                    "type": "task",
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "task_type": task_type,
                    "payload": payload,
                })
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"WS send failed: {e}"})

        # fallback: 通过 executor 尝试 ADB 节点
        executor = context.get("executor") if context else None
        if executor:
            try:
                result = await executor("Node_33_ADB", task_type, {
                    "device_id": device_id,
                    **payload,
                })
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"ADB executor failed: {e}"})

        return json.dumps({
            "status": "queued",
            "device_id": device_id,
            "task_id": task_id,
            "trace_id": trace_id,
            "task_type": task_type,
            "note": "Device not connected via WS, command queued",
        })

    async def _exec_broadcast(self, args: Dict, context: Dict) -> str:
        """广播到所有设备

        Stage 10: CanonicalTask is registered in TaskGraphRuntime for the
        broadcast-level task so that broadcast execution paths participate in
        task-graph tracking (closing the gap vs _exec_relay and _exec_mesh_send
        which already register in TaskGraphRuntime).
        Ingress also recorded in execution spine log for observability.
        """
        import uuid as _uuid_bc
        task_type = args.get("task_type", "")
        payload = args.get("payload", {})
        devices = context.get("devices", {}) if context else {}

        # Stage 10: Record ingress in execution spine log.
        try:
            from core.execution_spine import ExecutionIngressSource, record_legacy_ingress
            record_legacy_ingress(
                ExecutionIngressSource.SCHEDULER,
                args,
                reason="scheduler._exec_broadcast → canonical spine",
            )
        except Exception:
            pass

        # Stage 10: Register broadcast task in TaskGraphRuntime so broadcast
        # execution is visible to the task graph (mirrors relay/mesh_send paths).
        _bc_task_id = args.get("task_id") or f"broadcast_{_uuid_bc.uuid4().hex[:16]}"
        try:
            from core.task_adapter import adapt_to_canonical_task as _adapt_bc
            from core.canonical_task import TaskOrigin as _TO_bc
            _bc_canonical = _adapt_bc(
                {
                    "task_id": _bc_task_id,
                    "trace_id": args.get("trace_id") or "",
                    "tool_name": task_type or "broadcast",
                    "targets": list(devices.keys()),
                    "args": args,
                },
                origin=_TO_bc.SCHEDULER,
            )
            _bc_task_id = _bc_canonical.identity.task_id
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr_bc,
                WorkflowContributorKind as _WCK_bc,
            )
            # Use register_canonical_task (not register_envelope) so that
            # CanonicalTask's intent.tool_name is read correctly.
            _get_tgr_bc().register_canonical_task(
                _bc_canonical,
                contributor=_WCK_bc.COMMAND_ROUTER,
            )
        except Exception as _bc_tgr_err:
            logger.debug(
                "_exec_broadcast: TaskGraphRuntime registration skipped: %s", _bc_tgr_err
            )

        results = {}
        for did in devices:
            r = await self._exec_send_to_device(
                {"device_id": did, "task_id": _bc_task_id, "task_type": task_type, "payload": payload},
                context,
            )
            results[did] = r

        return json.dumps({"broadcast_results": results, "broadcast_task_id": _bc_task_id}, ensure_ascii=False)

    async def _exec_relay(self, args: Dict, context: Dict) -> str:
        """设备间中继转发

        PR-3: Ingress recorded in execution spine log.
        PR-513 / GAP-512-002: CanonicalTask registered in TaskGraphRuntime.
        PR-B: Spine routing attempted via CommandRouter.route_envelope() before
        falling back to the ProxyRelay path.
        """
        # PR-3: Record ingress in execution spine log.
        try:
            from core.execution_spine import ExecutionIngressSource, record_legacy_ingress
            record_legacy_ingress(
                ExecutionIngressSource.SCHEDULER,
                args,
                reason="scheduler._exec_relay (relay_to_device) → canonical spine",
            )
        except Exception:
            pass
        # PR-513 / GAP-512-002: Front-load CanonicalTask and register in TaskGraphRuntime
        # so that relay-path tasks are covered by task-graph realization (PR-508).
        try:
            import uuid as _uuid_relay
            from core.task_adapter import adapt_to_canonical_task as _adapt_relay
            from core.canonical_task import TaskOrigin as _TO_relay
            _relay_canonical = _adapt_relay(
                {
                    "task_id": args.get("task_id") or f"relay_{_uuid_relay.uuid4().hex[:16]}",
                    "trace_id": args.get("trace_id") or "",
                    "tool_name": "relay_to_device",
                    "targets": [args.get("target_device", "")] if args.get("target_device") else [],
                    "args": args,
                },
                origin=_TO_relay.SCHEDULER,
            )
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr_relay,
                WorkflowContributorKind as _WCK_relay,
            )
            _get_tgr_relay().register_envelope(
                _relay_canonical,
                contributor=_WCK_relay.COMMAND_ROUTER,
            )
        except Exception as _relay_tgr_err:
            logger.debug(
                "_exec_relay: TaskGraphRuntime registration skipped: %s", _relay_tgr_err
            )

        # PR-B: Attempt canonical spine routing via CommandRouter.route_envelope()
        # before falling back to the ProxyRelay implementation.  This ensures
        # relay_to_device participates in the execution spine rather than
        # bypassing it entirely.
        _cmd_router_relay = context.get("command_router") if context else None
        if _cmd_router_relay is None:
            try:
                from core.command_router import get_command_router as _gcr_relay
                _cmd_router_relay = _gcr_relay()
            except Exception:
                _cmd_router_relay = None

        if _cmd_router_relay is not None:
            try:
                from core.execution_spine import (
                    ExecutionIngressSource as _EIS_relay,
                    normalize_ingress_to_envelope as _norm_relay,
                )
                _envelope_relay = _norm_relay(
                    {
                        "task_id": args.get("task_id") or "",
                        "trace_id": args.get("trace_id") or "",
                        "tool_name": "relay_to_device",
                        "targets": [args.get("target_device", "")] if args.get("target_device") else [],
                        "args": args,
                    },
                    source=_EIS_relay.SCHEDULER,
                )
                _relay_spine_result = await _cmd_router_relay.route_envelope(_envelope_relay)
                return json.dumps(_relay_spine_result, ensure_ascii=False)
            except Exception as _spine_relay_err:
                logger.debug(
                    "_exec_relay: spine routing failed (%s); falling back to ProxyRelay",
                    _spine_relay_err,
                )

        _allow_legacy_fallback = str(
            args.get("allow_legacy_scheduler_fallback")
            or (context or {}).get("allow_legacy_scheduler_fallback")
            or os.environ.get("GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not _allow_legacy_fallback:
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        "canonical_command_router_unavailable: relay legacy fallback blocked "
                        "(set allow_legacy_scheduler_fallback=true to opt in)"
                    ),
                    "error_code": "CANONICAL_ROUTE_REQUIRED",
                    "legacy_fallback_blocked": True,
                    "canonical_route_required": True,
                },
                ensure_ascii=False,
            )

        try:
            from core.proxy_relay import get_proxy_relay, RelayRequest
            relay = get_proxy_relay()
            req = RelayRequest(
                source_device=args.get("source_device", ""),
                target_device=args.get("target_device", ""),
                payload_type=args.get("payload_type", "task"),
                payload=args.get("payload", {}),
            )
            result = await relay.relay(req)
            return json.dumps(result.to_dict(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Relay failed: {e}"})

    async def _exec_code(self, args: Dict) -> str:
        """安全代码执行"""
        try:
            from core.safe_executor import get_safe_executor
            executor = get_safe_executor()
            result = await executor.execute(
                code=args.get("code", ""),
                language=args.get("language", "python"),
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Code execution failed: {e}"})

    async def _exec_mesh_send(self, args: Dict) -> str:
        """P2P Mesh 发送 — 自动选路 (直连 / 中继)

        PR-3: Ingress recorded in execution spine log.
        PR-513 / GAP-512-002: CanonicalTask registered in TaskGraphRuntime.
        PR-B: Spine routing attempted via CommandRouter.route_envelope() before
        falling back to the MeshCoordinator path.
        """
        # PR-3: Record ingress in execution spine log.
        try:
            from core.execution_spine import ExecutionIngressSource, record_legacy_ingress
            record_legacy_ingress(
                ExecutionIngressSource.SCHEDULER,
                args,
                reason="scheduler._exec_mesh_send (mesh_send) → canonical spine",
            )
        except Exception:
            pass
        # PR-513 / GAP-512-002: Front-load CanonicalTask and register in TaskGraphRuntime.
        try:
            import uuid as _uuid_mesh
            from core.task_adapter import adapt_to_canonical_task as _adapt_mesh
            from core.canonical_task import TaskOrigin as _TO_mesh
            _mesh_canonical = _adapt_mesh(
                {
                    "task_id": args.get("task_id") or f"mesh_{_uuid_mesh.uuid4().hex[:16]}",
                    "trace_id": args.get("trace_id") or "",
                    "tool_name": "mesh_send",
                    "targets": [args.get("target_device", "")] if args.get("target_device") else [],
                    "args": args,
                },
                origin=_TO_mesh.SCHEDULER,
            )
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr_mesh,
                WorkflowContributorKind as _WCK_mesh,
            )
            _get_tgr_mesh().register_envelope(
                _mesh_canonical,
                contributor=_WCK_mesh.COMMAND_ROUTER,
            )
        except Exception as _mesh_tgr_err:
            logger.debug(
                "_exec_mesh_send: TaskGraphRuntime registration skipped: %s", _mesh_tgr_err
            )

        # PR-B: Attempt canonical spine routing via CommandRouter.route_envelope()
        # before falling back to the MeshCoordinator implementation.  This ensures
        # mesh_send participates in the execution spine rather than bypassing it.
        try:
            from core.command_router import get_command_router as _gcr_mesh
            _cmd_router_mesh = _gcr_mesh()
        except Exception:
            _cmd_router_mesh = None

        if _cmd_router_mesh is not None:
            try:
                from core.execution_spine import (
                    ExecutionIngressSource as _EIS_mesh,
                    normalize_ingress_to_envelope as _norm_mesh,
                )
                _envelope_mesh = _norm_mesh(
                    {
                        "task_id": args.get("task_id") or "",
                        "trace_id": args.get("trace_id") or "",
                        "tool_name": "mesh_send",
                        "targets": [args.get("target_device", "")] if args.get("target_device") else [],
                        "args": args,
                    },
                    source=_EIS_mesh.SCHEDULER,
                )
                _mesh_spine_result = await _cmd_router_mesh.route_envelope(_envelope_mesh)
                return json.dumps(_mesh_spine_result, ensure_ascii=False)
            except Exception as _spine_mesh_err:
                logger.debug(
                    "_exec_mesh_send: spine routing failed (%s); falling back to MeshCoordinator",
                    _spine_mesh_err,
                )

        _allow_legacy_fallback = str(
            args.get("allow_legacy_scheduler_fallback")
            or os.environ.get("GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK", "")
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not _allow_legacy_fallback:
            return json.dumps(
                {
                    "success": False,
                    "error": (
                        "canonical_command_router_unavailable: mesh legacy fallback blocked "
                        "(set allow_legacy_scheduler_fallback=true to opt in)"
                    ),
                    "error_code": "CANONICAL_ROUTE_REQUIRED",
                    "legacy_fallback_blocked": True,
                    "canonical_route_required": True,
                },
                ensure_ascii=False,
            )

        try:
            from core.mesh_coordinator import get_mesh_coordinator
            mesh = get_mesh_coordinator()
            result = await mesh.send(
                target_device=args.get("target_device", ""),
                payload=args.get("payload", {}),
                payload_type=args.get("payload_type", "task"),
                source_device=args.get("source_device", ""),
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Mesh send failed: {e}"})

    async def _exec_find_device(self, args: Dict, context: Dict) -> str:
        """按类型或名称查找在线设备"""
        device_type = args.get("device_type", "").lower()
        device_name = args.get("device_name", "").lower()

        devices = context.get("devices", {}) if context else {}
        for did, info in devices.items():
            if not isinstance(info, dict):
                continue
            dt = (info.get("device_type", "") or "").lower()
            dn = (info.get("device_name", "") or info.get("name", "") or "").lower()
            online = info.get("online", info.get("status") == "online")
            if not online:
                continue
            if device_type and device_type in dt:
                return json.dumps({"device_id": did, **info}, ensure_ascii=False)
            if device_name and device_name in dn:
                return json.dumps({"device_id": did, **info}, ensure_ascii=False)

        return json.dumps({"error": f"No online device found matching type={device_type} name={device_name}"})

    async def _exec_mcp_tool(self, function_name: str, args: Dict) -> str:
        """调用 MCP 工具.

        Accepts both canonical and legacy naming formats:
          - Canonical: ``mcp__<server_id>__<tool_name>``  (primary, double-underscore)
          - Legacy compat: ``mcp_<server_id>_<tool_name>``  (single-underscore, alias only)

        server_id 由 mcp_loader 生成（8 位不含下划线的十六进制），
        tool_name 可包含下划线。
        """
        try:
            from core.mcp_loader import mcp_loader
            if function_name.startswith("mcp__"):
                # Canonical double-underscore form: mcp__<server_id>__<tool_name>
                parts = function_name[len("mcp__"):].split("__", 1)
                if len(parts) != 2:
                    return json.dumps({"error": f"Invalid canonical MCP tool name: {function_name}"})
                server_id, tool_name = parts
            else:
                # Legacy compat: mcp_<server_id>_<tool_name>
                parts = function_name[len("mcp_"):].split("_", 1)
                if len(parts) != 2:
                    return json.dumps({"error": f"Invalid MCP tool name: {function_name}"})
                server_id, tool_name = parts
            result = await mcp_loader.call_tool(server_id, tool_name, args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"MCP tool failed: {e}"})

    async def _exec_skill_tool(self, function_name: str, args: Dict) -> str:
        """调用已注册的 Skill.

        Accepts both canonical and legacy naming formats:
          - Canonical: ``skill__<skill_id>``  (primary, double-underscore)
          - Legacy compat: ``skill_<name>``  (single-underscore, alias only)
        """
        try:
            from core.skill_loader import skill_loader as loader
            if function_name.startswith("skill__"):
                # Canonical double-underscore form.
                skill_name = function_name[len("skill__"):]
            else:
                # Legacy compat: strip single "skill_" prefix.
                skill_name = function_name[len("skill_"):]
            result = await loader.execute(skill_name, **args)
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False)
            return str(result)
        except Exception as e:
            return json.dumps({"error": f"Skill execution failed: {e}"})

    def _select_relevant_tools(self, instruction: str, max_tools: int = 20) -> List[Dict]:
        """根据指令选择最相关的工具 (避免 token 爆炸)"""
        if len(self.tools_cache) <= max_tools:
            return self.tools_cache

        # 内置工具始终保留
        selected = list(_BUILTIN_TOOLS)
        remaining = [t for t in self.tools_cache if t not in _BUILTIN_TOOLS]

        # 关键词匹配优先
        inst_lower = instruction.lower()
        scored = []
        for tool in remaining:
            func_name = tool["function"]["name"].lower()
            desc = tool["function"].get("description", "").lower()
            score = 0
            # 名称关键词匹配
            for word in inst_lower.split():
                if len(word) > 2 and (word in func_name or word in desc):
                    score += 10
            # 特定类型匹配
            if any(k in inst_lower for k in ["文件", "file", "目录"]) and "file" in func_name:
                score += 20
            if any(k in inst_lower for k in ["网页", "web", "搜索"]) and "web" in func_name:
                score += 20
            if any(k in inst_lower for k in ["截图", "screenshot", "ocr"]) and ("ocr" in func_name or "vision" in func_name):
                score += 20
            if any(k in inst_lower for k in ["代码", "code", "编程", "bug", "测试", "test", "重构", "refactor"]) and ("code" in func_name or "coding" in func_name):
                score += 20
            if any(k in inst_lower for k in ["学习", "learn", "经验", "experience", "知识", "knowledge", "pattern", "模式"]) and ("learning" in func_name or "knowledge" in func_name):
                score += 20
            if any(k in inst_lower for k in ["反思", "reflect", "评估", "assess", "认知", "cognition", "优化", "optimize", "分析", "analyze"]) and ("metacognition" in func_name or "cognit" in desc):
                score += 20
            if any(k in inst_lower for k in ["手机", "android", "安卓", "adb"]) and "adb" in func_name:
                score += 20
            if any(k in inst_lower for k in ["shell", "命令", "终端"]) and "shell" in func_name:
                score += 20
            if any(k in inst_lower for k in ["windows", "电脑", "桌面", "窗口", "点击", "输入"]) and func_name.startswith("mcp_"):
                score += 20
            scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        budget = max_tools - len(selected)
        selected.extend([t for _, t in scored[:budget]])

        return selected
