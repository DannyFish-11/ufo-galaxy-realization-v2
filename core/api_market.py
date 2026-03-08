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

import json
import logging
import re
from datetime import datetime
import os
import time
import hashlib
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("UFO-Galaxy.MarketAPI")

router = APIRouter()


# ============================================================================
# 技能存储 (JSON 文件持久化)
# ============================================================================

_MARKET_STORE_DIR = os.getenv("UFO_MARKET_STORE_DIR", "./data/market")
_MARKET_STORE_FILE = os.path.join(_MARKET_STORE_DIR, "published_skills.json")


def _load_published_skills() -> List[Dict[str, Any]]:
    """从持久化文件加载已发布技能"""
    if os.path.exists(_MARKET_STORE_FILE):
        try:
            with open(_MARKET_STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"加载技能存储失败: {e}")
    return []


def _save_published_skills(skills: List[Dict[str, Any]]):
    """持久化已发布技能到文件"""
    os.makedirs(_MARKET_STORE_DIR, exist_ok=True)
    with open(_MARKET_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)


# 运行时缓存
_published_skills: List[Dict[str, Any]] = _load_published_skills()


def _verify_publish_token(token: str) -> bool:
    """验证发布令牌 (基于 UFO_API_TOKEN)"""
    expected = os.getenv("UFO_API_TOKEN", "")
    if not expected:
        # 未设置令牌时，只允许本地开发环境
        logger.warning("UFO_API_TOKEN 未设置，技能发布仅允许本地访问")
        return True
    return hashlib.sha256(token.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()


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
    for skill in BUILTIN_SKILLS + _published_skills:
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
    for skill in BUILTIN_SKILLS + _published_skills:
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
async def publish_skill(
    req: SkillPublishRequest,
    authorization: str = Header(default=""),
):
    """发布技能 (需要认证)"""
    # 认证: 验证 Bearer token
    token = authorization.replace("Bearer ", "").strip()
    if not _verify_publish_token(token):
        return JSONResponse(
            {"success": False, "error": "认证失败: 无效的 API Token"},
            status_code=401,
        )

    # 输入校验
    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="技能名称不能为空")
    if not req.description or not req.description.strip():
        raise HTTPException(status_code=400, detail="技能描述不能为空")
    if not _VERSION_PATTERN.match(req.version):
        raise HTTPException(status_code=400, detail="版本号格式无效，应为 x.y.z")

    skill_id = re.sub(r'-+', '-', re.sub(r'[^a-z0-9-]', '-', req.name.lower().strip())).strip('-')

    # 检查是否已存在（同名更新）
    existing_idx = None
    for i, s in enumerate(_published_skills):
        if s["id"] == skill_id:
            existing_idx = i
            break

    # 检查是否与内置技能重名
    if skill_id in [s["id"] for s in BUILTIN_SKILLS] and existing_idx is None:
        raise HTTPException(status_code=409, detail=f"技能 '{skill_id}' 与内置技能冲突")

    skill_data: Dict[str, Any] = {
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

    if existing_idx is not None:
        skill_data["downloads"] = _published_skills[existing_idx].get("downloads", 0)
        skill_data["rating"] = _published_skills[existing_idx].get("rating", 0.0)
        _published_skills[existing_idx] = skill_data
        action = "updated"
    else:
        _published_skills.append(skill_data)
        action = "published"

    _save_published_skills(_published_skills)
    logger.info(f"技能 {action}: {skill_id} v{req.version} by {skill_data['author']}")

    return JSONResponse({
        "success": True,
        "message": f"技能已{action}",
        "skill": {k: v for k, v in skill_data.items() if k != "content"},
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
    return JSONResponse({
        "success": True,
        "stats": {
            "total_skills": len(all_skills),
            "builtin_skills": len(BUILTIN_SKILLS),
            "published_skills": len(_published_skills),
            "total_downloads": sum(s["downloads"] for s in all_skills),
            "avg_rating": sum(s["rating"] for s in all_skills) / max(len(all_skills), 1),
        },
    })


# ============================================================================
# 导出
# ============================================================================

__all__ = ["router"]
