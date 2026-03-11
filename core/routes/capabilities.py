"""
Galaxy - Capability Management Routes
======================================

MCP/Skill 热加载与能力总线管理端点，供 Dashboard 和管理工具调用。

Routes:
  POST /api/v1/capabilities/reload             - 热加载全部 MCP/Skill（强制刷新注册表）
  POST /api/v1/capabilities/mcp/load           - 加载单个 MCP 服务器
  POST /api/v1/capabilities/mcp/{server_id}/reload  - 重载单个 MCP 服务器工具列表
  POST /api/v1/capabilities/mcp/{server_id}/unload  - 卸载 MCP 服务器
  GET  /api/v1/capabilities/mcp                - 列出所有 MCP 服务器
  POST /api/v1/capabilities/skill/load         - 加载技能（路径）
  POST /api/v1/capabilities/skill/{skill_id}/unload - 卸载技能
  GET  /api/v1/capabilities/skills             - 列出所有技能
  GET  /api/v1/capabilities/status             - Dashboard 可观测加载状态
  GET  /api/v1/capabilities/tools              - 列出全部已注册工具 schema
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.API.Capabilities")


# ──────────────────────────────────────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────────────────────────────────────


class MCPLoadRequest(BaseModel):
    name: str = Field(..., description="服务器名称（用户自定义）")
    command: str = Field(..., description="启动命令，如 'node /path/server.js'")
    args: List[str] = Field(default_factory=list, description="额外命令行参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    cwd: str = Field(default="", description="工作目录")


class SkillLoadRequest(BaseModel):
    path: str = Field(..., description="技能目录路径（含 skill.json）")
    skill_id: Optional[str] = Field(default=None, description="自定义 skill_id（可选）")


# ──────────────────────────────────────────────────────────────────────────────
# 路由工厂
# ──────────────────────────────────────────────────────────────────────────────


def create_router(service_manager=None, config=None) -> APIRouter:
    """创建能力管理路由。"""
    router = APIRouter()

    # ── 全局热加载 ──────────────────────────────────────────────────────

    @router.post("/api/v1/capabilities/reload")
    async def reload_all_capabilities():
        """
        强制重新加载全部 MCP 服务器工具列表和 Skill 技能，
        并刷新 CapabilityRegistry（含标准协议 schema 校验）。
        """
        from core.agent.capability_registry import CapabilityRegistry
        registry = CapabilityRegistry.get_instance()
        await registry.refresh(force=True)
        status = registry.get_load_status()
        return JSONResponse({
            "success": True,
            "message": "能力注册表已强制重载",
            "tool_count": status.get("tool_count", 0),
            "validated": status.get("validated", {}),
            "errors": status.get("errors", []),
            "by_source": status.get("by_source", {}),
        })

    # ── MCP 服务器管理 ──────────────────────────────────────────────────

    @router.post("/api/v1/capabilities/mcp/load")
    async def load_mcp_server(req: MCPLoadRequest):
        """加载（启动）一个新的 MCP 服务器并将其工具注入 CapabilityRegistry。"""
        from core.mcp_loader import MCPLoader
        from core.agent.capability_registry import CapabilityRegistry

        loader = MCPLoader.get_instance()
        result = await loader.load(
            name=req.name,
            command=req.command,
            args=req.args,
            env=req.env,
            cwd=req.cwd,
            auto_start=True,
        )
        if not result.get("success"):
            return JSONResponse({"success": False, "error": result.get("error", "加载失败")}, status_code=500)

        server_id = result["server_id"]

        # 校验工具 schema
        registry = CapabilityRegistry.get_instance()
        server_inst = loader.servers.get(server_id)
        validation_errors: List[str] = []
        if server_inst:
            for tool in server_inst.tools:
                ok, err = registry.validate_mcp_tool_schema({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                })
                if not ok:
                    validation_errors.append(f"tool {tool.name}: {err}")

        # 立即触发注册表刷新
        await registry.refresh(force=True)

        return JSONResponse({
            "success": True,
            "server_id": server_id,
            "name": req.name,
            "tool_count": len(server_inst.tools) if server_inst else 0,
            "validation_errors": validation_errors,
            "message": "MCP 服务器已加载",
        })

    @router.post("/api/v1/capabilities/mcp/{server_id}/reload")
    async def reload_mcp_server(server_id: str):
        """重载指定 MCP 服务器的工具列表（调用 tools/list 并刷新注册表）。"""
        from core.mcp_loader import MCPLoader
        from core.agent.capability_registry import CapabilityRegistry

        loader = MCPLoader.get_instance()
        if server_id not in loader.servers:
            return JSONResponse({"success": False, "error": "MCP 服务器不存在"}, status_code=404)

        # 重新拉取工具列表
        await loader.refresh_tools(server_id)

        server_inst = loader.servers[server_id]
        registry = CapabilityRegistry.get_instance()
        validation_errors: List[str] = []
        for tool in server_inst.tools:
            ok, err = registry.validate_mcp_tool_schema({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            })
            if not ok:
                validation_errors.append(f"tool {tool.name}: {err}")

        # 触发注册表刷新
        await registry.refresh(force=True)

        return JSONResponse({
            "success": True,
            "server_id": server_id,
            "tool_count": len(server_inst.tools),
            "validation_errors": validation_errors,
            "message": "MCP 服务器工具已重载",
        })

    @router.post("/api/v1/capabilities/mcp/{server_id}/unload")
    async def unload_mcp_server(server_id: str):
        """卸载 MCP 服务器并刷新注册表。"""
        from core.mcp_loader import MCPLoader
        from core.agent.capability_registry import CapabilityRegistry

        loader = MCPLoader.get_instance()
        result = await loader.unload(server_id)
        if not result.get("success"):
            return JSONResponse({"success": False, "error": result.get("error", "卸载失败")}, status_code=404)

        await CapabilityRegistry.get_instance().refresh(force=True)

        return JSONResponse({
            "success": True,
            "server_id": server_id,
            "message": "MCP 服务器已卸载",
        })

    @router.get("/api/v1/capabilities/mcp")
    async def list_mcp_servers():
        """列出所有已加载的 MCP 服务器及其工具数量。"""
        from core.mcp_loader import MCPLoader
        loader = MCPLoader.get_instance()
        servers = loader.list_servers()
        return JSONResponse({"servers": servers, "total": len(servers)})

    # ── Skill 管理 ──────────────────────────────────────────────────────

    @router.post("/api/v1/capabilities/skill/load")
    async def load_skill(req: SkillLoadRequest):
        """加载技能（从路径读取 skill.json），校验 manifest 并更新注册表。"""
        from core.skill_loader import SkillLoader
        from core.agent.capability_registry import CapabilityRegistry

        loader = SkillLoader.get_instance()
        result = await loader.load(req.path, skill_id=req.skill_id)
        if not result.get("success"):
            return JSONResponse({"success": False, "error": result.get("error", "加载失败")}, status_code=500)

        skill_id = result["skill_id"]

        # manifest 校验
        registry = CapabilityRegistry.get_instance()
        ok, err = registry.validate_skill_manifest({
            "id": skill_id,
            "name": result.get("name", ""),
            "description": result.get("description", ""),
        })
        validation_error = err if not ok else None

        # 立即触发注册表刷新
        await registry.refresh(force=True)

        return JSONResponse({
            "success": True,
            "skill_id": skill_id,
            "name": result.get("name", ""),
            "status": result.get("status", ""),
            "validation_error": validation_error,
            "message": "技能已加载",
        })

    @router.post("/api/v1/capabilities/skill/{skill_id}/unload")
    async def unload_skill(skill_id: str):
        """卸载技能并刷新注册表。"""
        from core.skill_loader import SkillLoader
        from core.agent.capability_registry import CapabilityRegistry

        loader = SkillLoader.get_instance()
        result = await loader.unload(skill_id)
        if not result.get("success"):
            return JSONResponse({"success": False, "error": result.get("error", "卸载失败")}, status_code=404)

        await CapabilityRegistry.get_instance().refresh(force=True)

        return JSONResponse({
            "success": True,
            "skill_id": skill_id,
            "message": "技能已卸载",
        })

    @router.get("/api/v1/capabilities/skills")
    async def list_skills():
        """列出所有已加载的技能。"""
        from core.skill_loader import SkillLoader
        loader = SkillLoader.get_instance()
        skills = loader.list_skills()
        return JSONResponse({"skills": skills, "total": len(skills)})

    # ── 观测与状态 ──────────────────────────────────────────────────────

    @router.get("/api/v1/capabilities/status")
    async def capability_status():
        """
        返回能力总线 Dashboard 可观测状态。

        字段说明:
          loaded      — 注册表是否已完成至少一次加载
          tool_count  — 当前注册的工具总数
          by_source   — 按来源（mcp/skill/gateway）分类的工具数
          validated   — 通过协议校验的工具数（mcp/skill 各自）
          errors      — 最近一次刷新中的校验/加载错误列表
          last_refresh_ts — 最近一次刷新的 monotonic 时间戳
        """
        from core.agent.capability_registry import CapabilityRegistry
        registry = CapabilityRegistry.get_instance()
        return JSONResponse(registry.get_load_status())

    @router.get("/api/v1/capabilities/tools")
    async def list_capability_tools(source: Optional[str] = None):
        """
        列出注册表中所有（或指定来源的）工具，含 OpenAI function calling 格式 schema。

        参数:
          source — 按来源过滤: mcp | skill | gateway（可选）
        """
        from core.agent.capability_registry import CapabilityRegistry
        registry = CapabilityRegistry.get_instance()
        items = registry.list_tools(source=source)
        tools = [
            {
                "name": item.name,
                "source": item.source,
                "source_id": item.source_id,
                "description": item.description,
                "schema": item.to_tool_schema(),
            }
            for item in items
        ]
        return JSONResponse({
            "tools": tools,
            "total": len(tools),
            "source_filter": source,
        })

    return router
