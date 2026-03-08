"""
LocalAgentRuntime — 端侧 Agent 执行沙盒
=======================================

Phase 1 Matrix OS 核心组件。

接收 AgentManifest → 反序列化 → 在本地执行 Thought/Action/Observation 循环。

执行模式:
1. REACT: LLM 驱动的 ReAct Loop (需要 LLM API)
2. SEQUENTIAL: 按顺序执行预定义动作列表 (无需 LLM)
3. AUTONOMOUS: 先发现本地 MCP 工具, 再自主规划执行

日志回传:
- 每一步 Thought/Action/Observation 都通过回调函数上报
- 上报格式兼容 AIP v2 AGENT_STATUS 消息类型
"""

import asyncio
import json
import logging
import time
import uuid
import traceback
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field

logger = logging.getLogger("Galaxy.LocalRuntime")


@dataclass
class AgentStep:
    """单步执行记录"""
    step_id: int
    thought: str = ""
    action: str = ""
    action_params: Dict = field(default_factory=dict)
    observation: str = ""
    timestamp: float = field(default_factory=time.time)
    success: bool = True

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "thought": self.thought,
            "action": self.action,
            "action_params": self.action_params,
            "observation": self.observation,
            "timestamp": self.timestamp,
            "success": self.success,
        }


@dataclass
class RuntimeResult:
    """执行结果"""
    manifest_id: str
    success: bool
    steps: List[Dict] = field(default_factory=list)
    final_output: str = ""
    error: str = ""
    total_steps: int = 0
    duration_ms: float = 0

    def to_dict(self) -> Dict:
        return {
            "manifest_id": self.manifest_id,
            "success": self.success,
            "steps": self.steps,
            "final_output": self.final_output,
            "error": self.error,
            "total_steps": self.total_steps,
            "duration_ms": self.duration_ms,
        }


# 工具执行回调类型: (tool_name, params) -> result_dict
ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]

# 状态上报回调: (manifest_id, step: AgentStep) -> None
StatusReporter = Callable[[str, Dict[str, Any]], Awaitable[None]]


class LocalAgentRuntime:
    """
    端侧 Agent 运行时

    职责:
    1. 反序列化 AgentManifest
    2. 发现本地工具 (MCP Schema)
    3. 执行 Thought/Action/Observation 循环
    4. 上报每一步状态
    5. 返回最终结果
    """

    def __init__(
        self,
        tool_executor: ToolExecutor = None,
        status_reporter: StatusReporter = None,
        llm_chat: Callable = None,
    ):
        """
        Args:
            tool_executor: 工具执行回调 (必须)
            status_reporter: 状态上报回调 (可选, 用于回传到服务端)
            llm_chat: LLM 对话回调 (REACT 模式需要)
                      签名: async (messages: List[Dict], tools: List[Dict]) -> Dict
                      返回: {"content": str, "tool_calls": [{"name": str, "arguments": dict}] | None}
        """
        self._tool_executor = tool_executor
        self._status_reporter = status_reporter
        self._llm_chat = llm_chat
        self._local_tools: Dict[str, Dict] = {}  # MCP 工具缓存

    async def execute(self, manifest_dict: Dict[str, Any]) -> RuntimeResult:
        """
        执行 AgentManifest

        这是核心入口 — 端侧收到 AGENT_DEPLOY 消息后调用此方法。
        """
        start_time = time.time()
        manifest_id = manifest_dict.get("manifest_id", str(uuid.uuid4()))

        try:
            mode = manifest_dict.get("execution_mode", "react")

            # 1. 工具发现 (如果启用)
            if manifest_dict.get("discover_local_tools", True):
                await self._discover_tools(manifest_dict)

            # 2. 按模式执行
            if mode == "sequential":
                result = await self._execute_sequential(manifest_dict)
            elif mode == "react":
                result = await self._execute_react(manifest_dict)
            elif mode == "autonomous":
                result = await self._execute_autonomous(manifest_dict)
            else:
                result = RuntimeResult(
                    manifest_id=manifest_id,
                    success=False,
                    error=f"Unknown execution mode: {mode}",
                )

            result.duration_ms = (time.time() - start_time) * 1000
            return result

        except Exception as e:
            logger.error(f"Runtime execution failed: {e}\n{traceback.format_exc()}")
            return RuntimeResult(
                manifest_id=manifest_id,
                success=False,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    # ================================================================
    # 工具发现
    # ================================================================

    async def _discover_tools(self, manifest_dict: Dict):
        """从 Manifest 声明 + 本地 MCP 端点发现工具"""
        # 从 Manifest 自带的工具声明
        for tool in manifest_dict.get("tools", []):
            name = tool.get("name", "")
            if name:
                self._local_tools[name] = tool

        # 从 MCP 端点动态发现 (如果指定)
        mcp_endpoint = manifest_dict.get("mcp_endpoint", "")
        if mcp_endpoint:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{mcp_endpoint}/mcp/tools")
                    if resp.status_code == 200:
                        tools_data = resp.json()
                        for tool in tools_data.get("tools", []):
                            self._local_tools[tool["name"]] = tool
                        logger.info(f"MCP 发现 {len(tools_data.get('tools', []))} 个工具: {mcp_endpoint}")
            except Exception as e:
                logger.warning(f"MCP 工具发现失败: {e}")

        logger.info(f"工具总计: {len(self._local_tools)} ({list(self._local_tools.keys())})")

    # ================================================================
    # 顺序执行模式
    # ================================================================

    async def _execute_sequential(self, manifest_dict: Dict) -> RuntimeResult:
        """顺序执行预定义任务列表"""
        manifest_id = manifest_dict["manifest_id"]
        tasks = manifest_dict.get("tasks", [])
        steps = []

        for i, task in enumerate(tasks):
            step = AgentStep(step_id=i + 1)
            action = task.get("action", "")
            params = task.get("params", {})
            instruction = task.get("instruction", "")

            step.thought = f"Executing step {i+1}: {instruction or action}"
            step.action = action
            step.action_params = params

            # 上报
            await self._report_status(manifest_id, step)

            # 执行
            if self._tool_executor and action:
                try:
                    result = await self._tool_executor(action, params)
                    step.observation = json.dumps(result, ensure_ascii=False)[:500]
                    step.success = result.get("success", True) if isinstance(result, dict) else True
                except Exception as e:
                    step.observation = f"Error: {e}"
                    step.success = False
            else:
                step.observation = f"Skipped (no executor or no action): {instruction}"

            steps.append(step.to_dict())
            await self._report_status(manifest_id, step)

        return RuntimeResult(
            manifest_id=manifest_id,
            success=all(s.get("success", True) for s in steps),
            steps=steps,
            final_output=f"Completed {len(steps)} sequential steps",
            total_steps=len(steps),
        )

    # ================================================================
    # ReAct 模式
    # ================================================================

    async def _execute_react(self, manifest_dict: Dict) -> RuntimeResult:
        """LLM 驱动的 ReAct Loop"""
        manifest_id = manifest_dict["manifest_id"]
        max_turns = manifest_dict.get("max_react_turns", 10)
        system_prompt = manifest_dict.get("system_prompt", "")
        tasks = manifest_dict.get("tasks", [])

        # 构建初始用户消息
        user_instruction = "\n".join(
            t.get("instruction", "") for t in tasks if t.get("instruction")
        ) or "Execute the assigned tasks."

        # 构建工具列表 (OpenAI function calling 格式)
        tool_defs = self._build_openai_tools()

        messages = [
            {"role": "system", "content": system_prompt or "You are an autonomous agent. Use tools to accomplish the task."},
            {"role": "user", "content": user_instruction},
        ]

        steps = []
        final_reply = ""

        for turn in range(max_turns):
            step = AgentStep(step_id=turn + 1)

            # 调用 LLM
            if not self._llm_chat:
                step.thought = "No LLM available — cannot run ReAct mode"
                step.success = False
                steps.append(step.to_dict())
                break

            try:
                llm_result = await self._llm_chat(messages, tool_defs)
            except Exception as e:
                step.thought = f"LLM call failed: {e}"
                step.success = False
                steps.append(step.to_dict())
                break

            content = llm_result.get("content", "")
            tool_calls = llm_result.get("tool_calls")

            step.thought = content or "(thinking...)"

            if not tool_calls:
                # LLM 认为完成
                final_reply = content
                steps.append(step.to_dict())
                await self._report_status(manifest_id, step)
                break

            # 执行 tool calls
            for tc in tool_calls:
                tc_name = tc.get("name", "")
                tc_args = tc.get("arguments", {})
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except json.JSONDecodeError:
                        tc_args = {}

                step.action = tc_name
                step.action_params = tc_args

                await self._report_status(manifest_id, step)

                # 执行工具
                if self._tool_executor:
                    try:
                        result = await self._tool_executor(tc_name, tc_args)
                        observation = json.dumps(result, ensure_ascii=False)[:1000]
                    except Exception as e:
                        observation = f"Tool execution error: {e}"
                else:
                    observation = f"Tool '{tc_name}' called but no executor available"

                step.observation = observation

                # 追加到 messages (用于下一轮 LLM 调用)
                messages.append({"role": "assistant", "content": content, "tool_calls_raw": tool_calls})
                messages.append({"role": "tool", "name": tc_name, "content": observation})

            steps.append(step.to_dict())
            await self._report_status(manifest_id, step)

        return RuntimeResult(
            manifest_id=manifest_id,
            success=True,
            steps=steps,
            final_output=final_reply or "ReAct loop completed",
            total_steps=len(steps),
        )

    # ================================================================
    # 自主模式
    # ================================================================

    async def _execute_autonomous(self, manifest_dict: Dict) -> RuntimeResult:
        """自主执行: 先发现工具, 再自主规划"""
        # 自主模式 = ReAct 模式 + 工具发现结果注入到 system_prompt
        tool_info = "\n".join(
            f"- {name}: {t.get('description', '')}" for name, t in self._local_tools.items()
        )
        manifest_dict = dict(manifest_dict)
        manifest_dict["system_prompt"] = (
            manifest_dict.get("system_prompt", "") +
            f"\n\nAVAILABLE LOCAL TOOLS (discovered via MCP):\n{tool_info}\n"
            "Use these tools to accomplish your task autonomously."
        )
        return await self._execute_react(manifest_dict)

    # ================================================================
    # 辅助方法
    # ================================================================

    def _build_openai_tools(self) -> List[Dict]:
        """将本地工具转换为 OpenAI function calling 格式"""
        tools = []
        for name, tool in self._local_tools.items():
            params = tool.get("parameters", {})
            if not isinstance(params, dict) or "type" not in params:
                params = {
                    "type": "object",
                    "properties": params,
                }
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description", f"Tool: {name}"),
                    "parameters": params,
                }
            })
        return tools

    async def _report_status(self, manifest_id: str, step: AgentStep):
        """上报执行状态"""
        if self._status_reporter:
            try:
                await self._status_reporter(manifest_id, step.to_dict())
            except Exception as e:
                logger.warning(f"Status report failed: {e}")

        logger.info(
            f"[Agent {manifest_id[:8]}] Step {step.step_id}: "
            f"T={step.thought[:60]}... A={step.action} "
            f"O={step.observation[:60]}..."
        )
