"""
Node 85: Prompt Library - 提示词库
提示词管理、模板优化、最佳实践

功能：
1. 提示词管理 - 存储和检索提示词
2. 模板系统 - 参数化提示词模板
3. 版本控制 - 提示词版本管理
4. 效果评估 - 提示词效果统计
5. 最佳实践 - 提示词优化建议

优势：
- 提示词复用
- 模板化管理
- 版本追踪
- 效果分析
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "85")
NODE_NAME = os.getenv("NODE_NAME", "PromptLibrary")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class PromptTemplate(BaseModel):
    id: str
    name: str
    description: str
    template: str
    variables: List[str] = []
    category: str
    tags: List[str] = []
    version: int = 1
    created_at: str
    updated_at: Optional[str] = None
    usage_count: int = 0
    success_rate: Optional[float] = None

class PromptVersion(BaseModel):
    version: int
    template: str
    created_at: str
    notes: Optional[str] = None

class PromptUsage(BaseModel):
    prompt_id: str
    variables: Dict[str, Any]
    result: Optional[str] = None
    success: bool
    feedback: Optional[str] = None
    timestamp: str

# =============================================================================
# Prompt Library Service
# =============================================================================

class PromptLibraryService:
    """提示词库服务"""
    
    def __init__(self):
        self.prompts: Dict[str, PromptTemplate] = {}
        self.versions: Dict[str, List[PromptVersion]] = {}
        self.usage_history: List[PromptUsage] = []
        
        # 加载默认提示词
        self._load_default_prompts()
    
    def _load_default_prompts(self):
        """加载默认提示词"""
        default_prompts = [
            {
                "id": "code_review",
                "name": "Code Review",
                "description": "代码审查提示词",
                "template": """请审查以下代码，重点关注：
1. 代码质量和可读性
2. 潜在的 bug 和安全问题
3. 性能优化建议
4. 最佳实践

代码语言：{language}
代码内容：
```{language}
{code}
```

请提供详细的审查意见。""",
                "variables": ["language", "code"],
                "category": "development",
                "tags": ["code", "review", "quality"]
            },
            {
                "id": "task_decompose",
                "name": "Task Decomposition",
                "description": "任务分解提示词",
                "template": """请将以下复杂任务分解为具体的执行步骤：

任务描述：{task}

要求：
1. 每个步骤要具体可执行
2. 步骤之间要有逻辑顺序
3. 标明每个步骤的预期结果
4. 估算每个步骤的时间

请以 JSON 格式返回分解结果。""",
                "variables": ["task"],
                "category": "planning",
                "tags": ["task", "planning", "decomposition"]
            },
            {
                "id": "data_analysis",
                "name": "Data Analysis",
                "description": "数据分析提示词",
                "template": """请分析以下数据并提供洞察：

数据类型：{data_type}
数据内容：
{data}

分析要求：
1. 数据概览和统计特征
2. 关键趋势和模式
3. 异常值检测
4. 可操作的建议

请提供详细的分析报告。""",
                "variables": ["data_type", "data"],
                "category": "analysis",
                "tags": ["data", "analysis", "insights"]
            },
            {
                "id": "text_summary",
                "name": "Text Summarization",
                "description": "文本摘要提示词",
                "template": """请总结以下文本的核心内容：

文本：
{text}

要求：
1. 提取关键信息
2. 保持逻辑清晰
3. 长度控制在 {max_length} 字以内
4. 使用 {language} 语言

请提供简洁准确的摘要。""",
                "variables": ["text", "max_length", "language"],
                "category": "text",
                "tags": ["summary", "text", "extraction"]
            },
            {
                "id": "creative_writing",
                "name": "Creative Writing",
                "description": "创意写作提示词",
                "template": """请根据以下要求进行创意写作：

主题：{topic}
风格：{style}
长度：{length}
受众：{audience}

要求：
1. 内容要有创意和吸引力
2. 符合指定的风格和受众
3. 结构清晰，逻辑连贯
4. 语言生动，富有表现力

请开始创作。""",
                "variables": ["topic", "style", "length", "audience"],
                "category": "writing",
                "tags": ["creative", "writing", "content"]
            },
            {
                "id": "problem_solving",
                "name": "Problem Solving",
                "description": "问题解决提示词",
                "template": """请帮助解决以下问题：

问题描述：{problem}
背景信息：{context}
约束条件：{constraints}

请提供：
1. 问题分析
2. 可能的解决方案（至少 3 个）
3. 每个方案的优缺点
4. 推荐方案和理由
5. 实施步骤

请给出详细的解决方案。""",
                "variables": ["problem", "context", "constraints"],
                "category": "problem_solving",
                "tags": ["problem", "solution", "analysis"]
            },
            {
                "id": "translation",
                "name": "Translation",
                "description": "翻译提示词",
                "template": """请将以下文本从 {source_lang} 翻译成 {target_lang}：

原文：
{text}

要求：
1. 准确传达原文含义
2. 符合目标语言习惯
3. 保持原文风格和语气
4. 注意专业术语的准确性

请提供高质量的翻译。""",
                "variables": ["source_lang", "target_lang", "text"],
                "category": "translation",
                "tags": ["translation", "language", "localization"]
            }
        ]
        
        for prompt_data in default_prompts:
            prompt = PromptTemplate(
                **prompt_data,
                created_at=datetime.now().isoformat()
            )
            self.prompts[prompt.id] = prompt
            self.versions[prompt.id] = [
                PromptVersion(
                    version=1,
                    template=prompt.template,
                    created_at=prompt.created_at,
                    notes="Initial version"
                )
            ]
        
        logger.info(f"Loaded {len(self.prompts)} default prompts")
    
    def get_prompt(self, prompt_id: str) -> PromptTemplate:
        """获取提示词"""
        if prompt_id not in self.prompts:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return self.prompts[prompt_id]
    
    def list_prompts(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None
    ) -> List[PromptTemplate]:
        """列出提示词"""
        prompts = list(self.prompts.values())
        
        if category:
            prompts = [p for p in prompts if p.category == category]
        
        if tag:
            prompts = [p for p in prompts if tag in p.tags]
        
        return prompts
    
    def render_prompt(self, prompt_id: str, variables: Dict[str, Any]) -> str:
        """渲染提示词"""
        prompt = self.get_prompt(prompt_id)
        
        # 检查变量
        missing_vars = set(prompt.variables) - set(variables.keys())
        if missing_vars:
            raise HTTPException(
                status_code=400,
                detail=f"Missing variables: {', '.join(missing_vars)}"
            )
        
        # 渲染模板
        try:
            rendered = prompt.template.format(**variables)
            
            # 更新使用计数
            prompt.usage_count += 1
            
            return rendered
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"Invalid variable: {e}")
    
    def add_prompt(
        self,
        prompt_id: str,
        name: str,
        description: str,
        template: str,
        variables: List[str],
        category: str,
        tags: List[str] = []
    ) -> PromptTemplate:
        """添加提示词"""
        if prompt_id in self.prompts:
            raise HTTPException(status_code=400, detail="Prompt ID already exists")
        
        prompt = PromptTemplate(
            id=prompt_id,
            name=name,
            description=description,
            template=template,
            variables=variables,
            category=category,
            tags=tags,
            created_at=datetime.now().isoformat()
        )
        
        self.prompts[prompt_id] = prompt
        self.versions[prompt_id] = [
            PromptVersion(
                version=1,
                template=template,
                created_at=prompt.created_at,
                notes="Initial version"
            )
        ]
        
        logger.info(f"Added prompt: {prompt_id}")
        return prompt
    
    def update_prompt(
        self,
        prompt_id: str,
        template: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None
    ) -> PromptTemplate:
        """更新提示词"""
        prompt = self.get_prompt(prompt_id)
        
        if template:
            # 创建新版本
            new_version = prompt.version + 1
            self.versions[prompt_id].append(
                PromptVersion(
                    version=new_version,
                    template=template,
                    created_at=datetime.now().isoformat(),
                    notes=notes
                )
            )
            prompt.template = template
            prompt.version = new_version
        
        if description:
            prompt.description = description
        
        if tags:
            prompt.tags = tags
        
        prompt.updated_at = datetime.now().isoformat()
        
        logger.info(f"Updated prompt: {prompt_id} (v{prompt.version})")
        return prompt
    
    def delete_prompt(self, prompt_id: str):
        """删除提示词"""
        if prompt_id not in self.prompts:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        del self.prompts[prompt_id]
        del self.versions[prompt_id]
        
        logger.info(f"Deleted prompt: {prompt_id}")
    
    def get_versions(self, prompt_id: str) -> List[PromptVersion]:
        """获取提示词版本历史"""
        if prompt_id not in self.versions:
            raise HTTPException(status_code=404, detail="Prompt not found")
        return self.versions[prompt_id]
    
    def record_usage(
        self,
        prompt_id: str,
        variables: Dict[str, Any],
        result: Optional[str] = None,
        success: bool = True,
        feedback: Optional[str] = None
    ):
        """记录使用情况"""
        usage = PromptUsage(
            prompt_id=prompt_id,
            variables=variables,
            result=result,
            success=success,
            feedback=feedback,
            timestamp=datetime.now().isoformat()
        )
        
        self.usage_history.append(usage)
        
        # 更新成功率
        prompt = self.prompts.get(prompt_id)
        if prompt:
            usages = [u for u in self.usage_history if u.prompt_id == prompt_id]
            success_count = sum(1 for u in usages if u.success)
            prompt.success_rate = success_count / len(usages) if usages else None
    
    def get_statistics(self, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """获取统计信息"""
        if prompt_id:
            prompt = self.get_prompt(prompt_id)
            usages = [u for u in self.usage_history if u.prompt_id == prompt_id]
            
            return {
                "prompt_id": prompt_id,
                "usage_count": prompt.usage_count,
                "success_rate": prompt.success_rate,
                "total_usages": len(usages),
                "recent_usages": [u.dict() for u in usages[-10:]]
            }
        else:
            return {
                "total_prompts": len(self.prompts),
                "total_usages": len(self.usage_history),
                "by_category": {
                    cat: len([p for p in self.prompts.values() if p.category == cat])
                    for cat in set(p.category for p in self.prompts.values())
                },
                "top_used": sorted(
                    self.prompts.values(),
                    key=lambda p: p.usage_count,
                    reverse=True
                )[:5]
            }

# =============================================================================
# FastAPI Application
# =============================================================================

library = PromptLibraryService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 85: Prompt Library")
    yield
    logger.info("Node 85 shutdown complete")

app = FastAPI(
    title="Node 85: Prompt Library",
    description="提示词库 - 提示词管理、模板优化、最佳实践",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 85: Prompt Library",
        "status": "running",
        "total_prompts": len(library.prompts),
        "categories": list(set(p.category for p in library.prompts.values())),
        "features": [
            "Prompt management",
            "Template system",
            "Version control",
            "Usage tracking",
            "Statistics"
        ]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "prompts_loaded": len(library.prompts),
        "total_usages": len(library.usage_history),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/prompts")
async def list_prompts(category: Optional[str] = None, tag: Optional[str] = None):
    """列出提示词"""
    prompts = library.list_prompts(category, tag)
    return {
        "prompts": [p.dict() for p in prompts],
        "count": len(prompts)
    }

@app.get("/prompts/{prompt_id}")
async def get_prompt(prompt_id: str):
    """获取提示词"""
    prompt = library.get_prompt(prompt_id)
    return prompt.dict()

@app.post("/prompts")
async def add_prompt(
    prompt_id: str,
    name: str,
    description: str,
    template: str,
    variables: List[str],
    category: str,
    tags: List[str] = []
):
    """添加提示词"""
    prompt = library.add_prompt(
        prompt_id, name, description, template, variables, category, tags
    )
    return prompt.dict()

@app.put("/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    template: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    notes: Optional[str] = None
):
    """更新提示词"""
    prompt = library.update_prompt(prompt_id, template, description, tags, notes)
    return prompt.dict()

@app.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str):
    """删除提示词"""
    library.delete_prompt(prompt_id)
    return {"message": "Prompt deleted", "prompt_id": prompt_id}

@app.post("/prompts/{prompt_id}/render")
async def render_prompt(prompt_id: str, variables: Dict[str, Any]):
    """渲染提示词"""
    rendered = library.render_prompt(prompt_id, variables)
    return {
        "prompt_id": prompt_id,
        "variables": variables,
        "rendered": rendered
    }

@app.get("/prompts/{prompt_id}/versions")
async def get_versions(prompt_id: str):
    """获取版本历史"""
    versions = library.get_versions(prompt_id)
    return {
        "prompt_id": prompt_id,
        "versions": [v.dict() for v in versions],
        "count": len(versions)
    }

@app.post("/prompts/{prompt_id}/usage")
async def record_usage(
    prompt_id: str,
    variables: Dict[str, Any],
    result: Optional[str] = None,
    success: bool = True,
    feedback: Optional[str] = None
):
    """记录使用情况"""
    library.record_usage(prompt_id, variables, result, success, feedback)
    return {"message": "Usage recorded", "prompt_id": prompt_id}

@app.get("/statistics")
async def get_statistics(prompt_id: Optional[str] = None):
    """获取统计信息"""
    stats = library.get_statistics(prompt_id)
    return stats

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8085)
