"""
Galaxy - 标准 Skill 加载器
==============================

支持动态加载任何技能
用户可以自己下载技能包，然后装载到系统

使用方法:
    from core.skill_loader import skill_loader
    
    # 加载技能 (用户自己下载的)
    await skill_loader.load("/path/to/skill")
    
    # 加载技能包 (包含多个技能)
    await skill_loader.load_package("/path/to/skills")
    
    # 列出已加载的技能
    skills = skill_loader.list_skills()
    
    # 执行技能
    result = await skill_loader.execute("skill_id", param=value)
    
    # 卸载技能
    await skill_loader.unload("skill_id")
"""

import asyncio
import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from pathlib import Path
from enum import Enum
import uuid

logger = logging.getLogger("Galaxy.Skill")


# ============================================================================
# 技能定义
# ============================================================================

class SkillStatus(str, Enum):
    """技能状态"""
    LOADED = "loaded"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class SkillParameter:
    """技能参数"""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SkillParameter":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", True),
            default=data.get("default"),
        )


@dataclass
class SkillInstance:
    """技能实例"""
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: List[SkillParameter] = field(default_factory=list)
    
    # 处理函数
    handler: Optional[Callable] = None
    handler_path: str = ""
    
    # 状态
    status: SkillStatus = SkillStatus.LOADED
    error: Optional[str] = None
    
    # 元数据
    source_path: str = ""
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.parameters
            ],
            "status": self.status.value,
            "error": self.error,
            "source_path": self.source_path,
            "created_at": self.created_at,
        }


# ============================================================================
# Skill 加载器
# ============================================================================

class SkillLoader:
    """
    标准 Skill 加载器
    
    支持动态加载任何技能
    用户可以自己下载技能包，然后装载到系统
    """
    
    _instance = None
    
    def __init__(self):
        self.skills: Dict[str, SkillInstance] = {}
        
        # 统计
        self.stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
        }
        
        logger.info("Skill 加载器初始化")
    
    @classmethod
    def get_instance(cls) -> "SkillLoader":
        if cls._instance is None:
            cls._instance = SkillLoader()
        return cls._instance

    # ========================================================================
    # 能力总线刷新（最佳努力）
    # ========================================================================

    async def _refresh_capability_registry(self, skill_id: str, event: str) -> None:
        """Skill 加载/卸载事件后，最佳努力刷新 CapabilityRegistry 并广播事件。

        Args:
            skill_id: Skill ID（仅用于日志）。
            event: 触发场景描述，如 "load" 或 "unload"。
        """
        # 刷新能力总线
        try:
            from core.agent.capability_registry import get_capability_registry
            reg = get_capability_registry()
            await reg.refresh(force=True)
            logger.info("CapabilityRegistry 已刷新（Skill %s: %s）", skill_id, event)
        except Exception as exc:
            logger.debug("CapabilityRegistry 刷新失败（不影响运行）: %s", exc)

        # 广播能力更新事件（最佳努力，事件总线不可用时静默降级）
        try:
            from integration.event_bus import event_bus, EventType
            event_bus.publish_sync(
                EventType.CAPABILITY_UPDATED,
                "skill_loader",
                {"skill_id": skill_id, "event": event},
            )
        except Exception:
            pass
    
    # ========================================================================
    # 加载/卸载
    # ========================================================================
    
    async def load(
        self,
        path: str,
        skill_id: str = None,
    ) -> Dict[str, Any]:
        """
        加载技能
        
        Args:
            path: 技能路径 (包含 skill.json 的目录)
            skill_id: 自定义技能 ID (可选)
        
        Returns:
            加载结果
        """
        skill_path = Path(path)
        
        # 检查路径
        if not skill_path.exists():
            return {"success": False, "error": f"路径不存在: {path}"}
        
        # 查找 skill.json
        if skill_path.is_file() and skill_path.name == "skill.json":
            skill_file = skill_path
            skill_dir = skill_path.parent
        elif skill_path.is_dir():
            skill_file = skill_path / "skill.json"
            skill_dir = skill_path
        else:
            return {"success": False, "error": f"无效的技能路径: {path}"}
        
        if not skill_file.exists():
            return {"success": False, "error": f"找不到 skill.json: {skill_file}"}
        
        try:
            # 读取技能定义
            with open(skill_file, encoding="utf-8") as f:
                skill_def = json.load(f)
            
            # 生成 ID
            if not skill_id:
                skill_id = skill_def.get("id", str(uuid.uuid4())[:8])
            
            # 解析参数
            parameters = []
            for p in skill_def.get("parameters", []):
                parameters.append(SkillParameter.from_dict(p))
            
            # 加载处理函数
            handler = None
            handler_file = skill_def.get("handler_file", "")
            if handler_file:
                handler_path = skill_dir / handler_file
                if handler_path.exists():
                    handler = await self._load_handler(
                        handler_path,
                        skill_def.get("handler_function", "execute"),
                        skill_id,
                    )
            
            # 创建技能实例
            skill = SkillInstance(
                id=skill_id,
                name=skill_def.get("name", skill_dir.name),
                description=skill_def.get("description", ""),
                version=skill_def.get("version", "1.0.0"),
                author=skill_def.get("author", ""),
                tags=skill_def.get("tags", []),
                parameters=parameters,
                handler=handler,
                handler_path=str(handler_path) if handler_file else "",
                source_path=str(skill_dir),
                metadata=skill_def.get("metadata", {}),
            )
            
            if not handler:
                skill.status = SkillStatus.ERROR
                skill.error = "未找到处理函数"
            
            self.skills[skill_id] = skill
            
            logger.info(f"加载技能: {skill.name} ({skill_id})")

            # 加载成功后自动注入能力总线（仅 LOADED 状态注入）
            if skill.status == SkillStatus.LOADED:
                self._inject_skill_to_registry(skill_id)
                # 最佳努力刷新 CapabilityRegistry 并广播事件（fire-and-forget）
                try:
                    asyncio.ensure_future(
                        self._refresh_capability_registry(skill_id, "load")
                    )
                except Exception:
                    pass
            else:
                logger.warning(
                    "技能 %s (%s) 状态为 ERROR（%s），跳过注入能力总线",
                    skill.name, skill_id, skill.error,
                )
            
            return {
                "success": True,
                "skill_id": skill_id,
                "name": skill.name,
                "description": skill.description,
                "status": skill.status.value,
            }
            
        except Exception as e:
            logger.error(f"加载技能失败: {path} - {e}")
            return {"success": False, "error": str(e)}
    
    async def load_package(
        self,
        path: str,
    ) -> Dict[str, Any]:
        """
        加载技能包 (包含多个技能)
        
        Args:
            path: 技能包路径
        
        Returns:
            加载结果
        """
        package_path = Path(path)
        
        if not package_path.exists():
            return {"success": False, "error": f"路径不存在: {path}"}
        
        results = []
        
        # 查找所有 skill.json
        for skill_file in package_path.rglob("skill.json"):
            result = await self.load(str(skill_file.parent))
            results.append(result)
        
        success_count = sum(1 for r in results if r.get("success"))
        
        return {
            "success": success_count > 0,
            "total": len(results),
            "loaded": success_count,
            "results": results,
        }
    
    async def unload(self, skill_id: str) -> Dict[str, Any]:
        """
        卸载技能
        
        Args:
            skill_id: 技能 ID
        
        Returns:
            卸载结果
        """
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}
        
        skill = self.skills.pop(skill_id)

        # 从能力总线移除
        try:
            from core.agent.capability_registry import CapabilityRegistry
            CapabilityRegistry.get_instance().eject(f"skill__{skill_id}")
        except Exception as exc:
            logger.debug("Skill 从能力总线移除失败: %s", exc)
        
        logger.info(f"卸载技能: {skill.name} ({skill_id})")

        # 最佳努力刷新 CapabilityRegistry 并广播事件（fire-and-forget）
        try:
            asyncio.ensure_future(
                self._refresh_capability_registry(skill_id, "unload")
            )
        except Exception:
            pass
        
        return {
            "success": True,
            "skill_id": skill_id,
            "name": skill.name,
        }

    def _inject_skill_to_registry(self, skill_id: str) -> None:
        """将 Skill 注入能力总线（在加载成功后调用）。"""
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            mcp_schema = self.to_mcp_tool_schema(skill_id)
            params = mcp_schema.get("inputSchema", {}) if mcp_schema else {}
            skill = self.skills.get(skill_id)
            if not skill:
                return
            reg.inject_skill(
                skill_id=skill_id,
                skill_name=skill.name,
                description=skill.description,
                parameters=params,
            )
            logger.info("Skill %s (%s) 已注入能力总线", skill.name, skill_id)
        except Exception as exc:
            logger.debug("Skill 注入能力总线失败（不影响正常运行）: %s", exc)
    
    async def _load_handler(
        self,
        handler_path: Path,
        function_name: str,
        skill_id: str,
    ) -> Optional[Callable]:
        """加载处理函数"""
        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_{skill_id}",
                handler_path,
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"skill_{skill_id}"] = module
            spec.loader.exec_module(module)
            
            return getattr(module, function_name, None)
        except Exception as e:
            logger.error(f"加载处理函数失败: {handler_path} - {e}")
            return None
    
    # ========================================================================
    # 执行
    # ========================================================================
    
    async def execute(
        self,
        skill_id: str,
        **params,
    ) -> Dict[str, Any]:
        """
        执行技能
        
        Args:
            skill_id: 技能 ID
            **params: 参数
        
        Returns:
            执行结果
        """
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}
        
        skill = self.skills[skill_id]
        
        if skill.status == SkillStatus.DISABLED:
            return {"success": False, "error": "技能已禁用"}
        
        if not skill.handler:
            return {"success": False, "error": "技能没有处理函数"}
        
        self.stats["total_executions"] += 1
        
        try:
            # 验证参数
            for param in skill.parameters:
                if param.required and param.name not in params:
                    self.stats["failed_executions"] += 1
                    return {"success": False, "error": f"缺少必需参数: {param.name}"}
            
            # 执行
            if asyncio.iscoroutinefunction(skill.handler):
                result = await skill.handler(**params)
            else:
                result = skill.handler(**params)
            
            self.stats["successful_executions"] += 1
            
            return {"success": True, "result": result}
            
        except Exception as e:
            self.stats["failed_executions"] += 1
            logger.error(f"执行技能失败: {skill_id} - {e}")
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 查询
    # ========================================================================
    
    def list_skills(
        self,
        tag: str = None,
        status: SkillStatus = None,
    ) -> List[Dict]:
        """列出技能"""
        skills = list(self.skills.values())
        
        if tag:
            skills = [s for s in skills if tag in s.tags]
        if status:
            skills = [s for s in skills if s.status == status]
        
        return [s.to_dict() for s in skills]
    
    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取技能详情"""
        if skill_id in self.skills:
            return self.skills[skill_id].to_dict()
        return None
    
    def search(self, query: str) -> List[Dict]:
        """搜索技能"""
        query = query.lower()
        results = []
        
        for skill in self.skills.values():
            if (query in skill.name.lower() or
                query in skill.description.lower() or
                any(query in tag.lower() for tag in skill.tags)):
                results.append(skill.to_dict())
        
        return results
    
    def enable(self, skill_id: str) -> bool:
        """启用技能"""
        if skill_id in self.skills:
            self.skills[skill_id].status = SkillStatus.LOADED
            return True
        return False
    
    def disable(self, skill_id: str) -> bool:
        """禁用技能"""
        if skill_id in self.skills:
            self.skills[skill_id].status = SkillStatus.DISABLED
            return True
        return False
    
    def get_stats(self) -> Dict:
        """获取统计"""
        return {
            **self.stats,
            "loaded_skills": len(self.skills),
        }

    # ========================================================================
    # MCP Tool 桥接 — 将 Skill 暴露为 MCP 标准工具
    # ========================================================================

    def to_mcp_tool_schema(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """
        将 Skill 转换为 MCP 标准工具定义。

        生成符合 MCP 规范的 ``inputSchema`` (JSON Schema)，使外部 MCP
        客户端（如 Claude Desktop）可以通过标准 MCP 协议发现和调用
        Galaxy Skill。

        Args:
            skill_id: 技能 ID

        Returns:
            MCP 工具定义字典（包含 name, description, inputSchema），
            或 None（技能不存在）。
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return None

        # 构建 JSON Schema properties
        properties: Dict[str, Any] = {}
        required: List[str] = []

        type_map = {
            "string": "string",
            "str": "string",
            "int": "integer",
            "integer": "integer",
            "float": "number",
            "number": "number",
            "bool": "boolean",
            "boolean": "boolean",
            "list": "array",
            "array": "array",
            "dict": "object",
            "object": "object",
        }

        for param in skill.parameters:
            json_type = type_map.get(param.type.lower(), "string")
            prop: Dict[str, Any] = {
                "type": json_type,
                "description": param.description or param.name,
            }
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        input_schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            input_schema["required"] = required

        return {
            "name": f"galaxy_skill_{skill_id}",
            "description": f"[Galaxy Skill] {skill.description or skill.name}",
            "inputSchema": input_schema,
        }

    def list_as_mcp_tools(self) -> List[Dict[str, Any]]:
        """
        将所有已加载的 Skill 导出为 MCP 标准工具列表。

        Returns:
            MCP 工具定义列表（用于 tools/list 响应）。
        """
        tools = []
        for skill_id, skill in self.skills.items():
            if skill.status != SkillStatus.LOADED:
                continue
            schema = self.to_mcp_tool_schema(skill_id)
            if schema:
                tools.append(schema)
        return tools


# ============================================================================
# 全局实例
# ============================================================================

skill_loader = SkillLoader.get_instance()
