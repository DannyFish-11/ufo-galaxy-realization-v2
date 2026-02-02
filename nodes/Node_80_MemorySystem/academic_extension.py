#!/usr/bin/env python3
"""
Node 80: Memory System - Academic Extension
学术功能增强模块

功能:
1. 论文笔记管理
2. 引用关系追踪
3. 学术标签分类
4. 文献检索增强
"""

import os
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 配置
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_TOKEN", "")

# 请求模型
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
    citations: List[str] = []  # 引用的其他论文 ID

class CitationNetwork(BaseModel):
    paper_id: str
    cited_by: List[str] = []  # 被哪些论文引用
    cites: List[str] = []     # 引用了哪些论文

# 学术笔记管理
class AcademicMemoryManager:
    """学术记忆管理器"""
    
    def __init__(self):
        self.memos_url = MEMOS_URL
        self.memos_token = MEMOS_TOKEN
    
    async def save_paper_note(self, paper: PaperNote) -> bool:
        """保存论文笔记到 Memos"""
        try:
            if not self.memos_token:
                logger.warning("未配置 MEMOS_TOKEN，无法保存")
                return False
            
            # 构建 Markdown 内容
            content = self._format_paper_note(paper)
            
            # 调用 Memos API
            url = f"{self.memos_url}/api/v1/memos"
            headers = {
                "Authorization": f"Bearer {self.memos_token}",
                "Content-Type": "application/json"
            }
            data = {
                "content": content,
                "visibility": "PRIVATE"
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
            
            logger.info(f"论文笔记已保存: {paper.title[:50]}...")
            return True
        
        except Exception as e:
            logger.error(f"保存论文笔记失败: {e}")
            return False
    
    def _format_paper_note(self, paper: PaperNote) -> str:
        """格式化论文笔记为 Markdown"""
        content = f"""# 📄 {paper.title}

## 基本信息

- **来源**: {paper.source}
- **ID**: `{paper.paper_id}`
- **发布日期**: {paper.published_date}
- **链接**: {paper.url}

## 作者

{self._format_authors(paper.authors)}

## 摘要

{paper.abstract}

"""
        
        # 添加笔记
        if paper.notes:
            content += f"""## 我的笔记

{paper.notes}

"""
        
        # 添加引用
        if paper.citations:
            content += f"""## 引用文献

{self._format_citations(paper.citations)}

"""
        
        # 添加标签
        if paper.tags:
            content += f"""## 标签

{' '.join(['#' + tag.replace(' ', '_') for tag in paper.tags])}

"""
        
        content += f"""---
*保存时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*由 UFO³ Galaxy Node_80 (Academic Extension) 管理*
"""
        
        return content
    
    def _format_authors(self, authors: List[str]) -> str:
        """格式化作者列表"""
        if len(authors) <= 5:
            return ', '.join(authors)
        else:
            return ', '.join(authors[:5]) + f' 等 {len(authors)} 人'
    
    def _format_citations(self, citations: List[str]) -> str:
        """格式化引用列表"""
        return '\n'.join([f"- `{cit}`" for cit in citations])
    
    async def search_paper_notes(self, query: str, tags: Optional[List[str]] = None) -> List[Dict]:
        """搜索论文笔记"""
        try:
            if not self.memos_token:
                logger.warning("未配置 MEMOS_TOKEN，无法搜索")
                return []
            
            # 构建搜索过滤器
            filters = [f"content contains '{query}'"]
            if tags:
                for tag in tags:
                    filters.append(f"content contains '#{tag.replace(' ', '_')}'")
            
            filter_str = " && ".join(filters)
            
            # 调用 Memos API
            url = f"{self.memos_url}/api/v1/memos"
            headers = {
                "Authorization": f"Bearer {self.memos_token}"
            }
            params = {
                "filter": filter_str,
                "pageSize": 50
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
            
            data = response.json()
            memos = data.get("memos", [])
            
            logger.info(f"找到 {len(memos)} 条论文笔记")
            return memos
        
        except Exception as e:
            logger.error(f"搜索论文笔记失败: {e}")
            return []
    
    async def get_citation_network(self, paper_id: str) -> CitationNetwork:
        """获取论文的引用网络"""
        try:
            # 搜索引用了该论文的笔记
            cited_by_memos = await self.search_paper_notes(paper_id)
            
            # 搜索该论文引用的其他论文
            cites_memos = await self.search_paper_notes(f"引用文献.*{paper_id}")
            
            # 提取论文 ID
            cited_by = [self._extract_paper_id(memo) for memo in cited_by_memos]
            cites = [self._extract_paper_id(memo) for memo in cites_memos]
            
            return CitationNetwork(
                paper_id=paper_id,
                cited_by=[id for id in cited_by if id],
                cites=[id for id in cites if id]
            )
        
        except Exception as e:
            logger.error(f"获取引用网络失败: {e}")
            return CitationNetwork(paper_id=paper_id)
    
    def _extract_paper_id(self, memo: Dict) -> Optional[str]:
        """从 Memo 中提取论文 ID"""
        try:
            content = memo.get("content", "")
            # 查找 ID 行
            for line in content.split('\n'):
                if line.startswith("- **ID**:"):
                    return line.split("`")[1]
            return None
        except:
            return None
    
    async def get_papers_by_tag(self, tag: str) -> List[Dict]:
        """根据标签获取论文"""
        return await self.search_paper_notes("", tags=[tag])
    
    async def get_recent_papers(self, days: int = 7) -> List[Dict]:
        """获取最近的论文笔记"""
        try:
            if not self.memos_token:
                logger.warning("未配置 MEMOS_TOKEN，无法获取")
                return []
            
            url = f"{self.memos_url}/api/v1/memos"
            headers = {
                "Authorization": f"Bearer {self.memos_token}"
            }
            params = {
                "pageSize": 50
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
            
            data = response.json()
            memos = data.get("memos", [])
            
            # 过滤论文笔记（包含 "📄" 的）
            paper_memos = [m for m in memos if "📄" in m.get("content", "")]
            
            logger.info(f"找到 {len(paper_memos)} 条最近的论文笔记")
            return paper_memos[:days]
        
        except Exception as e:
            logger.error(f"获取最近论文失败: {e}")
            return []
    
    async def export_papers_to_bibtex(self, paper_ids: List[str]) -> str:
        """导出论文为 BibTeX 格式"""
        bibtex_entries = []
        
        for paper_id in paper_ids:
            memos = await self.search_paper_notes(paper_id)
            if memos:
                memo = memos[0]
                entry = self._memo_to_bibtex(memo)
                if entry:
                    bibtex_entries.append(entry)
        
        return '\n\n'.join(bibtex_entries)
    
    def _memo_to_bibtex(self, memo: Dict) -> Optional[str]:
        """将 Memo 转换为 BibTeX 条目"""
        try:
            content = memo.get("content", "")
            lines = content.split('\n')
            
            # 提取信息
            title = ""
            authors = []
            year = ""
            paper_id = ""
            url = ""
            
            for i, line in enumerate(lines):
                if line.startswith("# 📄"):
                    title = line.replace("# 📄", "").strip()
                elif "**ID**:" in line:
                    paper_id = line.split("`")[1]
                elif "**发布日期**:" in line:
                    year = line.split(":")[-1].strip()[:4]
                elif "**链接**:" in line:
                    url = line.split(":")[-1].strip()
                elif line.startswith("## 作者"):
                    if i + 2 < len(lines):
                        authors_line = lines[i + 2]
                        authors = [a.strip() for a in authors_line.split(',')]
            
            # 生成 BibTeX
            cite_key = paper_id.replace(":", "_").replace("/", "_")
            author_str = " and ".join(authors[:3])
            
            bibtex = f"""@article{{{cite_key},
  title = {{{title}}},
  author = {{{author_str}}},
  year = {{{year}}},
  url = {{{url}}}
}}"""
            
            return bibtex
        
        except Exception as e:
            logger.error(f"转换 BibTeX 失败: {e}")
            return None

# 全局实例
academic_manager = AcademicMemoryManager()
