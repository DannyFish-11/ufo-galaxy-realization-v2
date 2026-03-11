"""
Galaxy - Protocol Routes (MCP / Skill)
==========================================

MCP 和 Skill 协议管理 API 路由。

Routes:
  GET    /api/v1/protocols/mcp                  - 列出所有 MCP 服务器
  POST   /api/v1/protocols/mcp/load             - 加载/启动 MCP 服务器
  DELETE /api/v1/protocols/mcp/{name}            - 卸载/停止 MCP 服务器
  GET    /api/v1/protocols/mcp/{name}/tools      - 列出 MCP 服务器工具
  POST   /api/v1/protocols/mcp/{name}/call       - 调用 MCP 工具
  POST   /api/v1/protocols/mcp/{name}/reload     - 热重载 MCP 服务器（带协议校验）
  GET    /api/v1/protocols/skills               - 列出所有技能
  POST   /api/v1/protocols/skills/load          - 加载技能
  POST   /api/v1/protocols/skills/{name}/execute - 执行技能
  DELETE /api/v1/protocols/skills/{name}         - 卸载技能
  POST   /api/v1/protocols/skills/{name}/reload  - 热重载 Skill（带 manifest/schema 校验）
  POST   /api/v1/protocols/reload-all            - 热重载所有 MCP + Skill
  GET    /api/v1/protocols/load-status           - 可观测加载状态（供 Dashboard 消费）
  GET    /api/v1/protocols/status               - 协议整体健康状态
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("Galaxy.API")


# ============================================================================
# Pydantic 请求模型
# ============================================================================

_ALLOWED_MCP_EXECUTABLES = {"node", "python", "python3", "npx", "uvx", "deno"}
_SHELL_METACHAR_RE = re.compile(r'[;|&`$(){}]')


class MCPLoadRequest(BaseModel):
    """加载 MCP 服务器的请求体"""
    name: str = Field(..., description="MCP 服务器名称")
    command: str = Field(..., description="启动命令，如 'node /path/to/server.js'")
    args: List[str] = Field(default_factory=list, description="命令行参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    cwd: str = Field(default="", description="工作目录")
    auto_start: bool = Field(default=True, description="是否自动启动")

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        parts = v.strip().split()
        if not parts:
            raise ValueError("Command cannot be empty")
        base = Path(parts[0]).name
        if base not in _ALLOWED_MCP_EXECUTABLES:
            raise ValueError(
                f"Executable '{base}' not in allowlist: {_ALLOWED_MCP_EXECUTABLES}"
            )
        if _SHELL_METACHAR_RE.search(v):
            raise ValueError("Command contains disallowed shell metacharacters")
        return v


class MCPToolCallRequest(BaseModel):
    """调用 MCP 工具的请求体"""
    tool_name: str = Field(..., description="工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="工具参数")


class SkillLoadRequest(BaseModel):
    """加载技能的请求体"""
    name: str = Field(default="", description="技能名称 (可选，从 skill.json 读取)")
    path: str = Field(default="", description="技能目录路径 (包含 skill.json)")
    config: Dict[str, Any] = Field(default_factory=dict, description="额外配置")


class SkillExecuteRequest(BaseModel):
    """执行技能的请求体"""
    input: Dict[str, Any] = Field(default_factory=dict, description="输入参数")
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")


# ============================================================================
# 路由工厂
# ============================================================================

def create_router(service_manager=None, config=None) -> APIRouter:
    """Create protocol management routes router."""
    router = APIRouter()

    # ========================================================================
    # MCP 端点
    # ========================================================================

    @router.get("/api/v1/protocols/mcp")
    async def list_mcp_servers():
        """列出所有 MCP 服务器及其状态"""
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            return JSONResponse({
                "success": True,
                "servers": servers,
                "total": len(servers),
            })

        except ImportError:
            logger.warning("MCP Loader 模块不可用")
            return JSONResponse({
                "success": False,
                "error": "MCP Loader 模块未安装",
                "servers": [],
                "total": 0,
            })
        except Exception as e:
            logger.error(f"列出 MCP 服务器失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.post("/api/v1/protocols/mcp/load")
    async def load_mcp_server(req: MCPLoadRequest):
        """加载并启动一个 MCP 服务器"""
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

            logger.info(f"MCP 服务器加载: {req.name} -> {result.get('server_id', 'N/A')}")
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "MCP Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"加载 MCP 服务器失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.delete("/api/v1/protocols/mcp/{name}")
    async def unload_mcp_server(name: str):
        """卸载/停止一个 MCP 服务器"""
        try:
            from core.mcp_loader import mcp_loader

            # 通过名称查找 server_id
            server_id = _find_mcp_server_id(name)
            if not server_id:
                return JSONResponse(
                    {"success": False, "error": f"MCP 服务器 '{name}' 不存在"},
                    status_code=404,
                )

            result = await mcp_loader.unload(server_id)
            logger.info(f"MCP 服务器卸载: {name} ({server_id})")
            return JSONResponse(result)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "MCP Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"卸载 MCP 服务器失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.get("/api/v1/protocols/mcp/{name}/tools")
    async def list_mcp_tools(name: str):
        """列出指定 MCP 服务器提供的工具"""
        try:
            from core.mcp_loader import mcp_loader

            server_id = _find_mcp_server_id(name)
            if not server_id:
                return JSONResponse(
                    {"success": False, "error": f"MCP 服务器 '{name}' 不存在", "tools": []},
                    status_code=404,
                )

            tools = await mcp_loader.list_tools(server_id)
            return JSONResponse({
                "success": True,
                "server_name": name,
                "server_id": server_id,
                "tools": tools,
                "total": len(tools),
            })

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "MCP Loader 模块未安装", "tools": []},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"列出 MCP 工具失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e), "tools": []},
                status_code=500,
            )

    @router.post("/api/v1/protocols/mcp/{name}/call")
    async def call_mcp_tool(name: str, req: MCPToolCallRequest):
        """调用指定 MCP 服务器上的工具"""
        try:
            from core.mcp_loader import mcp_loader

            server_id = _find_mcp_server_id(name)
            if not server_id:
                return JSONResponse(
                    {"success": False, "error": f"MCP 服务器 '{name}' 不存在"},
                    status_code=404,
                )

            result = await mcp_loader.call_tool(
                server_id=server_id,
                tool_name=req.tool_name,
                arguments=req.arguments,
            )

            logger.info(
                f"MCP 工具调用: {name}/{req.tool_name} -> "
                f"success={result.get('success', False)}"
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "MCP Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"MCP 工具调用失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    # ========================================================================
    # Skill 端点
    # ========================================================================

    @router.get("/api/v1/protocols/skills")
    async def list_skills():
        """列出所有已加载的技能"""
        try:
            from core.skill_loader import skill_loader

            skills = skill_loader.list_skills()
            stats = skill_loader.get_stats()
            return JSONResponse({
                "success": True,
                "skills": skills,
                "total": len(skills),
                "stats": stats,
            })

        except ImportError:
            logger.warning("Skill Loader 模块不可用")
            return JSONResponse({
                "success": False,
                "error": "Skill Loader 模块未安装",
                "skills": [],
                "total": 0,
            })
        except Exception as e:
            logger.error(f"列出技能失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.post("/api/v1/protocols/skills/load")
    async def load_skill(req: SkillLoadRequest):
        """加载一个技能"""
        try:
            from core.skill_loader import skill_loader

            if not req.path:
                return JSONResponse(
                    {"success": False, "error": "必须提供技能路径 (path)"},
                    status_code=400,
                )

            result = await skill_loader.load(
                path=req.path,
                skill_id=req.name if req.name else None,
            )

            logger.info(
                f"技能加载: {req.name or req.path} -> "
                f"success={result.get('success', False)}"
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "Skill Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"加载技能失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.post("/api/v1/protocols/skills/{name}/execute")
    async def execute_skill(name: str, req: SkillExecuteRequest):
        """执行指定技能"""
        try:
            from core.skill_loader import skill_loader

            # 查找技能 (按 ID 或名称)
            skill_id = _find_skill_id(name)
            if not skill_id:
                return JSONResponse(
                    {"success": False, "error": f"技能 '{name}' 不存在"},
                    status_code=404,
                )

            # 合并 input 和 context 作为执行参数
            exec_params = {**req.input}
            if req.context:
                exec_params["_context"] = req.context

            result = await skill_loader.execute(skill_id, **exec_params)

            logger.info(
                f"技能执行: {name} ({skill_id}) -> "
                f"success={result.get('success', False)}"
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "Skill Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"技能执行失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    @router.delete("/api/v1/protocols/skills/{name}")
    async def unload_skill(name: str):
        """卸载一个技能"""
        try:
            from core.skill_loader import skill_loader

            skill_id = _find_skill_id(name)
            if not skill_id:
                return JSONResponse(
                    {"success": False, "error": f"技能 '{name}' 不存在"},
                    status_code=404,
                )

            result = await skill_loader.unload(skill_id)
            logger.info(f"技能卸载: {name} ({skill_id})")
            return JSONResponse(result)

        except ImportError:
            return JSONResponse(
                {"success": False, "error": "Skill Loader 模块未安装"},
                status_code=501,
            )
        except Exception as e:
            logger.error(f"卸载技能失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)},
                status_code=500,
            )

    # ========================================================================
    # 热重载端点（PR88: MCP/Skill hot-reload + 协议校验）
    # ========================================================================

    @router.post("/api/v1/protocols/mcp/{name}/reload")
    async def reload_mcp_server(name: str):
        """热重载指定 MCP 服务器，执行协议握手 + 工具 schema 校验。

        返回：
          {server_id, loaded, validated, tool_count, errors, capability_stats}
        """
        server_id = _find_mcp_server_id(name) or name
        try:
            from core.mcp_skill_reload import reload_mcp
            result = await reload_mcp(server_id)
            logger.info(
                "MCP 热重载: %s -> loaded=%s validated=%s tool_count=%d",
                server_id, result.get("loaded"), result.get("validated"), result.get("tool_count", 0),
            )
            status_code = 200 if result.get("loaded") else 500
            return JSONResponse(result, status_code=status_code)
        except Exception as e:
            logger.error("MCP 热重载异常: %s: %s", name, e)
            return JSONResponse({"success": False, "server_id": server_id, "error": str(e)}, status_code=500)

    @router.post("/api/v1/protocols/skills/{name}/reload")
    async def reload_skill_handler(name: str):
        """热重载指定 Skill，执行 manifest/schema/entrypoint 校验。

        返回：
          {skill_id, loaded, validated, errors}
        """
        skill_id = _find_skill_id(name) or name
        try:
            from core.mcp_skill_reload import reload_skill
            result = await reload_skill(skill_id)
            logger.info(
                "Skill 热重载: %s -> loaded=%s validated=%s",
                skill_id, result.get("loaded"), result.get("validated"),
            )
            status_code = 200 if result.get("loaded") else 500
            return JSONResponse(result, status_code=status_code)
        except Exception as e:
            logger.error("Skill 热重载异常: %s: %s", name, e)
            return JSONResponse({"success": False, "skill_id": skill_id, "error": str(e)}, status_code=500)

    @router.post("/api/v1/protocols/reload-all")
    async def reload_all_handler():
        """热重载所有 MCP 服务器 + Skill，返回逐项状态。

        返回：
          {mcp: {server_id: {...}}, skills: {skill_id: {...}}, total_errors: int}
        """
        try:
            from core.mcp_skill_reload import reload_all
            result = await reload_all()
            logger.info(
                "全量热重载完成: mcp=%d skills=%d errors=%d",
                len(result.get("mcp", {})), len(result.get("skills", {})), result.get("total_errors", 0),
            )
            return JSONResponse({"success": True, **result})
        except Exception as e:
            logger.error("全量热重载异常: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @router.get("/api/v1/protocols/load-status")
    async def get_load_status():
        """可观测加载状态 — 供 Dashboard 消费。

        每个条目包含：
          loaded (bool), validated (bool), tool_count (int), error (str), last_updated (float)

        返回：
          {mcp: {server_id: {...}}, skills: {skill_id: {...}}}
        """
        try:
            from core.mcp_skill_reload import get_load_status
            status = get_load_status()
            return JSONResponse({"success": True, **status})
        except Exception as e:
            logger.error("获取加载状态异常: %s", e)
            return JSONResponse({"success": False, "error": str(e), "mcp": {}, "skills": {}}, status_code=500)

    # ========================================================================
    # 协议整体状态
    # ========================================================================

    @router.get("/api/v1/protocols/status")
    async def protocol_status():
        """协议整体健康状态 — 汇总 MCP 和 Skill 子系统"""
        status = {
            "success": True,
            "mcp": {"available": False, "servers": 0, "running": 0, "total_tools": 0},
            "skills": {"available": False, "loaded": 0, "stats": {}},
        }

        # MCP 状态
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            running = sum(1 for s in servers if s.get("status") == "running")
            total_tools = sum(s.get("tools_count", 0) for s in servers)
            status["mcp"] = {
                "available": True,
                "servers": len(servers),
                "running": running,
                "total_tools": total_tools,
                "server_names": [s.get("name", "") for s in servers],
            }
        except ImportError:
            status["mcp"]["error"] = "模块未安装"
        except Exception as e:
            status["mcp"]["error"] = str(e)

        # Skill 状态
        try:
            from core.skill_loader import skill_loader

            skills = skill_loader.list_skills()
            stats = skill_loader.get_stats()
            status["skills"] = {
                "available": True,
                "loaded": len(skills),
                "stats": stats,
                "skill_names": [s.get("name", "") for s in skills],
            }
        except ImportError:
            status["skills"]["error"] = "模块未安装"
        except Exception as e:
            status["skills"]["error"] = str(e)

        # 整体健康判断
        mcp_ok = status["mcp"].get("available", False)
        skills_ok = status["skills"].get("available", False)
        if mcp_ok or skills_ok:
            status["health"] = "healthy"
        else:
            status["health"] = "degraded"
            status["success"] = False

        return JSONResponse(status)

    return router


# ============================================================================
# 辅助函数
# ============================================================================

def _find_mcp_server_id(name: str) -> Optional[str]:
    """通过名称或 ID 查找 MCP 服务器，返回 server_id"""
    try:
        from core.mcp_loader import mcp_loader

        # 先尝试直接作为 server_id
        if mcp_loader.get_server(name):
            return name

        # 按名称搜索
        for server_id, server in mcp_loader.servers.items():
            if server.name == name:
                return server_id

    except Exception:
        pass
    return None


def _find_skill_id(name: str) -> Optional[str]:
    """通过名称或 ID 查找技能，返回 skill_id"""
    try:
        from core.skill_loader import skill_loader

        # 先尝试直接作为 skill_id
        if skill_loader.get_skill(name):
            return name

        # 按名称搜索
        for skill_id, skill in skill_loader.skills.items():
            if skill.name == name:
                return skill_id

    except Exception:
        pass
    return None
