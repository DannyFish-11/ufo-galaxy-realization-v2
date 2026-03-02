"""
UFO Galaxy - 自主调度器 (Autonomous Scheduler)
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

        system_prompt = f"""You are the central AI scheduler of UFO Galaxy, a multi-device agent operating system.
Your goal: satisfy the user's request by calling the available tools.
You operate in a ReAct loop: Think → Act (call tools) → Observe results → Think again.

RULES:
1. For device operations (open app, click, swipe, type, screenshot): use 'send_to_device' tool with the target device_id.
2. For system operations (file, web, shell, OCR): use the appropriate 'call_Node_*' tool.
3. Always explain what you're doing before calling tools.
4. After tool execution, interpret the result and decide next steps.
5. When the task is fully done, provide a clear summary in the user's language.

DEVICE CONTEXT:
{device_context}

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

            # 内置工具: mesh_send (Phase 5)
            if function_name == "mesh_send":
                return await self._exec_mesh_send(args)

            # 节点工具: call_Node_xxx
            if function_name.startswith("call_"):
                node_id = function_name.replace("call_", "")
                action = args.get("action", "execute")
                params = args.get("params", {})

                if executor:
                    result = await executor(node_id, action, params)
                    return json.dumps(result, ensure_ascii=False)
                return json.dumps({"error": "No executor available"})

            return json.dumps({"error": f"Unknown tool: {function_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _exec_send_to_device(self, args: Dict, context: Dict) -> str:
        """发送任务到指定设备"""
        device_id = args.get("device_id", "")
        task_type = args.get("task_type", "")
        payload = args.get("payload", {})

        # 通过 WebSocket connection_manager 发送
        ws_sender = context.get("ws_sender") if context else None
        if ws_sender:
            try:
                result = await ws_sender(device_id, {
                    "type": "task",
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
            "task_type": task_type,
            "note": "Device not connected via WS, command queued",
        })

    async def _exec_broadcast(self, args: Dict, context: Dict) -> str:
        """广播到所有设备"""
        task_type = args.get("task_type", "")
        payload = args.get("payload", {})
        devices = context.get("devices", {}) if context else {}

        results = {}
        for did in devices:
            r = await self._exec_send_to_device(
                {"device_id": did, "task_type": task_type, "payload": payload},
                context,
            )
            results[did] = r

        return json.dumps({"broadcast_results": results}, ensure_ascii=False)

    async def _exec_relay(self, args: Dict, context: Dict) -> str:
        """设备间中继转发"""
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
        """P2P Mesh 发送 — 自动选路 (直连 / 中继)"""
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
            if any(k in inst_lower for k in ["代码", "code", "编程"]) and "code" in func_name:
                score += 20
            if any(k in inst_lower for k in ["手机", "android", "安卓", "adb"]) and "adb" in func_name:
                score += 20
            if any(k in inst_lower for k in ["shell", "命令", "终端"]) and "shell" in func_name:
                score += 20
            scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        budget = max_tools - len(selected)
        selected.extend([t for _, t in scored[:budget]])

        return selected
