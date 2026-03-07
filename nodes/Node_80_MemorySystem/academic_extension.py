#!/usr/bin/env python3
"""
Node 80: Memory System - Academic Extension
学术功能增强模块

功能:
1. 论文笔记管理
2. 引用关系追踪
3. 学术标签分类
4. 文献检索增强
5. 自动提取论文关键词
6. 论文相似度计算
7. 推荐相关论文
8. BibTeX 导出
9. 自动生成文献综述
"""

import os
import json
import re
import logging
from typing import List, Dict, Optional
from datetime import datetime
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 配置
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_TOKEN", "")

# 常用中英文停用词（关键词提取时过滤）
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "may", "might", "should", "this", "that", "these", "those",
    "we", "our", "us", "i", "my", "you", "your", "it", "its", "they",
    "their", "them", "which", "who", "how", "what", "when", "where", "why",
    "also", "using", "based", "approach", "method", "paper", "proposed",
    "results", "show", "shows", "novel", "new", "study", "work", "model",
    "学习", "方法", "研究", "通过", "实现", "论文", "提出", "基于", "系统"
}

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
        except Exception:
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

    # ── 关键词提取 ──────────────────────────────────────────────────────────

    def extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        """从文本（标题/摘要）中自动提取关键词

        使用简单的词频统计（TF），过滤停用词，返回最高频词汇。
        不依赖任何外部库，可在离线模式下运行。

        Args:
            text: 输入文本（标题 + 摘要）
            top_n: 返回的关键词数量

        Returns:
            关键词列表（按词频降序）
        """
        # 转小写，提取词语（支持中英文）
        words = re.findall(r"[a-z]{3,}|[\u4e00-\u9fa5]{2,}", text.lower())

        # 过滤停用词
        freq: Dict[str, int] = {}
        for word in words:
            if word not in _STOP_WORDS:
                freq[word] = freq.get(word, 0) + 1

        # 按频次排序
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_n]]

    async def extract_keywords_from_memo(self, memo: Dict, top_n: int = 10) -> List[str]:
        """从 Memo 笔记中提取关键词"""
        content = memo.get("content", "")
        # 仅分析标题 + 摘要部分（减少噪音）
        title_match = re.search(r"# 📄 (.+)", content)
        abstract_match = re.search(r"## 摘要\n\n(.+?)(?:\n\n##|$)", content, re.DOTALL)
        title = title_match.group(1) if title_match else ""
        abstract = abstract_match.group(1) if abstract_match else ""
        return self.extract_keywords(f"{title} {abstract}", top_n)

    # ── 论文相似度计算 ────────────────────────────────────────────────────────

    def _keyword_jaccard_similarity(self, kw1: List[str], kw2: List[str]) -> float:
        """基于关键词的 Jaccard 相似度"""
        s1, s2 = set(kw1), set(kw2)
        if not s1 or not s2:
            return 0.0
        intersection = len(s1 & s2)
        union = len(s1 | s2)
        return intersection / union if union > 0 else 0.0

    async def compute_similarity(self, paper_id_a: str, paper_id_b: str) -> float:
        """计算两篇论文的关键词相似度（Jaccard）

        Args:
            paper_id_a: 第一篇论文 ID
            paper_id_b: 第二篇论文 ID

        Returns:
            相似度分数 0.0 ~ 1.0
        """
        memos_a = await self.search_paper_notes(paper_id_a)
        memos_b = await self.search_paper_notes(paper_id_b)

        if not memos_a or not memos_b:
            return 0.0

        kw_a = await self.extract_keywords_from_memo(memos_a[0])
        kw_b = await self.extract_keywords_from_memo(memos_b[0])
        return self._keyword_jaccard_similarity(kw_a, kw_b)

    # ── 推荐相关论文 ──────────────────────────────────────────────────────────

    async def recommend_related_papers(
        self, paper_id: str, top_n: int = 5
    ) -> List[Dict]:
        """根据关键词相似度推荐相关论文

        Args:
            paper_id: 目标论文 ID
            top_n: 返回推荐数量

        Returns:
            [{paper_id, title, similarity, memo}, ...]
        """
        # 获取目标论文笔记
        target_memos = await self.search_paper_notes(paper_id)
        if not target_memos:
            return []

        target_kw = await self.extract_keywords_from_memo(target_memos[0])
        if not target_kw:
            return []

        # 获取所有论文笔记
        all_memos = await self.get_recent_papers(days=100)
        recommendations = []

        for memo in all_memos:
            content = memo.get("content", "")
            # 跳过目标论文自身
            if paper_id in content:
                continue

            kw = await self.extract_keywords_from_memo(memo)
            similarity = self._keyword_jaccard_similarity(target_kw, kw)

            if similarity > 0:
                title_match = re.search(r"# 📄 (.+)", content)
                id_match = re.search(r"\*\*ID\*\*: `([^`]+)`", content)
                recommendations.append({
                    "paper_id": id_match.group(1) if id_match else "unknown",
                    "title": title_match.group(1) if title_match else "unknown",
                    "similarity": round(similarity, 4),
                    "keywords": kw[:5]
                })

        # 按相似度降序排列
        recommendations.sort(key=lambda x: x["similarity"], reverse=True)
        return recommendations[:top_n]

    # ── 文献综述生成 ──────────────────────────────────────────────────────────

    async def generate_literature_review(
        self,
        paper_ids: List[str],
        topic: str = ""
    ) -> str:
        """根据论文列表自动生成文献综述（Markdown 格式）

        综述内容通过提取各论文的标题、作者、摘要和关键词生成，
        不依赖外部 LLM，适合快速离线使用。

        Args:
            paper_ids: 论文 ID 列表
            topic: 综述主题（可选，填写后会加入标题）

        Returns:
            Markdown 格式的文献综述字符串
        """
        entries = []
        all_keywords: List[str] = []

        for pid in paper_ids:
            memos = await self.search_paper_notes(pid)
            if not memos:
                continue
            memo = memos[0]
            content = memo.get("content", "")

            title_match = re.search(r"# 📄 (.+)", content)
            abstract_match = re.search(r"## 摘要\n\n(.+?)(?:\n\n##|$)", content, re.DOTALL)
            authors_match = re.search(r"## 作者\n\n(.+?)(?:\n\n##|$)", content, re.DOTALL)
            date_match = re.search(r"\*\*发布日期\*\*: (.+)", content)

            title = title_match.group(1).strip() if title_match else pid
            abstract = abstract_match.group(1).strip() if abstract_match else "N/A"
            authors = authors_match.group(1).strip() if authors_match else "N/A"
            date = date_match.group(1).strip() if date_match else "N/A"

            kw = self.extract_keywords(f"{title} {abstract}")
            all_keywords.extend(kw)

            entries.append({
                "paper_id": pid,
                "title": title,
                "authors": authors,
                "date": date,
                "abstract": abstract[:300] + ("..." if len(abstract) > 300 else ""),
                "keywords": kw[:5]
            })

        if not entries:
            return "未找到相关论文笔记，请确认论文已保存到 Memos。"

        # 汇总高频关键词
        kw_freq: Dict[str, int] = {}
        for kw in all_keywords:
            kw_freq[kw] = kw_freq.get(kw, 0) + 1
        top_kw = [k for k, _ in sorted(kw_freq.items(), key=lambda x: x[1], reverse=True)[:15]]

        # 组装 Markdown 综述
        title_str = ("\u201c" + topic + "\u201d的文献综述") if topic else "文献综述"
        review = f"# {title_str}\n\n"
        review += f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
        review += f"**论文数量**: {len(entries)}  \n"
        review += f"**核心关键词**: {', '.join(top_kw)}\n\n"
        review += "---\n\n"
        review += "## 论文摘要汇总\n\n"

        for i, entry in enumerate(entries, 1):
            review += f"### {i}. {entry['title']}\n\n"
            review += f"- **作者**: {entry['authors']}\n"
            review += f"- **发布日期**: {entry['date']}\n"
            review += f"- **ID**: `{entry['paper_id']}`\n"
            review += f"- **关键词**: {', '.join(entry['keywords'])}\n\n"
            review += f"**摘要**: {entry['abstract']}\n\n"
            review += "---\n\n"

        review += "## 综合分析\n\n"
        review += (
            f"本综述共收录 {len(entries)} 篇论文，"
            f"涵盖的核心研究方向包括：{', '.join(top_kw[:8])}。\n\n"
            "各论文在研究方法和应用场景上各有侧重，"
            "建议结合引用网络进一步梳理研究脉络。\n\n"
        )
        review += (
            "*本综述由 UFO³ Galaxy Node_80 (Academic Extension) 自动生成。*\n"
        )
        return review


# 全局实例
academic_manager = AcademicMemoryManager()
