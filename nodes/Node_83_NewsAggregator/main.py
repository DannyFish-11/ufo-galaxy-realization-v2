"""
Node 83: News Aggregator - 新闻聚合器
实时新闻、RSS 订阅、内容聚合

功能：
1. RSS 订阅 - 订阅和解析 RSS/Atom 源
2. 新闻搜索 - 搜索特定主题新闻
3. 热点追踪 - 追踪热门话题
4. 内容过滤 - 关键词过滤和分类
5. 定时更新 - 自动更新新闻源

优势：
- 多源聚合
- 实时更新
- 智能过滤
- 分类管理
"""

import os
import asyncio
import logging
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import uvicorn
import httpx
import feedparser
from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "83")
NODE_NAME = os.getenv("NODE_NAME", "NewsAggregator")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 默认新闻源
DEFAULT_FEEDS = {
    "tech": [
        "https://news.ycombinator.com/rss",
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
    ],
    "general": [
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        "https://feeds.bbci.co.uk/news/rss.xml",
    ],
    "science": [
        "https://www.science.org/rss/news_current.xml",
        "https://www.nature.com/nature.rss",
    ]
}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class NewsArticle(BaseModel):
    id: str
    title: str
    link: str
    summary: Optional[str] = None
    content: Optional[str] = None
    published: Optional[str] = None
    author: Optional[str] = None
    source: str
    category: Optional[str] = None
    tags: List[str] = []

class RSSFeed(BaseModel):
    url: HttpUrl
    category: str
    enabled: bool = True
    last_updated: Optional[str] = None

class NewsQuery(BaseModel):
    keywords: Optional[List[str]] = []
    category: Optional[str] = None
    source: Optional[str] = None
    limit: int = 20
    hours: int = 24  # 过去多少小时的新闻

# =============================================================================
# News Aggregator Service
# =============================================================================

class NewsAggregatorService:
    """新闻聚合服务"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30)
        self.feeds: Dict[str, List[RSSFeed]] = {}
        self.articles: List[NewsArticle] = []
        self.article_cache: Dict[str, NewsArticle] = {}
        
        # 加载默认订阅源
        for category, urls in DEFAULT_FEEDS.items():
            self.feeds[category] = [
                RSSFeed(url=url, category=category) for url in urls
            ]
    
    def _generate_article_id(self, link: str) -> str:
        """生成文章 ID"""
        return hashlib.md5(link.encode()).hexdigest()[:16]
    
    async def fetch_rss(self, feed: RSSFeed) -> List[NewsArticle]:
        """获取 RSS 源"""
        articles = []
        
        try:
            response = await self.http_client.get(str(feed.url))
            response.raise_for_status()
            
            # 解析 RSS
            parsed = feedparser.parse(response.text)
            
            for entry in parsed.entries[:50]:  # 限制每个源最多 50 条
                article_id = self._generate_article_id(entry.link)
                
                # 提取发布时间
                published = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6]).isoformat()
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6]).isoformat()
                
                # 提取摘要
                summary = None
                if hasattr(entry, 'summary'):
                    # 清理 HTML 标签
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    summary = soup.get_text()[:500]
                
                # 提取内容
                content = None
                if hasattr(entry, 'content') and entry.content:
                    soup = BeautifulSoup(entry.content[0].value, 'html.parser')
                    content = soup.get_text()[:2000]
                
                article = NewsArticle(
                    id=article_id,
                    title=entry.title if hasattr(entry, 'title') else "No Title",
                    link=entry.link,
                    summary=summary,
                    content=content,
                    published=published,
                    author=entry.author if hasattr(entry, 'author') else None,
                    source=str(feed.url),
                    category=feed.category,
                    tags=[]
                )
                
                articles.append(article)
                self.article_cache[article_id] = article
            
            # 更新订阅源状态
            feed.last_updated = datetime.now().isoformat()
            
            logger.info(f"Fetched {len(articles)} articles from {feed.url}")
        
        except Exception as e:
            logger.error(f"Failed to fetch RSS {feed.url}: {e}")
        
        return articles
    
    async def update_all_feeds(self):
        """更新所有订阅源"""
        logger.info("Updating all feeds...")
        
        all_articles = []
        
        for category, feeds in self.feeds.items():
            for feed in feeds:
                if feed.enabled:
                    articles = await self.fetch_rss(feed)
                    all_articles.extend(articles)
        
        # 更新文章列表（去重）
        self.articles = list(self.article_cache.values())
        
        # 按发布时间排序
        self.articles.sort(
            key=lambda x: x.published if x.published else "",
            reverse=True
        )
        
        logger.info(f"Total articles: {len(self.articles)}")
    
    def search_articles(self, query: NewsQuery) -> List[NewsArticle]:
        """搜索文章"""
        results = self.articles
        
        # 过滤分类
        if query.category:
            results = [a for a in results if a.category == query.category]
        
        # 过滤来源
        if query.source:
            results = [a for a in results if query.source in a.source]
        
        # 过滤时间
        if query.hours:
            cutoff_time = datetime.now() - timedelta(hours=query.hours)
            results = [
                a for a in results
                if a.published and datetime.fromisoformat(a.published) > cutoff_time
            ]
        
        # 关键词过滤
        if query.keywords:
            filtered = []
            for article in results:
                text = f"{article.title} {article.summary or ''} {article.content or ''}".lower()
                if any(kw.lower() in text for kw in query.keywords):
                    filtered.append(article)
            results = filtered
        
        # 限制数量
        return results[:query.limit]
    
    def add_feed(self, url: str, category: str):
        """添加订阅源"""
        feed = RSSFeed(url=url, category=category)
        
        if category not in self.feeds:
            self.feeds[category] = []
        
        # 检查是否已存在
        if any(f.url == feed.url for f in self.feeds[category]):
            raise HTTPException(status_code=400, detail="Feed already exists")
        
        self.feeds[category].append(feed)
        logger.info(f"Added feed: {url} ({category})")
    
    def remove_feed(self, url: str):
        """删除订阅源"""
        for category, feeds in self.feeds.items():
            self.feeds[category] = [f for f in feeds if str(f.url) != url]
        
        logger.info(f"Removed feed: {url}")
    
    async def get_trending_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取热门话题（基于关键词频率）"""
        from collections import Counter
        import re
        
        # 提取所有标题中的词
        words = []
        for article in self.articles[:100]:  # 只分析最近 100 篇
            # 简单的词频统计（英文）
            title_words = re.findall(r'\b[A-Za-z]{4,}\b', article.title.lower())
            words.extend(title_words)
        
        # 排除常见词
        stopwords = {'that', 'this', 'with', 'from', 'have', 'will', 'what', 'when', 'where', 'about'}
        words = [w for w in words if w not in stopwords]
        
        # 统计频率
        counter = Counter(words)
        trending = counter.most_common(limit)
        
        return [
            {"topic": word, "count": count}
            for word, count in trending
        ]
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# FastAPI Application
# =============================================================================

aggregator = NewsAggregatorService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 83: News Aggregator")
    
    # 启动时更新一次
    await aggregator.update_all_feeds()
    
    # 启动后台更新任务
    async def background_updater():
        while True:
            await asyncio.sleep(3600)  # 每小时更新一次
            try:
                await aggregator.update_all_feeds()
            except Exception as e:
                logger.error(f"Background update failed: {e}")
    
    task = asyncio.create_task(background_updater())
    
    yield
    
    task.cancel()
    await aggregator.close()
    logger.info("Node 83 shutdown complete")

app = FastAPI(
    title="Node 83: News Aggregator",
    description="新闻聚合器 - RSS 订阅、新闻搜索、热点追踪",
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
        "service": "Node 83: News Aggregator",
        "status": "running",
        "total_articles": len(aggregator.articles),
        "total_feeds": sum(len(feeds) for feeds in aggregator.feeds.values()),
        "categories": list(aggregator.feeds.keys()),
        "features": [
            "RSS subscription",
            "News search",
            "Trending topics",
            "Content filtering"
        ]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "articles_cached": len(aggregator.articles),
        "feeds_active": sum(1 for feeds in aggregator.feeds.values() for f in feeds if f.enabled),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/articles")
async def get_articles(
    category: Optional[str] = None,
    limit: int = 20,
    hours: int = 24
):
    """获取文章列表"""
    query = NewsQuery(
        category=category,
        limit=limit,
        hours=hours
    )
    
    articles = aggregator.search_articles(query)
    
    return {
        "articles": [a.dict() for a in articles],
        "count": len(articles),
        "query": query.dict()
    }

@app.post("/search")
async def search_articles(query: NewsQuery):
    """搜索文章"""
    articles = aggregator.search_articles(query)
    
    return {
        "articles": [a.dict() for a in articles],
        "count": len(articles),
        "query": query.dict()
    }

@app.get("/article/{article_id}")
async def get_article(article_id: str):
    """获取单篇文章"""
    article = aggregator.article_cache.get(article_id)
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return article.dict()

@app.get("/feeds")
async def get_feeds():
    """获取所有订阅源"""
    all_feeds = []
    for category, feeds in aggregator.feeds.items():
        all_feeds.extend([f.dict() for f in feeds])
    
    return {
        "feeds": all_feeds,
        "count": len(all_feeds),
        "by_category": {
            cat: len(feeds) for cat, feeds in aggregator.feeds.items()
        }
    }

@app.post("/feeds")
async def add_feed(url: str, category: str):
    """添加订阅源"""
    aggregator.add_feed(url, category)
    
    return {
        "message": "Feed added",
        "url": url,
        "category": category
    }

@app.delete("/feeds")
async def remove_feed(url: str):
    """删除订阅源"""
    aggregator.remove_feed(url)
    
    return {
        "message": "Feed removed",
        "url": url
    }

@app.post("/update")
async def update_feeds(background_tasks: BackgroundTasks):
    """手动更新所有订阅源"""
    background_tasks.add_task(aggregator.update_all_feeds)
    
    return {
        "message": "Update started",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/trending")
async def get_trending(limit: int = 10):
    """获取热门话题"""
    topics = await aggregator.get_trending_topics(limit)
    
    return {
        "topics": topics,
        "count": len(topics),
        "timestamp": datetime.now().isoformat()
    }

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8083)
