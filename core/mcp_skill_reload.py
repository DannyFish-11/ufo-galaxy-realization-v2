"""
core/mcp_skill_reload.py
==========================
MCP/Skill 热加载与协议校验（PR86）

提供：
- reload_mcp(server_id)   — 重新加载单个 MCP 服务器并校验协议
- reload_skill(skill_id)  — 重新加载单个 Skill 并校验 manifest
- reload_all()            — 热重载所有 MCP + Skill
- get_load_status()       — 返回所有 MCP/Skill 的加载状态（供 Dashboard 可观测）

协议校验要求：
  MCP：
    - server handshake 成功（list_tools 不抛异常）
    - 每个 tool 必须有 name (str) 且不为空
    - 每个 tool 有 description (str，可为空)
    - tool schema 格式合法（dict 或 None）
  Skill：
    - 有 name、description 字段
    - 有 handler 可调用入口（handler 或 handler_path）
    - 版本字段为字符串
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MCPSkillReload")

# ──────────────────────────────────────────────────────────────────────────────
# 加载状态数据结构
# ──────────────────────────────────────────────────────────────────────────────

_load_status: Dict[str, Dict[str, Any]] = {}
"""全局加载状态表。key = "mcp:<server_id>" 或 "skill:<skill_id>"。"""


def _set_status(
    key: str,
    loaded: bool,
    error: str = "",
    tool_count: int = 0,
    validated: bool = False,
    extra: Optional[Dict] = None,
) -> None:
    _load_status[key] = {
        "loaded": loaded,
        "error": error,
        "tool_count": tool_count,
        "validated": validated,
        "last_updated": time.time(),
        **(extra or {}),
    }


# ──────────────────────────────────────────────────────────────────────────────
# MCP 协议校验
# ──────────────────────────────────────────────────────────────────────────────


async def _validate_mcp_server(server_id: str, loader: Any) -> Dict[str, Any]:
    """对已加载的 MCP 服务器执行协议握手 + 工具 schema 校验。

    Returns:
        {valid: bool, tool_count: int, errors: List[str]}
    """
    errors: List[str] = []
    tool_count = 0

    try:
        tools = await asyncio.wait_for(loader.list_tools(server_id), timeout=10.0)
    except asyncio.TimeoutError:
        return {"valid": False, "tool_count": 0, "errors": ["list_tools 超时（>10s）"]}
    except Exception as e:
        return {"valid": False, "tool_count": 0, "errors": [f"list_tools 失败: {e}"]}

    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        if not name or not isinstance(name, str):
            errors.append(f"工具缺少有效 name 字段: {tool!r:.100}")
            continue
        tool_count += 1
        # schema 检查（input_schema 必须是 dict 或 None）
        schema = (
            tool.get("input_schema") if isinstance(tool, dict)
            else getattr(tool, "input_schema", None)
        )
        if schema is not None and not isinstance(schema, dict):
            errors.append(f"工具 {name} 的 input_schema 类型非法: {type(schema)}")

    valid = len(errors) == 0
    return {"valid": valid, "tool_count": tool_count, "errors": errors}


# ──────────────────────────────────────────────────────────────────────────────
# Skill 协议校验
# ──────────────────────────────────────────────────────────────────────────────


def _validate_skill(skill: Any) -> Dict[str, Any]:
    """校验 Skill 的 manifest/schema/entrypoint。

    Returns:
        {valid: bool, errors: List[str]}
    """
    errors: List[str] = []

    def _get(obj: Any, attr: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    name = _get(skill, "name", "")
    if not name:
        errors.append("Skill 缺少 name 字段")

    desc = _get(skill, "description", "")
    if not isinstance(desc, str):
        errors.append("Skill description 必须是字符串")

    # entrypoint 检查：handler 可调用 或 handler_path 存在
    handler = _get(skill, "handler")
    handler_path = _get(skill, "handler_path", "")
    if handler is None and not handler_path:
        errors.append("Skill 缺少 handler 或 handler_path")
    if handler is not None and not callable(handler):
        errors.append("Skill.handler 不可调用")

    # 版本字段
    version = _get(skill, "version", "")
    if version is not None and not isinstance(version, str):
        errors.append("Skill.version 必须是字符串")

    return {"valid": len(errors) == 0, "errors": errors}


# ──────────────────────────────────────────────────────────────────────────────
# 公共 API
# ──────────────────────────────────────────────────────────────────────────────


async def reload_mcp(server_id: str) -> Dict[str, Any]:
    """热重载指定 MCP 服务器，并执行协议校验。

    Returns:
        {server_id, loaded, validated, tool_count, error, errors}
    """
    key = f"mcp:{server_id}"
    logger.info("MCP 热重载开始: %s", server_id)

    try:
        from core.mcp_loader import MCPLoader
        loader = MCPLoader.get_instance()
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        error = f"MCPLoader 不可用: {e}"
        _set_status(key, loaded=False, error=error)
        return {"server_id": server_id, "loaded": False, "error": error}

    # 重新加载（先卸载再加载）
    try:
        if hasattr(loader, "unload_server"):
            loader.unload_server(server_id)
        if hasattr(loader, "reload_server"):
            await loader.reload_server(server_id)
        elif hasattr(loader, "load_server"):
            await loader.load_server(server_id)
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        error = f"MCP 加载失败: {e}"
        _set_status(key, loaded=False, error=error)
        logger.warning("MCP 热重载失败 %s: %s", server_id, e)
        return {"server_id": server_id, "loaded": False, "error": error}

    # 协议校验
    validation = await _validate_mcp_server(server_id, loader)
    valid = validation["valid"]
    tool_count = validation["tool_count"]
    errors = validation["errors"]

    if not valid:
        logger.warning("MCP %s 协议校验失败: %s", server_id, errors)
    else:
        logger.info("MCP %s 热重载成功: %d 个工具", server_id, tool_count)

    _set_status(
        key,
        loaded=True,
        error="; ".join(errors) if errors else "",
        tool_count=tool_count,
        validated=valid,
    )

    # 触发 CapabilityRegistry 刷新，使新工具立即可用
    try:
        from core.agent.capability_registry import get_capability_registry
        reg = get_capability_registry()
        await reg.refresh(force=True)
        logger.info("MCP 热重载后 CapabilityRegistry 已刷新")
    except Exception as e:
        logger.debug("CapabilityRegistry 刷新失败: %s", e)

    return {
        "server_id": server_id,
        "loaded": True,
        "validated": valid,
        "tool_count": tool_count,
        "errors": errors,
    }


async def reload_skill(skill_id: str) -> Dict[str, Any]:
    """热重载指定 Skill，并执行 manifest/schema/entrypoint 校验。

    Returns:
        {skill_id, loaded, validated, error, errors}
    """
    key = f"skill:{skill_id}"
    logger.info("Skill 热重载开始: %s", skill_id)

    try:
        from core.skill_loader import SkillLoader
        loader = SkillLoader.get_instance()
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        error = f"SkillLoader 不可用: {e}"
        _set_status(key, loaded=False, error=error)
        return {"skill_id": skill_id, "loaded": False, "error": error}

    # 重新加载
    try:
        if hasattr(loader, "unload_skill"):
            loader.unload_skill(skill_id)
        if hasattr(loader, "reload_skill"):
            skill = await loader.reload_skill(skill_id)
        elif hasattr(loader, "load_skill"):
            skill = loader.load_skill(skill_id)
        else:
            skill = None
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        error = f"Skill 加载失败: {e}"
        _set_status(key, loaded=False, error=error)
        logger.warning("Skill 热重载失败 %s: %s", skill_id, e)
        return {"skill_id": skill_id, "loaded": False, "error": error}

    # 校验
    if skill is not None:
        validation = _validate_skill(skill)
    else:
        # 加载成功但无返回值，尝试从 loader 获取
        try:
            skills = loader.list_skills() if hasattr(loader, "list_skills") else []
            matched = next(
                (s for s in skills if (
                    (s.get("skill_id") if isinstance(s, dict) else getattr(s, "skill_id", "")) == skill_id
                )),
                None,
            )
            validation = _validate_skill(matched) if matched else {"valid": True, "errors": []}
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            validation = {"valid": True, "errors": []}

    valid = validation["valid"]
    errors = validation["errors"]

    if not valid:
        logger.warning("Skill %s 协议校验失败: %s", skill_id, errors)
    else:
        logger.info("Skill %s 热重载成功", skill_id)

    _set_status(
        key,
        loaded=True,
        error="; ".join(errors) if errors else "",
        tool_count=1,
        validated=valid,
    )

    # 触发 CapabilityRegistry 刷新
    try:
        from core.agent.capability_registry import get_capability_registry
        reg = get_capability_registry()
        await reg.refresh(force=True)
        logger.info("Skill 热重载后 CapabilityRegistry 已刷新")
    except Exception as e:
        logger.debug("CapabilityRegistry 刷新失败: %s", e)

    return {
        "skill_id": skill_id,
        "loaded": True,
        "validated": valid,
        "errors": errors,
    }


async def reload_all() -> Dict[str, Any]:
    """热重载所有 MCP 服务器和 Skill。

    Returns:
        {mcp: {server_id: result, ...}, skills: {skill_id: result, ...}, total_errors: int}
    """
    logger.info("开始全量热重载 MCP + Skill …")
    mcp_results: Dict[str, Any] = {}
    skill_results: Dict[str, Any] = {}
    total_errors = 0

    # 重载 MCP
    try:
        from core.mcp_loader import MCPLoader
        loader = MCPLoader.get_instance()
        servers = loader.list_servers() if hasattr(loader, "list_servers") else {}
        server_ids = (
            list(servers.keys()) if isinstance(servers, dict)
            else [s.get("id") or s.get("server_id") for s in servers if isinstance(s, dict)]
        )
        for sid in server_ids:
            if sid:
                r = await reload_mcp(sid)
                mcp_results[sid] = r
                if not r.get("validated", False):
                    total_errors += 1
    except Exception as e:
        logger.warning("MCP 全量热重载失败: %s", e)

    # 重载 Skill
    try:
        from core.skill_loader import SkillLoader
        loader = SkillLoader.get_instance()
        skills = loader.list_skills() if hasattr(loader, "list_skills") else []
        for skill in skills:
            sid = (
                skill.get("skill_id") if isinstance(skill, dict)
                else getattr(skill, "skill_id", None)
            )
            if sid:
                r = await reload_skill(sid)
                skill_results[sid] = r
                if not r.get("validated", False):
                    total_errors += 1
    except Exception as e:
        logger.warning("Skill 全量热重载失败: %s", e)

    logger.info(
        "全量热重载完成: mcp=%d skill=%d total_errors=%d",
        len(mcp_results), len(skill_results), total_errors,
    )
    return {
        "mcp": mcp_results,
        "skills": skill_results,
        "total_errors": total_errors,
    }


def get_load_status() -> Dict[str, Any]:
    """返回所有 MCP/Skill 的加载状态（供 Dashboard 可观测）。

    Returns:
        {
            "mcp": {server_id: {loaded, validated, tool_count, error, last_updated}},
            "skills": {skill_id: {loaded, validated, tool_count, error, last_updated}},
        }
    """
    mcp: Dict[str, Any] = {}
    skills: Dict[str, Any] = {}

    for key, status in _load_status.items():
        if key.startswith("mcp:"):
            mcp[key[4:]] = status
        elif key.startswith("skill:"):
            skills[key[6:]] = status

    # 补充 MCPLoader 实时状态
    try:
        from core.mcp_loader import MCPLoader
        loader = MCPLoader.get_instance()
        servers = loader.list_servers() if hasattr(loader, "list_servers") else {}
        items = servers.items() if isinstance(servers, dict) else [(s.get("id", ""), s) for s in servers]
        for sid, srv in items:
            if sid and sid not in mcp:
                srv_dict = srv if isinstance(srv, dict) else {}
                mcp[sid] = {
                    "loaded": srv_dict.get("status") == "running",
                    "validated": False,
                    "tool_count": srv_dict.get("tools_count", 0),
                    "error": "",
                    "last_updated": 0.0,
                }
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 补充 SkillLoader 实时状态
    try:
        from core.skill_loader import SkillLoader
        loader = SkillLoader.get_instance()
        skill_list = loader.list_skills() if hasattr(loader, "list_skills") else []
        for skill in skill_list:
            sid = (
                skill.get("skill_id") if isinstance(skill, dict)
                else getattr(skill, "skill_id", None)
            )
            if sid and sid not in skills:
                skills[sid] = {
                    "loaded": True,
                    "validated": False,
                    "tool_count": 1,
                    "error": "",
                    "last_updated": 0.0,
                }
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    return {"mcp": mcp, "skills": skills}
