"""
Galaxy Skills 层 (技能模块系统)
================================
动态加载和管理技能模块，提供可扩展的能力系统

功能：
1. 技能注册和发现
2. 技能加载和卸载
3. 技能执行和编排
4. 技能市场（下载和安装）
"""

import os
import sys
import json
import asyncio
import logging
import importlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("Galaxy.SkillsLayer")

# ============================================================================
# 技能数据模型
# ============================================================================

class SkillStatus(Enum):
    """技能状态"""
    UNINSTALLED = "uninstalled"
    INSTALLED = "installed"
    LOADED = "loaded"
    RUNNING = "running"
    ERROR = "error"

class SkillCategory(Enum):
    """技能类别"""
    CORE = "core"           # 核心技能
    HARDWARE = "hardware"   # 硬件控制
    AI = "ai"               # AI 能力
    PRODUCTIVITY = "productivity"  # 生产力
    ENTERTAINMENT = "entertainment"  # 娱乐
    CUSTOM = "custom"       # 自定义

@dataclass
class SkillAction:
    """技能动作"""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: str = "any"
    
    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns
        }

@dataclass
class Skill:
    """技能定义"""
    id: str
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "Galaxy"
    category: SkillCategory = SkillCategory.CUSTOM
    status: SkillStatus = SkillStatus.UNINSTALLED
    actions: List[SkillAction] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    module_path: str = ""
    installed_at: str = ""
    last_used: str = ""
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category.value,
            "status": self.status.value,
            "actions_count": len(self.actions),
            "dependencies": self.dependencies,
            "installed_at": self.installed_at,
            "last_used": self.last_used
        }

# ============================================================================
# 内置技能
# ============================================================================

BUILTIN_SKILLS = {
    # 核心技能
    "chat": {
        "id": "chat",
        "name": "智能对话",
        "description": "自然语言对话能力",
        "category": "core",
        "actions": [
            {"name": "chat", "description": "进行对话"},
            {"name": "summarize", "description": "总结对话"},
        ]
    },
    
    "search": {
        "id": "search",
        "name": "信息搜索",
        "description": "搜索网络信息",
        "category": "core",
        "actions": [
            {"name": "web_search", "description": "网页搜索"},
            {"name": "image_search", "description": "图片搜索"},
            {"name": "news_search", "description": "新闻搜索"},
        ]
    },
    
    "code": {
        "id": "code",
        "name": "代码助手",
        "description": "代码生成和解释",
        "category": "ai",
        "actions": [
            {"name": "generate", "description": "生成代码"},
            {"name": "explain", "description": "解释代码"},
            {"name": "debug", "description": "调试代码"},
            {"name": "refactor", "description": "重构代码"},
        ]
    },
    
    "translate": {
        "id": "translate",
        "name": "翻译",
        "description": "多语言翻译",
        "category": "ai",
        "actions": [
            {"name": "translate", "description": "翻译文本"},
            {"name": "detect", "description": "检测语言"},
        ]
    },
    
    # 硬件技能
    "screenshot": {
        "id": "screenshot",
        "name": "截图",
        "description": "截取屏幕内容",
        "category": "hardware",
        "actions": [
            {"name": "capture", "description": "截取全屏"},
            {"name": "capture_region", "description": "截取区域"},
            {"name": "capture_window", "description": "截取窗口"},
        ]
    },
    
    "voice": {
        "id": "voice",
        "name": "语音",
        "description": "语音输入输出",
        "category": "hardware",
        "actions": [
            {"name": "listen", "description": "语音识别"},
            {"name": "speak", "description": "语音合成"},
        ]
    },
    
    "camera": {
        "id": "camera",
        "name": "摄像头",
        "description": "摄像头控制",
        "category": "hardware",
        "actions": [
            {"name": "capture", "description": "拍照"},
            {"name": "record", "description": "录像"},
            {"name": "stream", "description": "视频流"},
        ]
    },
    
    # 数字生命卡
    "digital_life_card": {
        "id": "digital_life_card",
        "name": "数字生命卡",
        "description": "流浪地球数字生命卡管理",
        "category": "hardware",
        "actions": [
            {"name": "init", "description": "初始化存储"},
            {"name": "read_memory", "description": "读取记忆"},
            {"name": "write_memory", "description": "写入记忆"},
            {"name": "backup", "description": "备份"},
            {"name": "restore", "description": "恢复"},
            {"name": "encrypt", "description": "加密数据"},
            {"name": "decrypt", "description": "解密数据"},
        ]
    },
    
    # 苯苯机械狗
    "benben_dog": {
        "id": "benben_dog",
        "name": "苯苯机械狗",
        "description": "流浪地球苯苯机械狗控制",
        "category": "hardware",
        "actions": [
            {"name": "connect", "description": "连接机械狗"},
            {"name": "disconnect", "description": "断开连接"},
            {"name": "move_forward", "description": "前进"},
            {"name": "move_backward", "description": "后退"},
            {"name": "turn_left", "description": "左转"},
            {"name": "turn_right", "description": "右转"},
            {"name": "stop", "description": "停止"},
            {"name": "sit", "description": "坐下"},
            {"name": "stand", "description": "站立"},
            {"name": "wave", "description": "挥手"},
            {"name": "speak", "description": "说话"},
            {"name": "get_camera", "description": "获取摄像头"},
            {"name": "get_status", "description": "获取状态"},
        ]
    },
    
    # 机械臂
    "robot_arm": {
        "id": "robot_arm",
        "name": "机械臂",
        "description": "机械臂控制",
        "category": "hardware",
        "actions": [
            {"name": "connect", "description": "连接机械臂"},
            {"name": "move_to", "description": "移动到位置"},
            {"name": "grab", "description": "抓取"},
            {"name": "release", "description": "释放"},
            {"name": "home", "description": "回原点"},
            {"name": "get_position", "description": "获取位置"},
        ]
    },
    
    # 生产力
    "calendar": {
        "id": "calendar",
        "name": "日历",
        "description": "日程管理",
        "category": "productivity",
        "actions": [
            {"name": "add_event", "description": "添加事件"},
            {"name": "list_events", "description": "列出事件"},
            {"name": "remove_event", "description": "删除事件"},
        ]
    },
    
    "notes": {
        "id": "notes",
        "name": "笔记",
        "description": "笔记管理",
        "category": "productivity",
        "actions": [
            {"name": "create", "description": "创建笔记"},
            {"name": "read", "description": "读取笔记"},
            {"name": "update", "description": "更新笔记"},
            {"name": "delete", "description": "删除笔记"},
            {"name": "search", "description": "搜索笔记"},
        ]
    },
}

# ============================================================================
# 技能层管理器
# ============================================================================

class SkillsLayer:
    """技能层管理器"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir: Optional[Path] = None):
        if self._initialized:
            return
        
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.skills_dir = self.config_dir / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        self.skills: Dict[str, Skill] = {}
        self.loaded_modules: Dict[str, Any] = {}
        
        self._load_builtin_skills()
        self._load_user_skills()
        
        self._initialized = True
        logger.info(f"Skills 层初始化完成，已加载 {len(self.skills)} 个技能")
    
    def _load_builtin_skills(self):
        """加载内置技能"""
        for skill_id, config in BUILTIN_SKILLS.items():
            skill = Skill(
                id=config["id"],
                name=config["name"],
                description=config["description"],
                category=SkillCategory(config.get("category", "custom")),
                status=SkillStatus.INSTALLED
            )
            
            for action_config in config.get("actions", []):
                action = SkillAction(
                    name=action_config["name"],
                    description=action_config["description"]
                )
                skill.actions.append(action)
            
            self.skills[skill.id] = skill
    
    def _load_user_skills(self):
        """加载用户技能"""
        config_file = self.skills_dir / "installed.json"
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                for skill_config in data.get("skills", []):
                    self.install_skill(skill_config)
            except Exception as e:
                logger.error(f"加载用户技能失败: {e}")
    
    def install_skill(self, config: Dict[str, Any]) -> bool:
        """安装技能"""
        try:
            skill = Skill(
                id=config["id"],
                name=config["name"],
                description=config.get("description", ""),
                version=config.get("version", "1.0.0"),
                author=config.get("author", "User"),
                category=SkillCategory(config.get("category", "custom")),
                status=SkillStatus.INSTALLED,
                dependencies=config.get("dependencies", []),
                module_path=config.get("module_path", ""),
                installed_at=datetime.now().isoformat()
            )
            
            for action_config in config.get("actions", []):
                action = SkillAction(
                    name=action_config["name"],
                    description=action_config.get("description", ""),
                    parameters=action_config.get("parameters", {})
                )
                skill.actions.append(action)
            
            self.skills[skill.id] = skill
            self._save_installed_skills()
            logger.info(f"安装技能: {skill.name}")
            return True
        except Exception as e:
            logger.error(f"安装技能失败: {e}")
            return False
    
    def uninstall_skill(self, skill_id: str) -> bool:
        """卸载技能"""
        if skill_id not in self.skills:
            return False
        
        if skill_id in BUILTIN_SKILLS:
            logger.warning(f"不能卸载内置技能: {skill_id}")
            return False
        
        del self.skills[skill_id]
        self.loaded_modules.pop(skill_id, None)
        self._save_installed_skills()
        logger.info(f"卸载技能: {skill_id}")
        return True
    
    def _save_installed_skills(self):
        """保存已安装技能"""
        config_file = self.skills_dir / "installed.json"
        
        skills_data = []
        for skill in self.skills.values():
            if skill.id not in BUILTIN_SKILLS:
                skills_data.append({
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "version": skill.version,
                    "author": skill.author,
                    "category": skill.category.value,
                    "dependencies": skill.dependencies,
                    "module_path": skill.module_path,
                    "actions": [a.to_dict() for a in skill.actions]
                })
        
        config_file.write_text(json.dumps({"skills": skills_data}, indent=2, ensure_ascii=False))
    
    async def execute(self, skill_id: str, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行技能动作"""
        if skill_id not in self.skills:
            return {"success": False, "error": f"Skill not found: {skill_id}"}
        
        skill = self.skills[skill_id]
        
        # 检查动作是否存在
        action_names = [a.name for a in skill.actions]
        if action not in action_names:
            return {"success": False, "error": f"Action not found: {action}"}
        
        # 更新最后使用时间
        skill.last_used = datetime.now().isoformat()
        
        # 执行动作
        try:
            result = await self._execute_impl(skill, action, params or {})
            return {"success": True, "result": result, "skill": skill_id, "action": action}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _execute_impl(self, skill: Skill, action: str, params: Dict) -> Any:
        """实际执行"""
        # 模拟执行 - 实际需要加载模块并调用
        return {
            "message": f"Executed {action} on {skill.name}",
            "params": params
        }
    
    def get_skills(self, category: str = None) -> List[Skill]:
        """获取技能列表"""
        skills = list(self.skills.values())
        if category:
            skills = [s for s in skills if s.category.value == category]
        return skills
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能"""
        return self.skills.get(skill_id)
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "skills_count": len(self.skills),
            "loaded_count": len(self.loaded_modules),
            "categories": {
                cat.value: len([s for s in self.skills.values() if s.category == cat])
                for cat in SkillCategory
            },
            "skills": [s.to_dict() for s in self.skills.values()]
        }

# ============================================================================
# 全局实例
# ============================================================================

_skills_layer: Optional[SkillsLayer] = None

def get_skills_layer() -> SkillsLayer:
    """获取 Skills 层实例"""
    global _skills_layer
    if _skills_layer is None:
        _skills_layer = SkillsLayer()
    return _skills_layer
