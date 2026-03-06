"""
UFO Galaxy - Skill 系统
=======================

通用的技能管理系统

功能：
1. 动态加载技能
2. 技能注册和发现
3. 技能执行和组合
4. 从 GitHub 加载技能包

技能定义：
- 一个技能是一个可执行的操作单元
- 技能可以组合成更复杂的工作流
- 技能可以从外部动态加载

使用方法：
    from core.skill_manager import skill_manager
    
    # 注册技能
    skill_manager.register_skill("web_search", "搜索网页", handler)
    
    # 执行技能
    result = await skill_manager.execute("web_search", query="Python")
    
    # 加载技能包
    await skill_manager.load_skill_package("https://github.com/user/skills")
"""

import asyncio
import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Union
from pathlib import Path
from enum import Enum
import subprocess

logger = logging.getLogger("UFO-Galaxy.Skill")


# ============================================================================
# 数据模型
# ============================================================================

class SkillStatus(str, Enum):
    """技能状态"""
    DISABLED = "disabled"
    ENABLED = "enabled"
    ERROR = "error"


class SkillType(str, Enum):
    """技能类型"""
    ACTION = "action"          # 单一动作
    WORKFLOW = "workflow"      # 工作流（多个动作组合）
    CONDITIONAL = "conditional"  # 条件执行
    LOOP = "loop"              # 循环执行


@dataclass
class SkillParameter:
    """技能参数"""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    options: List[str] = field(default_factory=list)


@dataclass
class Skill:
    """技能定义"""
    id: str
    name: str
    description: str
    type: SkillType = SkillType.ACTION
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: List[SkillParameter] = field(default_factory=list)
    handler: Optional[Callable] = None
    workflow: List[Dict] = field(default_factory=list)  # 工作流步骤
    status: SkillStatus = SkillStatus.ENABLED
    error: Optional[str] = None
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
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
                    "options": p.options,
                }
                for p in self.parameters
            ],
            "status": self.status.value,
            "workflow": self.workflow,
            "metadata": self.metadata,
        }


@dataclass
class SkillExecution:
    """技能执行记录"""
    execution_id: str
    skill_id: str
    params: Dict[str, Any]
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    started_at: float = field(default_factory=lambda: datetime.now().timestamp())
    completed_at: Optional[float] = None
    steps: List[Dict] = field(default_factory=list)


# ============================================================================
# Skill 管理器
# ============================================================================

class SkillManager:
    """
    Skill 管理器
    
    统一管理所有技能
    """
    
    _instance = None
    
    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.executions: Dict[str, SkillExecution] = {}
        self._skill_packages: Dict[str, str] = {}  # 包名 -> 路径
        
        # 配置
        self.config_path = Path("config/skills.json")
        self.skills_dir = Path("skills")
        
        # 统计
        self.stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
        }
        
        logger.info("Skill 管理器初始化")
    
    @classmethod
    def get_instance(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ========================================================================
    # 技能注册
    # ========================================================================
    
    def register_skill(
        self,
        id: str,
        name: str,
        description: str,
        handler: Callable = None,
        type: SkillType = SkillType.ACTION,
        parameters: List[Dict] = None,
        workflow: List[Dict] = None,
        tags: List[str] = None,
        version: str = "1.0.0",
        author: str = "",
        metadata: Dict = None,
    ) -> Skill:
        """
        注册技能
        
        Args:
            id: 技能 ID
            name: 技能名称
            description: 描述
            handler: 处理函数
            type: 技能类型
            parameters: 参数定义
            workflow: 工作流步骤
            tags: 标签
            version: 版本
            author: 作者
            metadata: 元数据
        
        Returns:
            技能对象
        """
        params = []
        if parameters:
            for p in parameters:
                params.append(SkillParameter(
                    name=p.get("name", ""),
                    type=p.get("type", "string"),
                    description=p.get("description", ""),
                    required=p.get("required", True),
                    default=p.get("default"),
                    options=p.get("options", []),
                ))
        
        skill = Skill(
            id=id,
            name=name,
            description=description,
            type=type,
            version=version,
            author=author,
            tags=tags or [],
            parameters=params,
            handler=handler,
            workflow=workflow or [],
            metadata=metadata or {},
        )
        
        self.skills[id] = skill
        logger.info(f"注册技能: {id} ({type.value})")
        
        return skill
    
    def unregister_skill(self, id: str) -> bool:
        """注销技能"""
        if id in self.skills:
            del self.skills[id]
            logger.info(f"注销技能: {id}")
            return True
        return False
    
    def enable_skill(self, id: str) -> bool:
        """启用技能"""
        if id in self.skills:
            self.skills[id].status = SkillStatus.ENABLED
            return True
        return False
    
    def disable_skill(self, id: str) -> bool:
        """禁用技能"""
        if id in self.skills:
            self.skills[id].status = SkillStatus.DISABLED
            return True
        return False
    
    # ========================================================================
    # 技能执行
    # ========================================================================
    
    async def execute(
        self,
        skill_id: str,
        **params,
    ) -> Any:
        """
        执行技能
        
        Args:
            skill_id: 技能 ID
            **params: 参数
        
        Returns:
            执行结果
        """
        import uuid
        
        skill = self.skills.get(skill_id)
        if not skill:
            raise ValueError(f"技能不存在: {skill_id}")
        
        if skill.status == SkillStatus.DISABLED:
            raise RuntimeError(f"技能已禁用: {skill_id}")
        
        execution = SkillExecution(
            execution_id=str(uuid.uuid4())[:8],
            skill_id=skill_id,
            params=params,
        )
        
        self.executions[execution.execution_id] = execution
        self.stats["total_executions"] += 1
        
        try:
            execution.status = "running"
            
            # 验证参数
            self._validate_params(skill, params)
            
            # 执行
            if skill.type == SkillType.ACTION:
                result = await self._execute_action(skill, params)
            elif skill.type == SkillType.WORKFLOW:
                result = await self._execute_workflow(skill, params)
            elif skill.type == SkillType.CONDITIONAL:
                result = await self._execute_conditional(skill, params)
            elif skill.type == SkillType.LOOP:
                result = await self._execute_loop(skill, params)
            else:
                result = await self._execute_action(skill, params)
            
            execution.result = result
            execution.status = "completed"
            execution.completed_at = datetime.now().timestamp()
            
            self.stats["successful_executions"] += 1
            
            logger.info(f"技能执行成功: {skill_id} ({execution.execution_id})")
            return result
            
        except Exception as e:
            execution.status = "failed"
            execution.error = str(e)
            execution.completed_at = datetime.now().timestamp()
            
            self.stats["failed_executions"] += 1
            
            logger.error(f"技能执行失败: {skill_id} - {e}")
            raise
    
    async def _execute_action(self, skill: Skill, params: Dict) -> Any:
        """执行动作类型技能"""
        if skill.handler:
            if asyncio.iscoroutinefunction(skill.handler):
                return await skill.handler(**params)
            else:
                return skill.handler(**params)
        else:
            raise RuntimeError(f"技能没有处理函数: {skill.id}")
    
    async def _execute_workflow(self, skill: Skill, params: Dict) -> Any:
        """执行工作流类型技能"""
        results = []
        context = dict(params)
        
        for step in skill.workflow:
            step_type = step.get("type", "skill")
            
            if step_type == "skill":
                # 执行子技能
                sub_skill_id = step.get("skill_id")
                sub_params = step.get("params", {})
                
                # 替换参数中的变量
                for key, value in sub_params.items():
                    if isinstance(value, str) and value.startswith("$"):
                        var_name = value[1:]
                        sub_params[key] = context.get(var_name)
                
                result = await self.execute(sub_skill_id, **sub_params)
                results.append(result)
                
                # 保存结果到上下文
                output_key = step.get("output")
                if output_key:
                    context[output_key] = result
            
            elif step_type == "mcp":
                # 执行 MCP 工具
                from core.mcp_manager import mcp_manager
                tool_name = step.get("tool")
                tool_params = step.get("params", {})
                result = await mcp_manager.call_tool(tool_name, tool_params)
                results.append(result)
            
            elif step_type == "code":
                # 执行代码（受限沙箱：禁用危险内置函数）
                code = step.get("code")
                _SAFE_BUILTINS = {
                    k: getattr(__builtins__, k) if hasattr(__builtins__, k)
                    else __builtins__[k] if isinstance(__builtins__, dict) else None
                    for k in [
                        "len", "range", "str", "int", "float", "list", "dict",
                        "bool", "tuple", "set", "frozenset", "type",
                        "isinstance", "issubclass", "enumerate", "zip",
                        "map", "filter", "sorted", "reversed", "min", "max",
                        "sum", "abs", "round", "print", "repr", "hash",
                        "True", "False", "None",
                    ]
                    if (hasattr(__builtins__, k) if not isinstance(__builtins__, dict)
                        else k in __builtins__)
                }
                restricted_globals = {"__builtins__": _SAFE_BUILTINS}
                local_vars = {"params": context, "result": None}
                exec(code, restricted_globals, local_vars)
                result = local_vars.get("result")
                results.append(result)
        
        return results[-1] if results else None
    
    async def _execute_conditional(self, skill: Skill, params: Dict) -> Any:
        """执行条件类型技能"""
        condition = skill.metadata.get("condition")
        if_true = skill.metadata.get("if_true")
        if_false = skill.metadata.get("if_false")
        
        # 评估条件
        result = eval(condition, {"params": params})
        
        if result:
            if if_true:
                return await self.execute(if_true, **params)
        else:
            if if_false:
                return await self.execute(if_false, **params)
        
        return None
    
    async def _execute_loop(self, skill: Skill, params: Dict) -> Any:
        """执行循环类型技能"""
        loop_skill = skill.metadata.get("skill")
        items = params.get("items", [])
        
        results = []
        for item in items:
            result = await self.execute(loop_skill, item=item)
            results.append(result)
        
        return results
    
    def _validate_params(self, skill: Skill, params: Dict):
        """验证参数"""
        for param in skill.parameters:
            if param.required and param.name not in params:
                raise ValueError(f"缺少必需参数: {param.name}")
    
    # ========================================================================
    # 技能发现
    # ========================================================================
    
    def list_skills(
        self,
        tag: str = None,
        type: SkillType = None,
        status: SkillStatus = None,
    ) -> List[Dict]:
        """列出技能"""
        skills = list(self.skills.values())
        
        if tag:
            skills = [s for s in skills if tag in s.tags]
        if type:
            skills = [s for s in skills if s.type == type]
        if status:
            skills = [s for s in skills if s.status == status]
        
        return [s.to_dict() for s in skills]
    
    def get_skill(self, id: str) -> Optional[Dict]:
        """获取技能详情"""
        if id in self.skills:
            return self.skills[id].to_dict()
        return None
    
    def search_skills(self, query: str) -> List[Dict]:
        """搜索技能"""
        query = query.lower()
        results = []
        
        for skill in self.skills.values():
            if (query in skill.name.lower() or
                query in skill.description.lower() or
                any(query in tag.lower() for tag in skill.tags)):
                results.append(skill.to_dict())
        
        return results
    
    # ========================================================================
    # 技能包加载
    # ========================================================================
    
    async def load_skill_package(
        self,
        source: str,
        name: str = None,
    ) -> bool:
        """
        加载技能包
        
        Args:
            source: 来源 (本地路径或 GitHub URL)
            name: 包名
        
        Returns:
            是否成功
        """
        try:
            if source.startswith("http"):
                # 从 GitHub 加载
                return await self._load_from_github(source, name)
            else:
                # 从本地加载
                return await self._load_from_local(source)
        except Exception as e:
            logger.error(f"加载技能包失败: {source} - {e}")
            return False
    
    async def _load_from_github(self, url: str, name: str = None) -> bool:
        """从 GitHub 加载"""
        # 克隆仓库
        if not name:
            name = url.split("/")[-1].replace(".git", "")
        
        target_dir = self.skills_dir / name
        
        if target_dir.exists():
            # 更新
            subprocess.run(["git", "pull"], cwd=target_dir, check=True)
        else:
            # 克隆
            subprocess.run(["git", "clone", url, str(target_dir)], check=True)
        
        self._skill_packages[name] = str(target_dir)
        
        # 加载技能
        return await self._load_from_local(str(target_dir))
    
    async def _load_from_local(self, path: str) -> bool:
        """从本地加载"""
        skill_dir = Path(path)
        
        # 查找 skill.json
        skill_file = skill_dir / "skill.json"
        if not skill_file.exists():
            logger.warning(f"技能定义文件不存在: {skill_file}")
            return False
        
        with open(skill_file, encoding="utf-8") as f:
            skill_def = json.load(f)
        
        # 加载处理函数
        handler = None
        if "handler_file" in skill_def:
            handler_path = skill_dir / skill_def["handler_file"]
            if handler_path.exists():
                spec = importlib.util.spec_from_file_location(
                    f"skill_{skill_def['id']}",
                    handler_path,
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                handler_name = skill_def.get("handler_function", "execute")
                handler = getattr(module, handler_name, None)
        
        # 注册技能
        self.register_skill(
            id=skill_def.get("id", skill_dir.name),
            name=skill_def.get("name", skill_dir.name),
            description=skill_def.get("description", ""),
            handler=handler,
            type=SkillType(skill_def.get("type", "action")),
            parameters=skill_def.get("parameters", []),
            workflow=skill_def.get("workflow", []),
            tags=skill_def.get("tags", []),
            version=skill_def.get("version", "1.0.0"),
            author=skill_def.get("author", ""),
            metadata=skill_def.get("metadata", {}),
        )
        
        logger.info(f"加载技能: {skill_def.get('id', skill_dir.name)}")
        return True
    
    # ========================================================================
    # 内置技能
    # ========================================================================
    
    def register_builtin_skills(self):
        """注册内置技能（含实际 handler）"""

        # 网页搜索
        self.register_skill(
            id="web_search",
            name="网页搜索",
            description="搜索网页内容",
            type=SkillType.ACTION,
            handler=self._builtin_web_search,
            parameters=[
                {"name": "query", "type": "string", "description": "搜索关键词", "required": True},
                {"name": "num_results", "type": "integer", "description": "结果数量", "default": 5},
            ],
            tags=["search", "web"],
        )

        # 文件操作
        self.register_skill(
            id="file_read",
            name="读取文件",
            description="读取文件内容",
            type=SkillType.ACTION,
            handler=self._builtin_file_read,
            parameters=[
                {"name": "path", "type": "string", "description": "文件路径", "required": True},
            ],
            tags=["file", "io"],
        )

        # 代码执行
        self.register_skill(
            id="code_execute",
            name="执行代码",
            description="执行 Python 代码",
            type=SkillType.ACTION,
            handler=self._builtin_code_execute,
            parameters=[
                {"name": "code", "type": "string", "description": "Python 代码", "required": True},
            ],
            tags=["code", "execute"],
        )

        # 设备控制
        self.register_skill(
            id="device_control",
            name="设备控制",
            description="控制设备执行操作",
            type=SkillType.ACTION,
            handler=self._builtin_device_control,
            parameters=[
                {"name": "device_id", "type": "string", "description": "设备 ID", "required": True},
                {"name": "action", "type": "string", "description": "操作", "required": True},
                {"name": "params", "type": "object", "description": "参数", "default": {}},
            ],
            tags=["device", "control"],
        )

        logger.info("已注册内置技能（含 handler）")

    # ── 内置技能 handler ────────────────────────────────────

    async def _builtin_web_search(self, query: str, num_results: int = 5, **kwargs) -> Dict:
        """网页搜索：委托给 httpx GET 请求（简单实现）"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1},
                )
                data = resp.json()
                results = []
                for item in (data.get("RelatedTopics") or [])[:num_results]:
                    if isinstance(item, dict) and "Text" in item:
                        results.append({"text": item["Text"], "url": item.get("FirstURL", "")})
                return {"success": True, "query": query, "results": results}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _builtin_file_read(self, path: str, **kwargs) -> Dict:
        """读取文件"""
        import os
        if not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(1_000_000)  # 1 MB 上限
            return {"success": True, "path": path, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _builtin_code_execute(self, code: str, **kwargs) -> Dict:
        """在受限环境中执行 Python 代码"""
        import io, contextlib
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        local_ns: Dict = {}
        try:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(compile(code, "<skill_code_execute>", "exec"), {"__builtins__": __builtins__}, local_ns)
            return {
                "success": True,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
            }
        except Exception as e:
            return {"success": False, "error": str(e), "stderr": stderr_buf.getvalue()}

    async def _builtin_device_control(self, device_id: str, action: str, params: Dict = None, **kwargs) -> Dict:
        """设备控制：委托给 DeviceAgentManager"""
        try:
            from core.device_agent_manager import DeviceAgentManager
            manager = DeviceAgentManager.instance() if hasattr(DeviceAgentManager, 'instance') else None
            if manager:
                return await manager.execute_on_device(device_id, action, params or {})
            return {"success": False, "error": "DeviceAgentManager not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def load_from_config(self):
        """从配置文件加载技能包；若文件不存在则创建默认模板"""
        if not self.config_path.exists():
            self._create_default_config()

        try:
            with open(self.config_path, encoding="utf-8") as f:
                config = json.load(f)

            # 注册配置中声明的内置技能（元数据注册，无 handler）
            for skill_def in config.get("builtin_skills", []):
                sid = skill_def.get("id", "")
                if sid and sid not in self.skills:
                    self.register_skill(
                        id=sid,
                        name=skill_def.get("name", sid),
                        description=skill_def.get("description", ""),
                        type=SkillType(skill_def.get("type", "action")),
                        tags=skill_def.get("tags", []),
                    )

            # 加载 auto_load=true 的技能包
            loaded = 0
            for pkg in config.get("skill_packages", []):
                if not pkg.get("auto_load", False):
                    continue
                try:
                    source = pkg.get("source", "")
                    if source:
                        await self.load_skill_package(source, pkg.get("name"))
                        loaded += 1
                except Exception as pkg_err:
                    logger.warning(f"加载技能包 '{pkg.get('name')}' 失败: {pkg_err}")

            logger.info(f"从配置注册了 {len(self.skills)} 个技能，加载了 {loaded} 个技能包")
        except Exception as e:
            logger.error(f"加载技能配置失败: {e}")

    def _create_default_config(self):
        """若配置文件不存在则创建默认模板"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            default = {
                "version": "1.0.0",
                "description": "技能配置 - 支持动态加载技能包",
                "builtin_skills": [],
                "skill_packages": [],
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
            logger.info(f"已创建默认技能配置模板: {self.config_path}")
        except Exception as e:
            logger.warning(f"创建技能配置模板失败: {e}")


# ============================================================================
# 全局实例
# ============================================================================

skill_manager = SkillManager.get_instance()


# ============================================================================
# 便捷函数
# ============================================================================

async def execute_skill(skill_id: str, **params) -> Any:
    """执行技能"""
    return await skill_manager.execute(skill_id, **params)


def register_skill(id: str, name: str, description: str, **kwargs):
    """注册技能"""
    return skill_manager.register_skill(id, name, description, **kwargs)
