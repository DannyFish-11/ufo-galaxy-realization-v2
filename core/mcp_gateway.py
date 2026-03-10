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
  C11 — loguru logger
"""

from __future__ import annotations

import fnmatch
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from core.acl import AntiCorruptionLayer, acl
from core.nats_bus import NATSBus, nats_bus
from core.schemas.contracts import (
    AgentEventModel,
    EventDomain,
    EventSeverity,
    MCPRegistrationAction,
    MCPToolDescriptorModel,
    MCPToolRegistrationModel,
    MCPToolRegistrationResultModel,
    TimestampModel,
)

# Generated tools directory
_TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "generated_tools",
)


def _try_emit_event(event_type_name: str, data: dict) -> None:
    """Best-effort emit to EventBus.  Never raises."""
    try:
        from integration.event_bus import EventBus, EventType

        bus = EventBus()
        et = getattr(EventType, event_type_name, None)
        if et is not None:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bus.emit(et, data))
    except Exception:
        pass


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

    async def handle_capability_gap(
        self, missing_tool: str, context: dict
    ) -> dict:
        """Handle a missing tool report by generating, testing, and registering it.

        Returns ``{"success": True, "tool_name": ..., "server_id": ...}``
        or error dict.
        """
        logger.info("MCPGateway: handling capability gap for tool '{}'", missing_tool)

        # Step 1: Generate tool code via LLM
        gen_result = await self._generate_tool_code(missing_tool, context)
        if not gen_result["success"]:
            return gen_result

        code = gen_result["code"]
        _try_emit_event("MCP_TOOL_GENERATED", {
            "tool_name": missing_tool,
            "language": "python",
            "code_length": len(code),
        })

        # Step 2: ACL validate the generated code
        acl_result = await self._acl.validate_mcp_registration({
            "action": "register",
            "tool": {"name": missing_tool, "description": context.get("description", "")},
            "script_content": code,
            "script_language": "python",
            "generated_by": "mcp_gateway",
            "generation_prompt": json.dumps(context, default=str)[:500],
        })
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

        _try_emit_event("MCP_TOOL_REGISTERED", {
            "tool_name": missing_tool,
            "server_id": register_result.get("server_id", ""),
            "script_path": str(script_path),
        })

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
                logger.info("MCPGateway: stopped existing server {} for hot-reload", server_id)

            # Save new script
            if registration.script_content:
                script_path = self._save_tool_script(tool_name, registration.script_content)
            else:
                return {"success": False, "error": "No script_content for hot-reload"}

            # Restart
            result = await loader.load(
                name=f"generated_{tool_name}",
                command=["python", str(script_path)],
                auto_start=True,
            )

            _try_emit_event("MCP_TOOL_RELOADED", {"tool_name": tool_name, "server_id": server_id})
            logger.info("MCPGateway: hot-reloaded tool '{}'", tool_name)
            return {"success": True, "server_id": server_id}

        except Exception as exc:
            logger.error("MCPGateway: hot-reload failed for '{}' — {}", tool_name, exc)
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
        logger.info("MCPGateway: synced {} tools to workers", len(tools))
        return {"success": True, "synced": len(tools), "nats_result": result}

    async def list_all_tools(
        self, filter_tags: list[str] | None = None
    ) -> list[MCPToolDescriptorModel]:
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
                            if any(
                                any(fnmatch.fnmatch(tag, ft) for tag in descriptor.tags)
                                for ft in filter_tags
                            ):
                                tools.append(descriptor)
                        else:
                            tools.append(descriptor)
                except Exception:
                    pass
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

            response = await llm_manager.chat(prompt)
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
        logger.info("MCPGateway: saved tool script to {}", script_path)
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

    async def _broadcast_tool_registration(
        self, tool_name: str, server_id: str
    ) -> None:
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
