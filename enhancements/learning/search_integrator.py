#!/usr/bin/env python3
"""
Search Integrator for UFO Galaxy v5.0

Integrates multiple search sources:
- Web search (via search engines)
- ArXiv API (academic papers)
- GitHub API (code repositories)

Features:
- Unified search interface
- Result aggregation and ranking
- Async operations for performance
- Caching and rate limiting

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import time

try:
    import aiohttp
    from aiohttp import ClientSession, ClientTimeout
except ImportError:
    aiohttp = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SearchSource(Enum):
    """Available search sources."""
    WEB = "web"
    ARXIV = "arxiv"
    GITHUB = "github"


@dataclass
class SearchResult:
    """Unified search result structure."""
    id: str
    source: SearchSource
    title: str
    content: str
    url: str
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    relevance_score: float = 0.0
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique result ID."""
        content = f"{self.source.value}:{self.title}:{self.url}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'source': self.source.value,
            'title': self.title,
            'content': self.content[:500] if self.content else "",
            'url': self.url,
            'author': self.author,
            'published_date': self.published_date.isoformat() if self.published_date else None,
            'metadata': self.metadata,
            'relevance_score': self.relevance_score,
            'fetched_at': self.fetched_at.isoformat()
        }


@dataclass
class SearchQuery:
    """Search query specification."""
    query: str
    sources: List[SearchSource]
    max_results: int = 10
    filters: Dict[str, Any] = field(default_factory=dict)
    sort_by: str = "relevance"  # relevance, date, popularity


class RateLimiter:
    """Rate limiter for API calls."""
    
    def __init__(self, calls_per_minute: int = 60):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call_time: Dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()
    
    async def acquire(self, key: str = "default"):
        """Acquire rate limit token."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_call_time[key]
            
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                await asyncio.sleep(wait_time)
            
            self.last_call_time[key] = time.time()


class ResultCache:
    """Simple cache for search results."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict] = {}
    
    def _make_key(self, query: str, source: str) -> str:
        """Create cache key."""
        return hashlib.md5(f"{source}:{query}".encode()).hexdigest()
    
    def get(self, query: str, source: str) -> Optional[List[SearchResult]]:
        """Get cached results if valid."""
        key = self._make_key(query, source)
        
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        age = (datetime.now() - entry['timestamp']).total_seconds()
        
        if age > self.ttl_seconds:
            del self._cache[key]
            return None
        
        return entry['results']
    
    def set(self, query: str, source: str, results: List[SearchResult]):
        """Cache search results."""
        key = self._make_key(query, source)
        self._cache[key] = {
            'timestamp': datetime.now(),
            'results': results
        }
    
    def clear(self):
        """Clear all cached results."""
        self._cache.clear()


class SearchIntegrator:
    """
    Multi-source search integrator.
    
    Provides unified interface for searching across:
    - Web (via search APIs)
    - ArXiv (academic papers)
    - GitHub (repositories and code)
    
    Features result aggregation, ranking, and caching.
    """
    
    def __init__(
        self,
        cache_ttl: int = 3600,
        rate_limit_per_minute: int = 60
    ):
        self.cache = ResultCache(ttl_seconds=cache_ttl)
        self.rate_limiter = RateLimiter(calls_per_minute=rate_limit_per_minute)
        
        # API configurations
        self._arxiv_base_url = "http://export.arxiv.org/api/query"
        self._github_base_url = "https://api.github.com"
        
        # Session for HTTP requests
        self._session: Optional[ClientSession] = None
        
        # Statistics
        self._stats = {
            'total_searches': 0,
            'cache_hits': 0,
            'api_calls': defaultdict(int),
            'errors': defaultdict(int)
        }
        
        logger.info("SearchIntegrator initialized")
    
    async def _get_session(self) -> ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=30)
            self._session = ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def search_web(
        self,
        query: str,
        max_results: int = 10
    ) -> List[SearchResult]:
        """
        Search the web.
        
        Note: This is a simulated implementation.
        In production, integrate with actual search APIs
        (Google Custom Search, Bing API, etc.)
        """
        # Check cache
        cached = self.cache.get(query, "web")
        if cached:
            self._stats['cache_hits'] += 1
            return cached
        
        await self.rate_limiter.acquire("web")
        
        try:
            # Simulated web search results
            # In production, replace with actual API call
            results = self._simulate_web_search(query, max_results)
            
            self.cache.set(query, "web", results)
            self._stats['api_calls']['web'] += 1
            
            return results
            
        except Exception as e:
            logger.error(f"Web search error: {e}")
            self._stats['errors']['web'] += 1
            return []
    
    def _simulate_web_search(
        self,
        query: str,
        max_results: int
    ) -> List[SearchResult]:
        """Simulate web search results."""
        # This is a placeholder - replace with actual API integration
        simulated_results = [
            {
                'title': f"Result {i+1} for '{query}'",
                'snippet': f"This is a simulated search result about {query}. "
                          f"It contains relevant information that would be "
                          f"returned by a real search engine.",
                'url': f"https://example.com/result{i+1}",
                'author': None,
                'date': None
            }
            for i in range(min(max_results, 5))
        ]
        
        return [
            SearchResult(
                id="",
                source=SearchSource.WEB,
                title=r['title'],
                content=r['snippet'],
                url=r['url'],
                author=r['author'],
                relevance_score=0.9 - i * 0.1
            )
            for i, r in enumerate(simulated_results)
        ]
    
    async def search_arxiv(
        self,
        query: str,
        max_results: int = 10,
        sort_by: str = "relevance"
    ) -> List[SearchResult]:
        """
        Search ArXiv for academic papers.
        
        Uses the ArXiv API to search for papers.
        """
        # Check cache
        cached = self.cache.get(query, "arxiv")
        if cached:
            self._stats['cache_hits'] += 1
            return cached
        
        await self.rate_limiter.acquire("arxiv")
        
        try:
            session = await self._get_session()
            
            # Build ArXiv API query
            search_query = query.replace(' ', '+')
            url = (
                f"{self._arxiv_base_url}?"
                f"search_query=all:{search_query}&"
                f"start=0&"
                f"max_results={max_results}&"
                f"sortBy={sort_by}"
            )
            
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"ArXiv API returned {response.status}")
                    return []
                
                # Parse XML response
                xml_content = await response.text()
                results = self._parse_arxiv_response(xml_content)
                
                self.cache.set(query, "arxiv", results)
                self._stats['api_calls']['arxiv'] += 1
                
                return results
                
        except Exception as e:
            logger.error(f"ArXiv search error: {e}")
            self._stats['errors']['arxiv'] += 1
            return []
    
    def _parse_arxiv_response(self, xml_content: str) -> List[SearchResult]:
        """Parse ArXiv XML response."""
        results = []
        
        try:
            import xml.etree.ElementTree as ET
            
            root = ET.fromstring(xml_content)
            
            # ArXiv namespace
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            for entry in root.findall('atom:entry', ns):
                title = entry.find('atom:title', ns)
                summary = entry.find('atom:summary', ns)
                id_elem = entry.find('atom:id', ns)
                published = entry.find('atom:published', ns)
                
                # Get authors
                authors = []
                for author in entry.findall('atom:author', ns):
                    name = author.find('atom:name', ns)
                    if name is not None:
                        authors.append(name.text)
                
                if title is not None and id_elem is not None:
                    result = SearchResult(
                        id="",
                        source=SearchSource.ARXIV,
                        title=title.text.strip() if title.text else "Untitled",
                        content=summary.text.strip() if summary is not None and summary.text else "",
                        url=id_elem.text if id_elem.text else "",
                        author=", ".join(authors) if authors else None,
                        published_date=datetime.fromisoformat(published.text.replace('Z', '+00:00')) if published is not None else None,
                        metadata={'authors': authors}
                    )
                    results.append(result)
                    
        except Exception as e:
            logger.error(f"Error parsing ArXiv response: {e}")
        
        return results
    
    async def search_github(
        self,
        query: str,
        max_results: int = 10,
        search_type: str = "repositories"
    ) -> List[SearchResult]:
        """
        Search GitHub for repositories or code.
        
        Uses the GitHub Search API.
        """
        # Check cache
        cached = self.cache.get(query, "github")
        if cached:
            self._stats['cache_hits'] += 1
            return cached
        
        await self.rate_limiter.acquire("github")
        
        try:
            session = await self._get_session()
            
            # Build GitHub API query
            url = f"{self._github_base_url}/search/{search_type}"
            params = {
                'q': query,
                'per_page': max_results,
                'sort': 'stars',
                'order': 'desc'
            }
            
            headers = {}
            # Add GitHub token if available
            # headers['Authorization'] = f'token {GITHUB_TOKEN}'
            
            async with session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"GitHub API returned {response.status}")
                    return []
                
                data = await response.json()
                results = self._parse_github_response(data, search_type)
                
                self.cache.set(query, "github", results)
                self._stats['api_calls']['github'] += 1
                
                return results
                
        except Exception as e:
            logger.error(f"GitHub search error: {e}")
            self._stats['errors']['github'] += 1
            return []
    
    def _parse_github_response(
        self,
        data: Dict,
        search_type: str
    ) -> List[SearchResult]:
        """Parse GitHub API response."""
        results = []
        
        items = data.get('items', [])
        
        for item in items:
            if search_type == "repositories":
                result = SearchResult(
                    id="",
                    source=SearchSource.GITHUB,
                    title=item.get('full_name', 'Unknown'),
                    content=item.get('description', '') or "",
                    url=item.get('html_url', ''),
                    author=item.get('owner', {}).get('login'),
                    published_date=datetime.fromisoformat(
                        item.get('created_at', '').replace('Z', '+00:00')
                    ) if item.get('created_at') else None,
                    metadata={
                        'stars': item.get('stargazers_count', 0),
                        'language': item.get('language'),
                        'forks': item.get('forks_count', 0)
                    },
                    relevance_score=item.get('stargazers_count', 0) / 1000
                )
            else:
                result = SearchResult(
                    id="",
                    source=SearchSource.GITHUB,
                    title=item.get('name', 'Unknown'),
                    content=item.get('path', ''),
                    url=item.get('html_url', ''),
                    metadata={'repository': item.get('repository', {}).get('full_name')}
                )
            
            results.append(result)
        
        return results
    
    async def integrated_search(
        self,
        query: str,
        sources: List[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Perform integrated search across multiple sources.
        
        Args:
            query: Search query
            sources: List of sources to search (web, arxiv, github)
            max_results: Maximum results per source
            
        Returns:
            Aggregated and ranked results
        """
        if sources is None:
            sources = ["web", "arxiv", "github"]
        
        self._stats['total_searches'] += 1
        
        # Create search tasks
        tasks = []
        source_mapping = {
            'web': self.search_web,
            'arxiv': self.search_arxiv,
            'github': self.search_github
        }
        
        for source in sources:
            if source in source_mapping:
                tasks.append(source_mapping[source](query, max_results))
        
        # Execute searches concurrently
        results_by_source = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        all_results = []
        source_results = {}
        
        for source, results in zip(sources, results_by_source):
            if isinstance(results, Exception):
                logger.error(f"Search failed for {source}: {results}")
                source_results[source] = []
            else:
                source_results[source] = [r.to_dict() for r in results]
                all_results.extend(results)
        
        # Rank and deduplicate
        ranked_results = self._rank_results(all_results)
        
        return {
            'query': query,
            'sources': sources,
            'total_results': len(all_results),
            'unique_results': len(ranked_results),
            'by_source': source_results,
            'ranked_results': [r.to_dict() for r in ranked_results[:max_results]]
        }
    
    def _rank_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        Rank and deduplicate search results.
        
        Uses multiple factors:
        - Source relevance score
        - Recency
        - Cross-source validation
        """
        # Deduplicate by URL
        seen_urls = set()
        unique_results = []
        
        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        
        # Calculate composite score
        for result in unique_results:
            score = result.relevance_score
            
            # Boost for recency
            if result.published_date:
                age_days = (datetime.now() - result.published_date).days
                if age_days < 30:
                    score += 0.1
            
            # Boost for academic sources
            if result.source == SearchSource.ARXIV:
                score += 0.05
            
            result.relevance_score = min(1.0, score)
        
        # Sort by relevance
        unique_results.sort(key=lambda r: r.relevance_score, reverse=True)
        
        return unique_results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get search statistics."""
        return {
            'total_searches': self._stats['total_searches'],
            'cache_hits': self._stats['cache_hits'],
            'cache_hit_rate': (
                self._stats['cache_hits'] / self._stats['total_searches']
                if self._stats['total_searches'] > 0 else 0
            ),
            'api_calls': dict(self._stats['api_calls']),
            'errors': dict(self._stats['errors'])
        }
    
    def clear_cache(self):
        """Clear search cache."""
        self.cache.clear()
        logger.info("Search cache cleared")


# Example usage
async def demo():
    """Demonstrate search integration."""
    integrator = SearchIntegrator()
    
    try:
        print("=== Testing Web Search ===")
        web_results = await integrator.search_web("machine learning", max_results=3)
        for r in web_results:
            print(f"  - {r.title} ({r.relevance_score:.2f})")
        
        print("\n=== Testing ArXiv Search ===")
        arxiv_results = await integrator.search_arxiv("neural networks", max_results=3)
        for r in arxiv_results:
            print(f"  - {r.title[:60]}... ({r.relevance_score:.2f})")
        
        print("\n=== Testing GitHub Search ===")
        github_results = await integrator.search_github("transformer", max_results=3)
        for r in github_results:
            print(f"  - {r.title} ({r.metadata.get('stars', 0)} stars)")
        
        print("\n=== Testing Integrated Search ===")
        integrated = await integrator.integrated_search(
            "deep learning",
            sources=["arxiv", "github"],
            max_results=5
        )
        print(f"Total results: {integrated['total_results']}")
        print(f"Unique results: {integrated['unique_results']}")
        print("\nTop results:")
        for r in integrated['ranked_results'][:3]:
            print(f"  - [{r['source']}] {r['title'][:50]}...")
        
        print("\n=== Search Statistics ===")
        print(json.dumps(integrator.get_stats(), indent=2))
        
    finally:
        await integrator.close()


if __name__ == "__main__":
    asyncio.run(demo())
