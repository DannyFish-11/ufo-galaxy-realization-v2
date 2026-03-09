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

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

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

    def __init__(self):
        self._initialized = False
        self._session_memory: Dict[str, List[Dict]] = {}
        self._request_count = 0
        self._error_count = 0
        self._start_time = time.time()
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
    # handle_chat — 纯聊天 (无设备命令)
    # ========================================================================

    async def handle_chat(self, message: str, session_id: str) -> dict:
        """纯聊天 — 使用 MultiLLMRouter 进行 LLM 对话

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
                        "你是 Galaxy 智能助手 (OpenClawd)，一个 L4 级自主性 AI 系统。\n"
                        "你可以帮助用户进行对话、任务管理、设备控制、代码执行等操作。\n"
                        "当用户需要操作设备时，请告知他们描述具体操作即可。"
                    ),
                },
            ]

            # 添加会话历史
            session_history = self._session_memory.get(session_id, [])
            for turn in session_history[-10:]:
                messages.append(turn)

            messages.append({"role": "user", "content": message})

            # 调用 LLM
            response = await router.chat(
                messages=messages,
                task_type="GENERAL",
                max_tokens=4096,
            )

            return {
                "success": True,
                "response": response.content,
                "metadata": {
                    "provider": response.provider,
                    "model": response.model,
                    "latency_ms": round(response.latency_ms, 1),
                    "tokens": response.input_tokens + response.output_tokens,
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

            # 判断是否需要团队协作
            targets = intent.targets if intent else []
            is_complex = len(targets) > 2 or (
                intent and intent.intent in ("workflow", "batch_task", "multi_device")
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
        """执行团队协作任务"""
        try:
            from core.agent_team import TeamManager, TeamStrategy

            manager = TeamManager(agent_factory=factory, llm_router=router)

            # 选择团队策略
            if intent and intent.intent == "workflow":
                strategy = "specialized"
            elif intent and len(intent.targets) > 3:
                strategy = "swarm"
            else:
                strategy = "parallel"

            team = await manager.create_team(strategy=strategy, task_hint=message)
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
                },
            }

        except Exception as e:
            logger.warning(f"团队协作失败，降级到单 Agent: {e}")
            # 降级到单 Agent
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
