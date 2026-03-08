"""
Galaxy - 加载器 API
======================

提供 MCP 和 Skill 的加载/卸载 API 端点

API 端点:
- POST /api/v1/mcp/load      - 加载 MCP 服务器
- POST /api/v1/mcp/unload    - 卸载 MCP 服务器
- GET  /api/v1/mcp/list      - 列出 MCP 服务器
- GET  /api/v1/mcp/{id}/tools - 列出 MCP 工具
- POST /api/v1/mcp/{id}/call - 调用 MCP 工具

- POST /api/v1/skill/load    - 加载技能
- POST /api/v1/skill/unload  - 卸载技能
- GET  /api/v1/skill/list    - 列出技能
- POST /api/v1/skill/{id}/execute - 执行技能
"""

import logging
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.LoaderAPI")

router = APIRouter()


# ============================================================================
# MCP API
# ============================================================================

class MCPLoadRequest(BaseModel):
    """MCP 加载请求"""
    name: str = Field(..., description="服务器名称 (用户自定义)")
    command: str = Field(..., description="启动命令")
    args: List[str] = Field(default=[], description="命令行参数")
    env: Dict[str, str] = Field(default={}, description="环境变量")
    cwd: str = Field(default="", description="工作目录")
    auto_start: bool = Field(default=True, description="是否自动启动")


class MCPUnloadRequest(BaseModel):
    """MCP 卸载请求"""
    server_id: str


class MCPCallRequest(BaseModel):
    """MCP 工具调用请求"""
    tool_name: str
    arguments: Dict[str, Any] = {}


@router.post("/api/v1/mcp/load")
async def mcp_load(req: MCPLoadRequest):
    """
    加载 MCP 服务器
    
    用户可以加载任何符合 MCP 标准的服务器
    
    示例:
    {
        "name": "filesystem",
        "command": "npx -y @modelcontextprotocol/server-filesystem /path/to/dir"
    }
    
    {
        "name": "my-server",
        "command": "node /path/to/my-mcp-server.js",
        "env": {"API_KEY": "xxx"}
    }
    """
    try:
        from core.mcp_loader import mcp_loader
        
        result = await mcp_loader.load(
            name=req.name,
            command=req.command,
            args=req.args,
            env=req.env,
            cwd=req.cwd,
            auto_start=req.auto_start,
        )
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"加载 MCP 服务器失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/v1/mcp/unload")
async def mcp_unload(req: MCPUnloadRequest):
    """卸载 MCP 服务器"""
    try:
        from core.mcp_loader import mcp_loader
        
        result = await mcp_loader.unload(req.server_id)
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"卸载 MCP 服务器失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/mcp/list")
async def mcp_list():
    """列出所有已加载的 MCP 服务器"""
    try:
        from core.mcp_loader import mcp_loader
        
        servers = mcp_loader.list_servers()
        
        return JSONResponse({
            "success": True,
            "servers": servers,
            "count": len(servers),
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/mcp/{server_id}")
async def mcp_get(server_id: str):
    """获取 MCP 服务器详情"""
    try:
        from core.mcp_loader import mcp_loader
        
        server = mcp_loader.get_server(server_id)
        
        if not server:
            return JSONResponse({"success": False, "error": "服务器不存在"}, status_code=404)
        
        return JSONResponse({
            "success": True,
            "server": server,
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/mcp/{server_id}/tools")
async def mcp_tools(server_id: str):
    """列出 MCP 服务器的工具"""
    try:
        from core.mcp_loader import mcp_loader
        
        tools = await mcp_loader.list_tools(server_id)
        
        return JSONResponse({
            "success": True,
            "server_id": server_id,
            "tools": tools,
            "count": len(tools),
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/v1/mcp/{server_id}/call")
async def mcp_call(server_id: str, req: MCPCallRequest):
    """调用 MCP 工具"""
    try:
        from core.mcp_loader import mcp_loader
        
        result = await mcp_loader.call_tool(
            server_id=server_id,
            tool_name=req.tool_name,
            arguments=req.arguments,
        )
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"调用 MCP 工具失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================================================
# Skill API
# ============================================================================

class SkillLoadRequest(BaseModel):
    """技能加载请求"""
    path: str = Field(..., description="技能路径 (包含 skill.json 的目录)")
    skill_id: Optional[str] = Field(default=None, description="自定义技能 ID")


class SkillUnloadRequest(BaseModel):
    """技能卸载请求"""
    skill_id: str


class SkillExecuteRequest(BaseModel):
    """技能执行请求"""
    params: Dict[str, Any] = {}


@router.post("/api/v1/skill/load")
async def skill_load(req: SkillLoadRequest):
    """
    加载技能
    
    用户可以加载任何技能目录
    
    示例:
    {
        "path": "/path/to/my-skill"
    }
    
    技能目录结构:
    my-skill/
    ├── skill.json      # 技能定义
    └── handler.py      # 处理函数
    
    skill.json 格式:
    {
        "id": "my-skill",
        "name": "我的技能",
        "description": "技能描述",
        "version": "1.0.0",
        "parameters": [
            {"name": "param1", "type": "string", "required": true}
        ],
        "handler_file": "handler.py",
        "handler_function": "execute"
    }
    """
    try:
        from core.skill_loader import skill_loader
        
        result = await skill_loader.load(
            path=req.path,
            skill_id=req.skill_id,
        )
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"加载技能失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/v1/skill/load-package")
async def skill_load_package(path: str):
    """
    加载技能包 (包含多个技能)
    
    示例:
    POST /api/v1/skill/load-package?path=/path/to/skills
    """
    try:
        from core.skill_loader import skill_loader
        
        result = await skill_loader.load_package(path)
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"加载技能包失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/v1/skill/unload")
async def skill_unload(req: SkillUnloadRequest):
    """卸载技能"""
    try:
        from core.skill_loader import skill_loader
        
        result = await skill_loader.unload(req.skill_id)
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"卸载技能失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/skill/list")
async def skill_list(tag: str = None):
    """列出所有已加载的技能"""
    try:
        from core.skill_loader import skill_loader
        
        skills = skill_loader.list_skills(tag=tag)
        
        return JSONResponse({
            "success": True,
            "skills": skills,
            "count": len(skills),
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/skill/{skill_id}")
async def skill_get(skill_id: str):
    """获取技能详情"""
    try:
        from core.skill_loader import skill_loader
        
        skill = skill_loader.get_skill(skill_id)
        
        if not skill:
            return JSONResponse({"success": False, "error": "技能不存在"}, status_code=404)
        
        return JSONResponse({
            "success": True,
            "skill": skill,
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/v1/skill/{skill_id}/execute")
async def skill_execute(skill_id: str, req: SkillExecuteRequest):
    """执行技能"""
    try:
        from core.skill_loader import skill_loader
        
        result = await skill_loader.execute(skill_id, **req.params)
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"执行技能失败: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/skill/search")
async def skill_search(query: str):
    """搜索技能"""
    try:
        from core.skill_loader import skill_loader
        
        results = skill_loader.search(query)
        
        return JSONResponse({
            "success": True,
            "query": query,
            "results": results,
            "count": len(results),
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/v1/skill/stats")
async def skill_stats():
    """获取技能统计"""
    try:
        from core.skill_loader import skill_loader
        
        stats = skill_loader.get_stats()
        
        return JSONResponse({
            "success": True,
            "stats": stats,
        })
        
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ============================================================================
# 导出
# ============================================================================

__all__ = ["router"]
