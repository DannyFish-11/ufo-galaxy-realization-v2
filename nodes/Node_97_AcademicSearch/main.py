#!/usr/bin/env python3
"""
Node 97: Academic Search
学术搜索节点 - 集成多个学术数据源

功能:
1. arXiv 论文搜索
2. Google Scholar 搜索（通过 SerpAPI）
3. Semantic Scholar API
4. PubMed 搜索
5. 自动保存到 Memos
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import xml.etree.ElementTree as ET

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI 应用
app = FastAPI(title="Academic Search Node", version="1.0.0")

# 配置
ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
PUBMED_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_TOKEN", "")

# 请求模型
class SearchRequest(BaseModel):
    query: str
    source: str = "all"  # all, arxiv, scholar, semantic_scholar, pubmed
    max_results: int = 10
    save_to_memos: bool = True

class PaperNote(BaseModel):
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    published_date: str
    url: str
    source: str
    notes: Optional[str] = None
    tags: List[str] = []

# arXiv 搜索
async def search_arxiv(query: str, max_results: int = 10) -> List[Dict]:
    """搜索 arXiv 论文"""
    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ARXIV_API, params=params)
            response.raise_for_status()
        
        # 解析 XML
        root = ET.fromstring(response.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        papers = []
        for entry in root.findall('atom:entry', ns):
            paper = {
                "paper_id": entry.find('atom:id', ns).text.split('/')[-1],
                "title": entry.find('atom:title', ns).text.strip(),
                "authors": [author.find('atom:name', ns).text for author in entry.findall('atom:author', ns)],
                "abstract": entry.find('atom:summary', ns).text.strip(),
                "published_date": entry.find('atom:published', ns).text[:10],
                "url": entry.find('atom:id', ns).text,
                "source": "arXiv",
                "tags": ["arXiv"]
            }
            
            # 提取分类
            categories = entry.findall('atom:category', ns)
            for cat in categories:
                term = cat.get('term')
                if term:
                    paper["tags"].append(term)
            
            papers.append(paper)
        
        logger.info(f"arXiv 搜索完成: 找到 {len(papers)} 篇论文")
        return papers
    
    except Exception as e:
        logger.error(f"arXiv 搜索失败: {e}")
        return []

# Semantic Scholar 搜索
async def search_semantic_scholar(query: str, max_results: int = 10) -> List[Dict]:
    """搜索 Semantic Scholar"""
    try:
        url = f"{SEMANTIC_SCHOLAR_API}/paper/search"
        params = {
            "query": query,
            "limit": max_results,
            "fields": "paperId,title,authors,abstract,year,url,citationCount"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
        
        data = response.json()
        papers = []
        
        for item in data.get("data", []):
            paper = {
                "paper_id": item.get("paperId", ""),
                "title": item.get("title", ""),
                "authors": [author.get("name", "") for author in item.get("authors", [])],
                "abstract": item.get("abstract", "N/A"),
                "published_date": str(item.get("year", "N/A")),
                "url": item.get("url", ""),
                "source": "Semantic Scholar",
                "citation_count": item.get("citationCount", 0),
                "tags": ["Semantic Scholar"]
            }
            papers.append(paper)
        
        logger.info(f"Semantic Scholar 搜索完成: 找到 {len(papers)} 篇论文")
        return papers
    
    except Exception as e:
        logger.error(f"Semantic Scholar 搜索失败: {e}")
        return []

# PubMed 搜索
async def search_pubmed(query: str, max_results: int = 10) -> List[Dict]:
    """搜索 PubMed"""
    try:
        # 第一步: 搜索获取 ID 列表
        search_url = f"{PUBMED_API}/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            search_response = await client.get(search_url, params=search_params)
            search_response.raise_for_status()
        
        search_data = search_response.json()
        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        
        if not id_list:
            logger.info("PubMed 搜索: 未找到结果")
            return []
        
        # 第二步: 获取详细信息
        fetch_url = f"{PUBMED_API}/esummary.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            fetch_response = await client.get(fetch_url, params=fetch_params)
            fetch_response.raise_for_status()
        
        fetch_data = fetch_response.json()
        papers = []
        
        for pmid, item in fetch_data.get("result", {}).items():
            if pmid == "uids":
                continue
            
            paper = {
                "paper_id": f"PMID:{pmid}",
                "title": item.get("title", ""),
                "authors": [author.get("name", "") for author in item.get("authors", [])],
                "abstract": "查看 PubMed 获取摘要",
                "published_date": item.get("pubdate", "N/A"),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "PubMed",
                "tags": ["PubMed", "医学"]
            }
            papers.append(paper)
        
        logger.info(f"PubMed 搜索完成: 找到 {len(papers)} 篇论文")
        return papers
    
    except Exception as e:
        logger.error(f"PubMed 搜索失败: {e}")
        return []

# 保存到 Memos
async def save_to_memos(paper: Dict) -> bool:
    """将论文笔记保存到 Memos"""
    try:
        if not MEMOS_TOKEN:
            logger.warning("未配置 MEMOS_TOKEN，跳过保存")
            return False
        
        # 构建 Markdown 内容
        content = f"""# 📄 {paper['title']}

**来源**: {paper['source']}  
**ID**: {paper['paper_id']}  
**发布日期**: {paper['published_date']}  
**链接**: {paper['url']}

## 作者

{', '.join(paper['authors'][:5])}{'...' if len(paper['authors']) > 5 else ''}

## 摘要

{paper['abstract']}

## 标签

{' '.join(['#' + tag.replace(' ', '_') for tag in paper['tags']])}

---
*由 UFO³ Galaxy Node_97 自动保存于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        
        # 调用 Memos API
        url = f"{MEMOS_URL}/api/v1/memos"
        headers = {
            "Authorization": f"Bearer {MEMOS_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {
            "content": content,
            "visibility": "PRIVATE"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
        
        logger.info(f"论文已保存到 Memos: {paper['title'][:50]}...")
        return True
    
    except Exception as e:
        logger.error(f"保存到 Memos 失败: {e}")
        return False

# API 端点
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "node": "Node_97_AcademicSearch",
        "version": "1.0.0",
        "memos_configured": bool(MEMOS_TOKEN)
    }

@app.post("/search")
async def search_papers(request: SearchRequest):
    """搜索学术论文"""
    try:
        all_papers = []
        
        # 根据来源搜索
        if request.source in ["all", "arxiv"]:
            arxiv_papers = await search_arxiv(request.query, request.max_results)
            all_papers.extend(arxiv_papers)
        
        if request.source in ["all", "semantic_scholar"]:
            semantic_papers = await search_semantic_scholar(request.query, request.max_results)
            all_papers.extend(semantic_papers)
        
        if request.source in ["all", "pubmed"]:
            pubmed_papers = await search_pubmed(request.query, request.max_results)
            all_papers.extend(pubmed_papers)
        
        # 保存到 Memos
        if request.save_to_memos:
            for paper in all_papers:
                await save_to_memos(paper)
        
        return {
            "success": True,
            "query": request.query,
            "source": request.source,
            "total_results": len(all_papers),
            "papers": all_papers
        }
    
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/save_note")
async def save_paper_note(note: PaperNote):
    """保存论文笔记到 Memos"""
    try:
        paper_dict = note.dict()
        success = await save_to_memos(paper_dict)
        
        return {
            "success": success,
            "paper_id": note.paper_id,
            "title": note.title
        }
    
    except Exception as e:
        logger.error(f"保存笔记失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 启动服务
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_97_PORT", "8097"))
    uvicorn.run(app, host="0.0.0.0", port=port)
