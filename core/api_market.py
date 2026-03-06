"""
UFO Galaxy - 技能市场 API
========================

提供技能市场的 REST API

API 端点:
- GET  /api/v1/market/skills         - 列出市场技能
- GET  /api/v1/market/skills/{id}    - 获取技能详情
- GET  /api/v1/market/search         - 搜索技能
- POST /api/v1/market/publish        - 发布技能
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("UFO-Galaxy.MarketAPI")

router = APIRouter()


# ============================================================================
# 数据模型
# ============================================================================

class SkillPublishRequest(BaseModel):
    """技能发布请求"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = []
    content: str = ""  # SKILL.md 内容


# ============================================================================
# 模拟市场数据 (实际应该连接数据库)
# ============================================================================

# 内置技能市场
BUILTIN_SKILLS = [
    {
        "id": "weather",
        "name": "Weather",
        "description": "Get current weather and forecasts",
        "version": "1.0.0",
        "author": "UFO Galaxy",
        "tags": ["weather", "api"],
        "downloads": 1000,
        "rating": 4.5,
    },
    {
        "id": "github",
        "name": "GitHub",
        "description": "GitHub operations via gh CLI",
        "version": "1.0.0",
        "author": "UFO Galaxy",
        "tags": ["github", "git", "cli"],
        "downloads": 800,
        "rating": 4.8,
    },
    {
        "id": "web_search",
        "name": "Web Search",
        "description": "Search the web using DuckDuckGo",
        "version": "1.0.0",
        "author": "UFO Galaxy",
        "tags": ["search", "web"],
        "downloads": 600,
        "rating": 4.2,
    },
    {
        "id": "file_operations",
        "name": "File Operations",
        "description": "Read, write, and manage files",
        "version": "1.0.0",
        "author": "UFO Galaxy",
        "tags": ["file", "io"],
        "downloads": 500,
        "rating": 4.0,
    },
    {
        "id": "email",
        "name": "Email",
        "description": "Send and manage emails",
        "version": "1.0.0",
        "author": "UFO Galaxy",
        "tags": ["email", "communication"],
        "downloads": 400,
        "rating": 3.8,
    },
]

# 用户发布的技能（运行时内存存储）
_published_skills: List[Dict[str, Any]] = []

# 版本号校验模式（例如 "1.2.3"）
_VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+$')


# ============================================================================
# API 端点
# ============================================================================

@router.get("/api/v1/market/skills")
async def list_market_skills(
    tag: str = None,
    limit: int = 20,
    offset: int = 0,
):
    """列出市场技能"""
    skills = BUILTIN_SKILLS + _published_skills
    
    # 按标签过滤
    if tag:
        skills = [s for s in skills if tag in s["tags"]]
    
    # 分页
    total = len(skills)
    skills = skills[offset:offset + limit]
    
    return JSONResponse({
        "success": True,
        "skills": skills,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.get("/api/v1/market/skills/{skill_id}")
async def get_market_skill(skill_id: str):
    """获取技能详情"""
    for skill in BUILTIN_SKILLS:
        if skill["id"] == skill_id:
            # 返回完整信息
            return JSONResponse({
                "success": True,
                "skill": {
                    **skill,
                    "download_url": f"https://raw.githubusercontent.com/DannyFish-11/ufo-galaxy-realization-v2/main/skills/examples/{skill_id}/SKILL.md",
                    "readme": f"# {skill['name']}\n\n{skill['description']}",
                },
            })
    
    return JSONResponse({
        "success": False,
        "error": "技能不存在",
    }, status_code=404)


@router.get("/api/v1/market/search")
async def search_market_skills(q: str, limit: int = 10):
    """搜索技能"""
    q = q.lower()
    
    results = []
    for skill in BUILTIN_SKILLS:
        # 搜索名称、描述、标签
        if (q in skill["name"].lower() or
            q in skill["description"].lower() or
            any(q in tag.lower() for tag in skill["tags"])):
            results.append(skill)
    
    return JSONResponse({
        "success": True,
        "query": q,
        "skills": results[:limit],
        "total": len(results),
    })


@router.post("/api/v1/market/publish")
async def publish_skill(req: SkillPublishRequest):
    """发布技能"""
    # 输入校验
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="技能名称不能为空")
    if not req.description or not req.description.strip():
        raise HTTPException(status_code=400, detail="技能描述不能为空")
    if not _VERSION_PATTERN.match(req.version):
        raise HTTPException(status_code=400, detail="版本号格式无效，应为 x.y.z")

    skill_id = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', req.name.lower().strip())).strip('-')

    # 检查是否与内置技能或已发布技能重名
    all_ids = [s["id"] for s in BUILTIN_SKILLS + _published_skills]
    if skill_id in all_ids:
        raise HTTPException(status_code=409, detail=f"技能 '{skill_id}' 已存在")

    skill_entry: Dict[str, Any] = {
        "id": skill_id,
        "name": req.name.strip(),
        "description": req.description.strip(),
        "version": req.version,
        "author": req.author.strip() or "anonymous",
        "tags": [t.strip() for t in req.tags if t.strip()],
        "content": req.content,
        "downloads": 0,
        "rating": 0.0,
        "published_at": datetime.utcnow().isoformat() + "Z",
    }
    _published_skills.append(skill_entry)
    logger.info(f"技能已发布: {skill_id} v{req.version} by {skill_entry['author']}")

    return JSONResponse({
        "success": True,
        "message": f"技能 '{req.name}' 发布成功",
        "skill": {k: v for k, v in skill_entry.items() if k != "content"},
    }, status_code=201)


@router.get("/api/v1/market/tags")
async def list_tags():
    """列出所有标签"""
    tags = set()
    for skill in BUILTIN_SKILLS + _published_skills:
        tags.update(skill["tags"])
    
    return JSONResponse({
        "success": True,
        "tags": sorted(list(tags)),
    })


@router.get("/api/v1/market/stats")
async def market_stats():
    """市场统计"""
    all_skills = BUILTIN_SKILLS + _published_skills
    avg_rating = (
        sum(s["rating"] for s in all_skills) / len(all_skills)
        if all_skills else 0.0
    )
    return JSONResponse({
        "success": True,
        "stats": {
            "total_skills": len(all_skills),
            "builtin_skills": len(BUILTIN_SKILLS),
            "published_skills": len(_published_skills),
            "total_downloads": sum(s["downloads"] for s in all_skills),
            "avg_rating": avg_rating,
        },
    })


# ============================================================================
# 导出
# ============================================================================

__all__ = ["router"]
