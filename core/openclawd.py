"""
Galaxy-Nexus 星枢核心智能体 — OpenClawd
=========================================

统一智能交互入口，串联已有模块实现完整的意图解析 -> 模型选择 -> 执行 -> 响应流水线:

模块串联:
  - ai_intent.py        -> 意图解析 (IntentParser / ConversationMemory)
  - multi_llm_router.py -> 模型选择 (MultiLLMRouter / TaskType)
  - agent_factory.py    -> Agent 创建/复用 (AgentFactory / TaskAgent)
  - agent_team.py       -> 团队协作 (TeamManager / TeamStrategy)
  - device_orchestrator  -> 设备操控
  - mcp_loader.py       -> MCP 协议工具调用
  - skill_loader.py     -> Skill 技能调用

设计原则:
  1. 单例模式 — 全局唯一入口
  2. 懒加载 — 所有模块按需导入，避免循环依赖
  3. 容错降级 — 任何模块不可用时自动降级
  4. 统一响应 — 所有方法返回标准 dict 格式
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger("Galaxy.OpenClawd")


class OpenClawd:
    """Galaxy-Nexus 星枢核心智能体 — 统一智能交互入口

    串联已有模块实现完整的意图解析 -> 模型选择 -> 执行 -> 响应流水线:
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
        logger.info("OpenClawd 星枢核心智能体初始化")

    def _ensure_initialized(self):
        """标记为已初始化 (懒加载模式，模块在各方法内按需导入)"""
        if not self._initialized:
            self._initialized = True
            logger.info("OpenClawd 就绪 — 所有模块将按需懒加载")

    # ========================================================================
    # 主入口
    # ========================================================================

    async def process(
        self,
        message: str,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """主入口 — 解析意图并路由到对应处理器

        Args:
            message: 用户输入的自然语言消息
            device_id: 设备 ID (可选，用于设备操控场景)
            session_id: 会话 ID (可选，用于上下文管理)

        Returns:
            统一响应 dict: {success, response, intent, metadata}
        """
        self._ensure_initialized()
        self._request_count += 1
        t0 = time.monotonic()

        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        try:
            # Step 1: 意图解析
            parsed_intent = await self._parse_intent(message, session_id)

            # Step 2: 记录用户消息到会话记忆
            await self._record_turn(session_id, "user", message)

            # Step 3: 根据意图路由到对应处理器
            intent_type = parsed_intent.intent if parsed_intent else "chat"
            handler_name = self._INTENT_HANDLER_MAP.get(intent_type, "_dispatch_chat")
            if not hasattr(self, handler_name):
                logger.warning(f"Handler {handler_name} not found, falling back to chat")
                handler_name = "_dispatch_chat"
            handler = getattr(self, handler_name)

            result = await handler(
                message=message,
                intent=parsed_intent,
                device_id=device_id,
                session_id=session_id,
            )

            # Step 4: 记录助手回复到会话记忆
            response_text = result.get("response", "")
            await self._record_turn(session_id, "assistant", response_text)

            latency_ms = (time.monotonic() - t0) * 1000

            return {
                "success": result.get("success", True),
                "response": response_text,
                "intent": intent_type,
                "metadata": {
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "confidence": parsed_intent.confidence if parsed_intent else 0.0,
                    "suggestions": parsed_intent.suggestions if parsed_intent else [],
                    "handler": handler_name,
                    **(result.get("metadata", {})),
                },
            }

        except Exception as e:
            self._error_count += 1
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error(f"OpenClawd.process 失败: {e}", exc_info=True)
            return {
                "success": False,
                "response": f"处理请求时发生错误: {str(e)}",
                "intent": "error",
                "metadata": {
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
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
    ) -> dict:
        """纯聊天分派"""
        return await self.handle_chat(message, session_id or "default")

    async def _dispatch_device(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """设备操控分派"""
        if not device_id:
            return {
                "success": False,
                "response": "设备操控需要指定 device_id，请连接设备后重试。",
            }
        return await self.handle_device_command(intent, device_id)

    async def _dispatch_agent(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Agent 任务分派"""
        return await self.handle_agent_task(message, intent)

    async def _dispatch_tool(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """工具调用分派"""
        return await self.handle_tool_call(intent)

    async def _dispatch_status(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
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

    # ========================================================================
    # 工具总线 — 三层统一收集与分发
    # ========================================================================

    def _collect_tools(self) -> List[Dict]:
        """统一收集三层工具（MCP / Skill / Node），转为 OpenAI function calling 格式

        返回格式: [{"type": "function", "function": {"name": "mcp__server__tool", ...}}, ...]
        前缀约定:
          - mcp__<server_id>__<tool_name>   → MCP 协议工具
          - skill__<skill_id>               → Skill 技能
          - node__<node_id>__<action>       → Node 节点操作
        """
        tools: List[Dict] = []

        # ── 层 1: MCP 服务器工具 ──
        try:
            from core.mcp_loader import mcp_loader
            import asyncio

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

        # ── 层 1.5: MCP Gateway 自造工具 ──
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

        # ── 层 2: Skill 技能 ──
        try:
            from core.skill_loader import skill_loader

            for skill_info in skill_loader.list_skills():
                skill_id = skill_info.get("id", "")
                if not skill_id or skill_info.get("status") == "error":
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"skill__{skill_id}",
                        "description": skill_info.get("description", f"Skill: {skill_id}"),
                        "parameters": skill_info.get("parameters", {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "输入参数"}
                            },
                        }),
                    },
                })
        except Exception as e:
            logger.debug(f"收集 Skill 工具失败: {e}")

        # ── 层 3: Node 节点操作 (静态 action 目录 + 注册表验证) ──
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

            # 从静态目录生成工具列表
            for node_id, actions_map in self._CORE_NODE_ACTIONS.items():
                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in actions_map.items():
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"node__{node_id}__{action_name}",
                            "description": f"Node {node_name}: {action_desc}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "params": {"type": "object", "description": "操作参数"}
                                },
                            },
                        },
                    })
        except Exception as e:
            logger.debug(f"收集 Node 工具失败: {e}")

        logger.info(f"工具总线收集完成: {len(tools)} 个工具")
        return tools

    async def _dispatch_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """根据工具名前缀分发到对应执行器

        Args:
            tool_name: 格式为 "mcp__server__tool" / "skill__id" / "node__id__action"
            arguments: 工具参数

        Returns:
            {"success": bool, "result": Any, "error": Optional[str]}
        """
        try:
            if tool_name.startswith("mcp__"):
                parts = tool_name.split("__", 2)
                if len(parts) < 3:
                    return {"success": False, "error": f"无效 MCP 工具名: {tool_name}"}
                server_id, mcp_tool_name = parts[1], parts[2]

                # 特殊处理 gateway 自造工具
                if server_id == "gateway":
                    try:
                        from core.mcp_gateway import get_mcp_gateway
                        gateway = get_mcp_gateway()
                        result = await gateway.execute_tool(mcp_tool_name, arguments)
                        return {"success": True, "result": result}
                    except Exception as e:
                        return {"success": False, "error": f"Gateway 工具执行失败: {e}"}

                from core.mcp_loader import mcp_loader
                result = await mcp_loader.call_tool(server_id, mcp_tool_name, arguments)
                return {"success": True, "result": result}

            elif tool_name.startswith("skill__"):
                skill_id = tool_name[7:]  # len("skill__") == 7
                from core.skill_loader import skill_loader
                result = await skill_loader.execute(skill_id, **arguments)
                return {"success": True, "result": result}

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

            else:
                return {"success": False, "error": f"未知工具前缀: {tool_name}"}

        except Exception as e:
            logger.warning(f"工具执行失败 [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}

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
                if node_info["type"] == "function":
                    func = node_info["execute"]
                    if inspect.iscoroutinefunction(func):
                        result = asyncio.run(func(action, {}))
                    else:
                        result = func(action, {})
                else:
                    method = node_info["instance"].execute
                    if inspect.iscoroutinefunction(method):
                        result = asyncio.run(method(action))
                    else:
                        result = method(action)
                return result

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

        async def _inner_loop():
            nonlocal last_response, total_tokens

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

            # 添加会话历史
            session_history = self._session_memory.get(session_id, [])
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

    async def handle_agent_task(self, message: str, intent) -> dict:
        """复杂任务处理 — 使用 AgentFactory 创建 Agent，必要时组建团队

        Args:
            message: 用户消息
            intent: 解析后的意图 (ParsedIntent)

        Returns:
            Agent 执行结果 dict
        """
        try:
            from core.agent_factory import get_agent_factory
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            factory = get_agent_factory(router)

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
                return await self._execute_team_task(message, intent, factory, router)

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

            # 清理 Agent
            factory.terminate_agent(agent.id)

            return {
                "success": result.get("status") != "error",
                "response": reply,
                "metadata": {
                    "agent_id": agent.id,
                    "agent_role": agent.config.role.value,
                    "template": template,
                    "result_count": len(result.get("results", [])),
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
        """尝试通过 MCP 调用工具"""
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
        """尝试通过 SkillLoader 执行技能"""
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
