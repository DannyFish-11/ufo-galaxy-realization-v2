"""
Galaxy Agentic OS — MCP Dynamic Gateway (Self-Tool-Making)
============================================================

Enhanced MCP gateway that adds dynamic tool generation, hot-reload, and
registry synchronization on top of the existing ``MCPLoader`` singleton.

Self-Tool-Making flow:
  1. Worker TaskResult reports ``error.code == "MISSING_TOOL"``
  2. MasterBrain calls ``mcp_gateway.handle_capability_gap(tool_name, context)``
  3. Gateway uses LLM to generate a Python MCP server script (stdio JSON-RPC)
  4. ACL validates the generated code
  5. SafeExecutor tests it in sandbox
  6. ``MCPLoader.load(name, command=["python", script_path])`` starts the server
  7. Gateway publishes ``MCPToolRegistration`` event via NATS
  8. All workers receive new tool capability

Constraints (see plan 强约束):
  C1  — module-level singleton ``mcp_gateway``
  C2  — emits MCP_TOOL_GENERATED / REGISTERED / RELOADED events to EventBus
  C7  — all methods return ``{"success": bool, "error": ...}``
  C11 — uses stdlib ``logging`` (matching codebase convention)
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.acl import AntiCorruptionLayer, acl
from core.nats_bus import NATSBus, nats_bus
from core.schemas.contracts import (
    AgentEventModel,
    EventDomain,
    EventSeverity,
    MCPToolDescriptorModel,
    MCPToolRegistrationModel,
    TimestampModel,
)

logger = logging.getLogger("mcp_gateway")

# Generated tools directory
_TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "generated_tools",
)


def _try_emit_event(event_type_name: str, data: dict) -> None:
    """Best-effort emit to EventBus.  Never raises."""
    try:
        from integration.event_bus import EventType, event_bus

        et = getattr(EventType, event_type_name, None)
        if et is not None:
            event_bus.publish_sync(et, "agentic_os", data)
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)


def _run_async_blocking(async_fn, *args, timeout: float = 60):
    """在同步函数里安全执行协程,兼容"当前线程正跑着事件循环"的情形。

    原来用 ``run_coroutine_threadsafe(coro, get_running_loop()).result()``:若本函数是
    在该 loop 的线程上被同步调用,``.result()`` 阻塞的正是 loop 线程自身 → loop 无法
    推进协程 → 自死锁。修复:无运行 loop 时 asyncio.run;已有运行 loop 时在独立线程
    用新 loop 执行,绝不阻塞当前 loop 线程。
    """
    import asyncio
    import threading

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args))

    box: dict = {}

    def _worker() -> None:
        try:
            box["result"] = asyncio.run(async_fn(*args))
        except Exception as _e:  # noqa: BLE001
            box["error"] = _e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if "error" in box:
        raise box["error"]
    return box.get("result")


class MCPDynamicGateway:
    """Enhanced MCP gateway with dynamic tool generation and hot-reload.

    Wraps the existing ``MCPLoader`` singleton — does NOT replace it.
    ``mcp_loader.call_tool()``, ``mcp_loader.list_tools()`` continue working.
    """

    _instance: Optional[MCPDynamicGateway] = None

    def __init__(
        self,
        nats: NATSBus | None = None,
        acl_layer: AntiCorruptionLayer | None = None,
    ) -> None:
        self._nats = nats or nats_bus
        self._acl = acl_layer or acl
        self._generated_tools: Dict[str, Dict[str, Any]] = {}

        # Ensure tools directory exists
        os.makedirs(_TOOLS_DIR, exist_ok=True)

    @classmethod
    def get_instance(cls) -> MCPDynamicGateway:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Self-Tool-Making ────────────────────────────────────────────────────

    async def handle_capability_gap(self, missing_tool: str, context: dict) -> dict:
        """Handle a missing tool report by generating, testing, and registering it.

        Returns ``{"success": True, "tool_name": ..., "server_id": ...}``
        or error dict.
        """
        logger.info(f"MCPGateway: handling capability gap for tool '{missing_tool}'")

        # Step 1: Generate tool code via LLM
        gen_result = await self._generate_tool_code(missing_tool, context)
        if not gen_result["success"]:
            return gen_result

        code = gen_result["code"]
        _try_emit_event(
            "MCP_TOOL_GENERATED",
            {
                "tool_name": missing_tool,
                "language": "python",
                "code_length": len(code),
            },
        )

        # Step 2: ACL validate the generated code
        acl_result = await self._acl.validate_mcp_registration(
            {
                "action": "register",
                "tool": {"name": missing_tool, "description": context.get("description", "")},
                "script_content": code,
                "script_language": "python",
                "generated_by": "mcp_gateway",
                "generation_prompt": json.dumps(context, default=str)[:500],
            }
        )
        if not acl_result["success"]:
            return acl_result

        # Step 3: Test in sandbox
        test_result = await self._test_tool(code)
        if not test_result["success"]:
            return {
                "success": False,
                "error": f"Generated tool failed sandbox test: {test_result.get('error', 'unknown')}",
                "test_result": test_result,
            }

        # Step 4: Save script and register via MCPLoader
        script_path = self._save_tool_script(missing_tool, code)
        register_result = await self._register_tool(missing_tool, script_path)
        if not register_result["success"]:
            return register_result

        # Step 5: Broadcast new capability via NATS
        await self._broadcast_tool_registration(missing_tool, register_result.get("server_id", ""))

        _try_emit_event(
            "MCP_TOOL_REGISTERED",
            {
                "tool_name": missing_tool,
                "server_id": register_result.get("server_id", ""),
                "script_path": str(script_path),
            },
        )

        return {
            "success": True,
            "tool_name": missing_tool,
            "server_id": register_result.get("server_id", ""),
            "script_path": str(script_path),
        }

    async def hot_reload_tool(self, registration: MCPToolRegistrationModel) -> dict:
        """Hot-reload a tool without restarting the gateway.

        Stops the existing MCP server, updates the script, restarts.
        """
        tool_name = registration.tool.name if registration.tool else ""
        if not tool_name:
            return {"success": False, "error": "No tool name in registration"}

        try:
            from core.mcp_loader import MCPLoader

            loader = MCPLoader.get_instance()

            # Find existing server
            server_id = registration.server_command or f"generated_{tool_name}"
            existing = loader.get_server(server_id)

            if existing:
                await loader.stop(server_id)
                logger.info(f"MCPGateway: stopped existing server {server_id} for hot-reload")

            # Save new script
            if registration.script_content:
                script_path = self._save_tool_script(tool_name, registration.script_content)
            else:
                return {"success": False, "error": "No script_content for hot-reload"}

            # Restart
            await loader.load(
                name=f"generated_{tool_name}",
                command=["python", str(script_path)],
                auto_start=True,
            )

            _try_emit_event("MCP_TOOL_RELOADED", {"tool_name": tool_name, "server_id": server_id})
            logger.info(f"MCPGateway: hot-reloaded tool '{tool_name}'")
            return {"success": True, "server_id": server_id}

        except Exception as exc:
            logger.error(f"MCPGateway: hot-reload failed for '{tool_name}' — {exc}")
            return {"success": False, "error": str(exc)}

    async def sync_tool_registry(self) -> dict:
        """Broadcast current tool manifest to all connected workers via NATS."""
        tools = await self.list_all_tools()
        if not tools:
            return {"success": True, "synced": 0}

        event = AgentEventModel(
            domain=EventDomain.MCP,
            event_type="tool_registry_sync",
            severity=EventSeverity.INFO,
            source="mcp_gateway",
            message=f"Tool registry sync: {len(tools)} tools",
            data_json=json.dumps([t.model_dump(mode="json") for t in tools], default=str),
            timestamp=TimestampModel.now(),
        )
        result = await self._nats.publish_event(event)
        logger.info(f"MCPGateway: synced {len(tools)} tools to workers")
        return {"success": True, "synced": len(tools), "nats_result": result}

    async def list_all_tools(self, filter_tags: list[str] | None = None) -> list[MCPToolDescriptorModel]:
        """List all available tools from MCPLoader + generated tools."""
        tools: list[MCPToolDescriptorModel] = []

        try:
            from core.mcp_loader import MCPLoader

            loader = MCPLoader.get_instance()
            servers = loader.list_servers()

            for srv in servers:
                server_id = srv.get("id", "")
                try:
                    server_tools = await loader.list_tools(server_id)
                    for t in server_tools:
                        descriptor = MCPToolDescriptorModel(
                            name=t.get("name", ""),
                            description=t.get("description", ""),
                            input_schema=json.dumps(t.get("inputSchema", {})),
                            server_id=server_id,
                            server_name=srv.get("name", ""),
                            tags=t.get("tags", []),
                        )
                        if filter_tags:
                            if any(any(fnmatch.fnmatch(tag, ft) for tag in descriptor.tags) for ft in filter_tags):
                                tools.append(descriptor)
                        else:
                            tools.append(descriptor)
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
        except ImportError:
            pass

        return tools

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _generate_tool_code(self, tool_name: str, context: dict) -> dict:
        """Use LLM to generate MCP server script."""
        try:
            from core.llm_manager import llm_manager

            prompt = (
                f"Generate a Python MCP server script (stdio JSON-RPC 2.0) that "
                f"implements a tool named '{tool_name}'.\n\n"
                f"Description: {context.get('description', tool_name)}\n"
                f"Expected input: {context.get('input_schema', 'any')}\n"
                f"Expected output: {context.get('output_schema', 'string')}\n\n"
                f"Requirements:\n"
                f"- Read JSON-RPC requests from stdin, write responses to stdout\n"
                f"- Implement initialize, tools/list, and tools/call methods\n"
                f"- Include proper error handling\n"
                f"- Output ONLY the Python code, no markdown fences"
            )

            response = await llm_manager.simple_chat(prompt)
            code = response.get("content", "") if isinstance(response, dict) else str(response)

            if not code.strip():
                return {"success": False, "error": "LLM returned empty response"}

            return {"success": True, "code": code.strip()}
        except Exception as exc:
            return {"success": False, "error": f"Tool generation failed: {exc}"}

    async def _test_tool(self, code: str) -> dict:
        """Test generated tool code in SafeExecutor sandbox."""
        try:
            from core.safe_executor import get_safe_executor

            executor = get_safe_executor()
            result = await executor.execute(code, language="python", timeout=10)
            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "error": result.error if not result.success else None,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _save_tool_script(self, tool_name: str, code: str) -> Path:
        """Save generated tool script to data/generated_tools/."""
        safe_name = tool_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        script_path = Path(_TOOLS_DIR) / f"{safe_name}.py"
        script_path.write_text(code, encoding="utf-8")
        logger.info(f"MCPGateway: saved tool script to {script_path}")
        return script_path

    async def _register_tool(self, tool_name: str, script_path: Path) -> dict:
        """Register generated tool via MCPLoader."""
        try:
            from core.mcp_loader import MCPLoader

            loader = MCPLoader.get_instance()
            result = await loader.load(
                name=f"generated_{tool_name}",
                command=["python", str(script_path)],
                auto_start=True,
            )

            if result.get("success"):
                self._generated_tools[tool_name] = {
                    "script_path": str(script_path),
                    "server_id": result.get("server_id", f"generated_{tool_name}"),
                    "registered_at": datetime.now().isoformat(),
                }
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _broadcast_tool_registration(self, tool_name: str, server_id: str) -> None:
        """Broadcast new tool capability via NATS."""
        event = AgentEventModel(
            domain=EventDomain.MCP,
            event_type="tool_registered",
            severity=EventSeverity.INFO,
            source="mcp_gateway",
            message=f"New tool available: {tool_name}",
            data_json=json.dumps({"tool_name": tool_name, "server_id": server_id}),
            timestamp=TimestampModel.now(),
        )
        await self._nats.publish_event(event)

    # ── External Tool Registration (GitHub Addons) ───────────────────────────

    def register_external_tool(
        self,
        name: str,
        command: list,
        manifest: Optional[dict] = None,
    ) -> dict:
        """Register an externally-sourced tool (e.g. from GitHub) into MCPLoader.

        Falls back gracefully if MCPLoader is unavailable.

        Args:
            name: Unique tool identifier.
            command: Command list to start the MCP server process.
            manifest: Optional tool manifest dict (for metadata).

        Returns:
            ``{"success": bool, "name": str, ...}``
        """
        try:
            from core.mcp_loader import mcp_loader

            async def _load():
                return await mcp_loader.load(name=name, command=command)

            # 用安全执行器,避免 run_coroutine_threadsafe(...).result() 在 loop 线程上
            # 自死锁(见 _run_async_blocking 说明)。
            result = _run_async_blocking(_load, timeout=60)

            if result.get("success"):
                self._generated_tools[name] = {
                    "name": name,
                    "command": command,
                    "source": "github",
                    "manifest": manifest or {},
                    "registered_at": datetime.now().isoformat(),
                }
                _try_emit_event(
                    "MCP_TOOL_REGISTERED",
                    {"tool_name": name, "source": "github", "command": command},
                )
                logger.info("External tool '%s' registered via MCPLoader", name)
                return {"success": True, "name": name, "via": "mcp_loader"}

            return {
                "success": False,
                "error": result.get("error", "MCPLoader.load returned failure"),
            }
        except Exception as exc:
            logger.warning("register_external_tool '%s' failed: %s", name, exc)
            return {"success": False, "error": str(exc)}

    async def execute_tool(self, tool_name: str, arguments: dict, *, allow_mesh: bool = True) -> dict:
        """Execute a named tool — 先本机,本机没有再问网格。

        Args:
            tool_name: Tool name as registered.
            arguments: Tool input arguments.
            allow_mesh: 本机找不到时,是否把调用发上 ``galaxy.mcp.calls`` 问网格。
                **从 NATS 收到的调用必须传 False** —— 见下面的环路说明。

        Returns:
            Tool result dict.
        """
        try:
            local = await self._execute_tool_locally(tool_name, arguments)
            if local is not None:
                return local
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        if allow_mesh:
            mesh = await self._execute_tool_on_mesh(tool_name, arguments)
            if mesh is not None:
                return mesh

        return {"success": False, "error": f"Tool '{tool_name}' not found in any MCP server"}

    async def _execute_tool_locally(self, tool_name: str, arguments: dict):
        """跑本进程 MCPLoader 里的工具。找不到返回 ``None``(区别于"跑了但失败")。"""
        from core.mcp_loader import mcp_loader

        for server in mcp_loader.list_servers():
            sid = server.get("id", "")
            tools = await mcp_loader.list_tools(sid)
            for tool in tools:
                if tool.get("name") == tool_name:
                    return await mcp_loader.call_tool(sid, tool_name, arguments)
        return None

    async def _execute_tool_on_mesh(self, tool_name: str, arguments: dict):
        """本机没有这个工具时,问网格上有没有别人有。找不到/总线不可用返回 ``None``。

        为什么必须防环
        --------------
        网格那一端也是一个 MCP 网关。如果它在处理一条**来自 NATS 的**调用时,
        发现本机也没有这个工具、又把调用重新发上 ``galaxy.mcp.calls``,这条消息
        就会在网关之间来回弹 —— 而且每弹一次都新占一个 request_id,谁也不会
        收敛。所以 :meth:`_on_nats_call` 一律用 ``allow_mesh=False`` 调本方法的
        上游,网格这条路**只从本机发起的调用进入一次**。

        已知限制(如实记下,不假装没有)
        --------------------------------
        所有网关共用 durable ``mcp-gateway-calls``,JetStream 会在它们之间分发,
        所以一条调用只会落到**其中一个**网关手上。要是恰好落到同样没有这个工具
        的那个,就返回 not_found,不会再转给第三个。真要"问遍全网格",得改成每个
        网关各带自己的 durable(广播)+ 调用方做去重,那是另一件事。
        """
        try:
            if not self._nats.is_usable():
                return None
            from core.mcp_call_client import get_mcp_call_client

            result = await get_mcp_call_client().call_tool(tool_name, arguments)
            if result.get("success"):
                return result.get("result")
            logger.debug("MCPGateway: 网格上也没跑成 %s — %s", tool_name, result.get("error"))
            return None
        except Exception as exc:  # pragma: no cover — 网格兜底失败不该盖掉本机结论
            logger.debug("MCPGateway: 问网格失败 %s — %s", tool_name, exc)
            return None

    # ── MCP over NATS:网关这一端 ────────────────────────────────────────────
    #
    # 契约在 contracts/proto/galaxy/v1/mcp.proto 与 docs/AGENTIC_OS_ARCHITECTURE.md
    # 里写得很清楚:
    #
    #   galaxy.mcp.calls    Brain → MCP Gateway  (MCPCallRequest)
    #   galaxy.mcp.results  MCP Gateway → Brain  (MCPCallResponse)
    #
    # 但两端从来没接上:``NATSBus.publish_mcp_call`` 有发布器**没有订阅方**,
    # ``NATSBus.subscribe_mcp_results`` 有订阅器**没有发布方**。两条主题各自
    # 断在半路,文档写的那个回路一次都没跑通过。
    #
    # 下面这两个方法把网关这一端补齐:订 calls、执行、把结果发回 results。
    # Brain 那一端在 core/mcp_call_client.py。

    async def start_nats_listener(self) -> dict:
        """订上 ``galaxy.mcp.calls``,开始接受来自 Brain 的工具调用。

        由启动序列调用。总线不可用时直接返回不成功 —— 不抛,MCP 的本地
        (进程内 MCPLoader)通路不受影响。
        """
        if not self._nats.is_usable():
            logger.debug("MCPGateway: 总线不可用,不订阅 galaxy.mcp.calls")
            return {"success": False, "error": "nats_unavailable"}
        try:
            await self._nats.subscribe(
                "galaxy.mcp.calls",
                self._on_nats_call,
                durable="mcp-gateway-calls",
            )
            logger.info("MCPGateway: 已订阅 galaxy.mcp.calls")
            return {"success": True}
        except Exception as exc:
            logger.error("MCPGateway: 订阅 galaxy.mcp.calls 失败 — %s", exc)
            return {"success": False, "error": str(exc)}

    async def _on_nats_call(self, data: dict) -> None:
        """处理一条 MCPCallRequest,把 MCPCallResponse 发回 ``galaxy.mcp.results``。

        **无论成败都要回一条**:调用方按 ``request_id`` 等在 future 上,不回就是
        让它一直等到超时。工具不存在、参数是坏 JSON、执行抛异常 —— 全部转成
        ``is_error=True`` 的响应发回去,而不是让请求悬着。
        """
        import time as _t

        started = _t.monotonic()
        request_id = str((data or {}).get("request_id") or "")
        tool_name = str((data or {}).get("tool_name") or "")
        try:
            raw_args = (data or {}).get("arguments_json") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            except (TypeError, ValueError) as exc:
                await self._publish_call_response(
                    request_id, error=f"arguments_json 不是合法 JSON: {exc}", started=started
                )
                return

            # allow_mesh=False 是**防环**的关键:这条调用本来就是从网格上收到的,
            # 本机没有就该老实回 not_found,绝不能再发上 galaxy.mcp.calls ——
            # 那会让消息在网关之间来回弹且永不收敛(见 _execute_tool_on_mesh)。
            result = await self.execute_tool(tool_name, arguments, allow_mesh=False)
            if isinstance(result, dict) and result.get("success") is False:
                await self._publish_call_response(
                    request_id, error=str(result.get("error") or "tool_failed"), started=started
                )
            else:
                await self._publish_call_response(request_id, result=result, started=started)
        except Exception as exc:  # pragma: no cover — 兜底:绝不能让请求悬着
            logger.error("MCPGateway: 处理 %s 调用失败 — %s", tool_name, exc)
            await self._publish_call_response(request_id, error=str(exc), started=started)

    async def _publish_call_response(
        self,
        request_id: str,
        *,
        result: Any = None,
        error: str = "",
        started: float = 0.0,
    ) -> None:
        import time as _t

        from core.schemas.contracts import MCPCallResponseModel

        duration_ms = int((_t.monotonic() - started) * 1000) if started else 0
        resp = MCPCallResponseModel(
            request_id=request_id,
            is_error=bool(error),
            result_json=json.dumps(result, default=str) if result is not None else "{}",
            duration_ms=duration_ms,
            completed_at=TimestampModel.now(),
            server_id="mcp_gateway",
        )
        if error:
            from core.schemas.contracts import ErrorInfoModel

            resp.error = ErrorInfoModel(code="MCP_CALL_FAILED", message=error[:500])
        try:
            await self._nats.publish_mcp_result(resp)
        except Exception as exc:  # pragma: no cover
            logger.error("MCPGateway: 回发 %s 的结果失败 — %s", request_id, exc)

    def list_github_tools(self) -> list:
        """Return tools registered via GitHub (source == 'github')."""
        return [v for v in self._generated_tools.values() if v.get("source") == "github"]

    # ── Status ──────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return gateway status."""
        return {
            "generated_tools": len(self._generated_tools),
            "tools_dir": _TOOLS_DIR,
            "nats_connected": self._nats.is_connected(),
            "timestamp": datetime.now().isoformat(),
        }


# ── Module-level singleton (constraint C1) ─────────────────────────────────
mcp_gateway = MCPDynamicGateway.get_instance()


def get_mcp_gateway() -> MCPDynamicGateway:
    """返回进程级 MCP 网关单例。

    修复:canonical_dispatcher / openclawd / github_installer 三处生产消费方都
    `from core.mcp_gateway import get_mcp_gateway`,但本模块从未定义该函数——
    ImportError 被各自的 try/except 吞掉,这三处的 MCP 网关能力(GitHub 工具注册/
    动态工具生成等)一直静默失效。补上这个既有单例的标准访问器。
    """
    return MCPDynamicGateway.get_instance()
