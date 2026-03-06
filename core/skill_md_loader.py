"""
UFO Galaxy - SKILL.md 格式加载器
================================

兼容 OpenClaw 的 SKILL.md 格式
支持简洁的 Markdown + YAML frontmatter 格式

SKILL.md 格式示例:
---
name: weather
description: "Get current weather"
version: "1.0.0"
tags: ["weather", "api"]
---

# Weather Skill

## When to Use
- "What's the weather?"

## Commands
curl "wttr.in/London?format=3"
"""

import re
import json
import logging
import asyncio
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("UFO-Galaxy.SkillMD")


@dataclass
class SkillMD:
    """SKILL.md 解析结果"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Markdown 内容
    content: str = ""
    
    # 解析的命令
    commands: List[Dict[str, str]] = field(default_factory=list)
    
    # 来源
    source_path: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "homepage": self.homepage,
            "metadata": self.metadata,
            "content": self.content,
            "commands": self.commands,
            "source_path": self.source_path,
        }


class SkillMDLoader:
    """
    SKILL.md 格式加载器
    
    兼容 OpenClaw 的技能格式
    """
    
    _instance = None
    
    def __init__(self):
        self.skills: Dict[str, SkillMD] = {}
        logger.info("SKILL.md 加载器初始化")
    
    @classmethod
    def get_instance(cls) -> "SkillMDLoader":
        if cls._instance is None:
            cls._instance = SkillMDLoader()
        return cls._instance
    
    def parse(self, content: str, source_path: str = "") -> Optional[SkillMD]:
        """
        解析 SKILL.md 内容
        
        Args:
            content: SKILL.md 文件内容
            source_path: 来源路径
        
        Returns:
            解析后的 SkillMD 对象
        """
        try:
            # 提取 YAML frontmatter
            frontmatter = {}
            md_content = content
            
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    yaml_content = parts[1].strip()
                    md_content = parts[2].strip()
                    
                    # 简单解析 YAML (不依赖 PyYAML)
                    frontmatter = self._parse_yaml(yaml_content)
            
            # 创建 SkillMD 对象
            skill = SkillMD(
                name=frontmatter.get("name", "unnamed"),
                description=frontmatter.get("description", ""),
                version=frontmatter.get("version", "1.0.0"),
                author=frontmatter.get("author", ""),
                tags=frontmatter.get("tags", []),
                homepage=frontmatter.get("homepage", ""),
                metadata=frontmatter.get("metadata", {}),
                content=md_content,
                source_path=source_path,
            )
            
            # 解析命令
            skill.commands = self._extract_commands(md_content)
            
            return skill
            
        except Exception as e:
            logger.error(f"解析 SKILL.md 失败: {e}")
            return None
    
    def _parse_yaml(self, yaml_content: str) -> Dict:
        """简单解析 YAML frontmatter"""
        result = {}
        
        for line in yaml_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            # key: value
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                
                # 处理引号
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                
                # 处理列表
                if value.startswith("[") and value.endswith("]"):
                    # 简单列表解析
                    items = value[1:-1].split(",")
                    value = [item.strip().strip('"').strip("'") for item in items if item.strip()]
                
                # 处理字典
                elif value.startswith("{"):
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                result[key] = value
        
        return result
    
    def _extract_commands(self, md_content: str) -> List[Dict[str, str]]:
        """从 Markdown 中提取命令"""
        commands = []
        
        # 提取代码块
        pattern = r'```(\w+)?\n(.*?)```'
        matches = re.findall(pattern, md_content, re.DOTALL)
        
        for lang, code in matches:
            lang = lang or "bash"
            code = code.strip()
            
            # 只提取 bash/sh 命令
            if lang in ["bash", "sh", "shell", ""]:
                for line in code.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        commands.append({
                            "language": lang,
                            "command": line,
                        })
        
        return commands
    
    async def load(self, path: str, skill_id: str = None) -> Dict[str, Any]:
        """
        加载 SKILL.md 文件
        
        Args:
            path: SKILL.md 文件路径或包含 SKILL.md 的目录
            skill_id: 自定义技能 ID
        
        Returns:
            加载结果
        """
        path = Path(path)
        
        # 确定文件路径
        if path.is_file():
            skill_file = path
            skill_dir = path.parent
        elif path.is_dir():
            skill_file = path / "SKILL.md"
            skill_dir = path
        else:
            return {"success": False, "error": f"路径不存在: {path}"}
        
        if not skill_file.exists():
            return {"success": False, "error": f"找不到 SKILL.md: {skill_file}"}
        
        try:
            # 读取文件
            content = skill_file.read_text()
            
            # 解析
            skill = self.parse(content, str(skill_dir))
            
            if not skill:
                return {"success": False, "error": "解析失败"}
            
            # 使用自定义 ID 或名称
            skill_id = skill_id or skill.name.lower().replace(" ", "-")
            
            # 存储
            self.skills[skill_id] = skill
            
            logger.info(f"加载技能: {skill.name} ({skill_id})")
            
            return {
                "success": True,
                "skill_id": skill_id,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "commands_count": len(skill.commands),
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def execute(
        self,
        skill_id: str,
        params: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        执行技能
        
        Args:
            skill_id: 技能 ID
            params: 参数 (用于替换命令中的占位符)
        
        Returns:
            执行结果
        """
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}
        
        skill = self.skills[skill_id]
        params = params or {}
        
        results = []
        
        for cmd_info in skill.commands:
            command = cmd_info["command"]
            
            # 替换参数
            for key, value in params.items():
                command = command.replace(f"{{{key}}}", str(value))
                command = command.replace(f"${key}", str(value))
            
            try:
                # 执行命令
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60
                )
                
                results.append({
                    "command": command,
                    "success": process.returncode == 0,
                    "stdout": stdout.decode(),
                    "stderr": stderr.decode(),
                })
                
            except asyncio.TimeoutError:
                results.append({
                    "command": command,
                    "success": False,
                    "error": "执行超时",
                })
            except Exception as e:
                results.append({
                    "command": command,
                    "success": False,
                    "error": str(e),
                })
        
        return {
            "success": all(r["success"] for r in results),
            "results": results,
        }
    
    def list_skills(self) -> List[Dict]:
        """列出所有技能"""
        return [skill.to_dict() for skill in self.skills.values()]
    
    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取技能详情"""
        if skill_id in self.skills:
            return self.skills[skill_id].to_dict()
        return None
    
    def unload(self, skill_id: str) -> Dict[str, Any]:
        """卸载技能"""
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}
        
        skill = self.skills.pop(skill_id)
        
        return {
            "success": True,
            "skill_id": skill_id,
            "name": skill.name,
        }


# 全局实例
skill_md_loader = SkillMDLoader.get_instance()
