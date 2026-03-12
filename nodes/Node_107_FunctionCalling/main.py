"""
Node 107: FunctionCalling
==========================
A function-calling dispatcher. Maintains a registry of callable tools/functions,
accepts natural language or structured requests, uses OpenAI's function-calling
API to determine which tool to invoke, executes it, and returns the result.

Built-in tools: get_current_time, calculate, search_web (stub), get_node_status
External tools can be dynamically registered via POST /register_tool.
"""

import os
import json
import math
import logging
import httpx
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from nodes.common.cors_config import get_cors_origins
except Exception:
    def get_cors_origins():
        return ["*"]

try:
    from core.port_config import get_node_port
    _DEFAULT_PORT = get_node_port("Node_107_FunctionCalling")
except Exception:
    _DEFAULT_PORT = 8107

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NODE_ID = "107"
NODE_NAME = "FunctionCalling"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_start_time = datetime.now()

app = FastAPI(title=f"Node {NODE_ID} - {NODE_NAME}", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------

def _builtin_get_current_time(timezone: str = "UTC") -> Dict[str, Any]:
    now = datetime.utcnow()
    return {
        "utc": now.isoformat() + "Z",
        "timezone_requested": timezone,
        "note": "Full timezone conversion requires pytz; UTC returned.",
    }


def _builtin_calculate(expression: str) -> Dict[str, Any]:
    """Safe arithmetic evaluator using math module only."""
    allowed_names = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed_names["abs"] = abs
    allowed_names["round"] = round
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return {"expression": expression, "result": result}
    except Exception as exc:
        return {"expression": expression, "error": str(exc)}


def _builtin_search_web(query: str) -> Dict[str, Any]:
    """Stub: real web search would integrate a search API."""
    return {
        "query": query,
        "results": [],
        "note": "Web search stub — configure a search API integration to enable live results.",
    }


async def _builtin_get_node_status(node_url: str) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{node_url.rstrip('/')}/health")
            resp.raise_for_status()
            return {"url": node_url, "status": resp.json()}
    except Exception as exc:
        return {"url": node_url, "error": str(exc)}

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

class ToolDefinition:
    """Holds both the OpenAI function schema and the execution callable."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler=None,           # sync/async callable for built-ins
        handler_url: str = "",  # HTTP URL for external tools
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.handler_url = handler_url

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "type": "external_http" if self.handler_url else "builtin",
            "handler_url": self.handler_url or None,
        }


# Seed the registry with built-in tools
_tool_registry: Dict[str, ToolDefinition] = {
    "get_current_time": ToolDefinition(
        name="get_current_time",
        description="Get the current UTC date and time. Optionally specify a timezone name.",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone name, e.g. 'America/New_York'. Defaults to UTC."},
            },
            "required": [],
        },
        handler=_builtin_get_current_time,
    ),
    "calculate": ToolDefinition(
        name="calculate",
        description="Evaluate a safe arithmetic expression (supports Python math module functions like sqrt, sin, log, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Arithmetic expression to evaluate, e.g. 'sqrt(144) + 2**8'"},
            },
            "required": ["expression"],
        },
        handler=_builtin_calculate,
    ),
    "search_web": ToolDefinition(
        name="search_web",
        description="Search the web for a query and return relevant results (stub — configure a search API for live results).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["query"],
        },
        handler=_builtin_search_web,
    ),
    "get_node_status": ToolDefinition(
        name="get_node_status",
        description="Check the health/status of a Galaxy node by its base URL.",
        parameters={
            "type": "object",
            "properties": {
                "node_url": {"type": "string", "description": "Base URL of the Galaxy node, e.g. 'http://localhost:8090'"},
            },
            "required": ["node_url"],
        },
        handler=_builtin_get_node_status,
    ),
}

# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Any:
    tool = _tool_registry.get(tool_name)
    if tool is None:
        return {"error": f"Tool '{tool_name}' not found in registry."}

    if tool.handler_url:
        # External HTTP tool
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(tool.handler_url, json=arguments)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}

    if tool.handler is None:
        return {"error": "Tool has no handler configured."}

    import asyncio
    try:
        if asyncio.iscoroutinefunction(tool.handler):
            return await tool.handler(**arguments)
        else:
            return tool.handler(**arguments)
    except Exception as exc:
        return {"error": str(exc)}

# ---------------------------------------------------------------------------
# OpenAI function-calling
# ---------------------------------------------------------------------------

async def _openai_function_call(
    prompt: str,
    tools: List[ToolDefinition],
) -> Dict[str, Any]:
    """
    Send a prompt to OpenAI with function-calling tools.
    Returns {"tool_name": str, "arguments": dict} or {"content": str} for plain answers.
    """
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY not configured."}

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [t.to_openai_schema() for t in tools],
        "tool_choice": "auto",
    }
    async with httpx.AsyncClient(base_url=OPENAI_BASE_URL, timeout=60.0) as client:
        resp = await client.post("/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]

    message = choice["message"]
    tool_calls = message.get("tool_calls")

    if tool_calls:
        tc = tool_calls[0]
        return {
            "tool_name": tc["function"]["name"],
            "arguments": json.loads(tc["function"]["arguments"]),
        }
    return {"content": message.get("content", "")}

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CallRequest(BaseModel):
    prompt: str
    tools: Optional[List[str]] = None   # restrict to these tool names; None = all

class RegisterToolRequest(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    handler_url: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_107_FunctionCalling",
        "version": "1.0.0",
        "openai_configured": bool(OPENAI_API_KEY),
        "tools_count": len(_tool_registry),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "status": "running",
        "uptime_seconds": round(uptime, 1),
        "openai_configured": bool(OPENAI_API_KEY),
        "openai_model": OPENAI_MODEL,
        "tools": [t.to_info() for t in _tool_registry.values()],
    }


@app.get("/tools")
async def list_tools():
    """List all registered tools with their schemas."""
    return {
        "success": True,
        "count": len(_tool_registry),
        "tools": [t.to_info() for t in _tool_registry.values()],
    }


@app.delete("/tools/{tool_name}")
async def deregister_tool(tool_name: str):
    """Deregister a tool from the registry."""
    if tool_name not in _tool_registry:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
    del _tool_registry[tool_name]
    return {"success": True, "removed": tool_name, "remaining": len(_tool_registry)}


@app.post("/register_tool")
async def register_tool(req: RegisterToolRequest):
    """Register an external HTTP tool."""
    _tool_registry[req.name] = ToolDefinition(
        name=req.name,
        description=req.description,
        parameters=req.parameters,
        handler_url=req.handler_url,
    )
    logger.info(f"Tool registered: {req.name} → {req.handler_url}")
    return {
        "success": True,
        "registered": req.name,
        "total_tools": len(_tool_registry),
    }


@app.post("/call")
async def call(req: CallRequest):
    """
    Accept a natural language prompt, use OpenAI function-calling to select
    and execute the appropriate tool, and return the result.
    """
    # Determine which tools to expose to OpenAI
    if req.tools is not None:
        active_tools = [_tool_registry[n] for n in req.tools if n in _tool_registry]
        unknown = [n for n in req.tools if n not in _tool_registry]
    else:
        active_tools = list(_tool_registry.values())
        unknown = []

    if not active_tools:
        raise HTTPException(status_code=400, detail="No valid tools available for this request.")

    decision = await _openai_function_call(req.prompt, active_tools)

    if "error" in decision:
        raise HTTPException(status_code=503, detail=decision["error"])

    # Plain text answer — no tool was invoked
    if "content" in decision:
        return {
            "success": True,
            "tool_called": None,
            "arguments": None,
            "result": decision["content"],
            "unknown_tools_requested": unknown,
        }

    tool_name = decision["tool_name"]
    arguments = decision["arguments"]
    result = await _execute_tool(tool_name, arguments)

    return {
        "success": True,
        "tool_called": tool_name,
        "arguments": arguments,
        "result": result,
        "unknown_tools_requested": unknown,
    }


@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "call":
        return await call(CallRequest(**params))
    elif tool == "register_tool":
        return await register_tool(RegisterToolRequest(**params))
    elif tool == "list_tools":
        return await list_tools()
    elif tool == "health":
        return await health()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_107_PORT", str(_DEFAULT_PORT)))
    logger.info(f"Starting {NODE_NAME} on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
