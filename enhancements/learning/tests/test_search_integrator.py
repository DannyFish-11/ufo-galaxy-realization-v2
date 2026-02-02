#!/usr/bin/env python3
"""
Unit tests for Search Integrator
"""

import asyncio
import unittest
from datetime import datetime

import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning')

from search_integrator import (
    SearchSource,
    SearchResult,
    SearchQuery,
    RateLimiter,
    ResultCache,
    SearchIntegrator
)


class TestSearchSource(unittest.TestCase):
    """Test SearchSource enumeration."""
    
    def test_search_sources(self):
        """Test all search sources exist."""
        sources = list(SearchSource)
        self.assertEqual(len(sources), 3)
        
        self.assertIn(SearchSource.WEB, sources)
        self.assertIn(SearchSource.ARXIV, sources)
        self.assertIn(SearchSource.GITHUB, sources)
    
    def test_source_values(self):
        """Test source values."""
        self.assertEqual(SearchSource.WEB.value, "web")
        self.assertEqual(SearchSource.ARXIV.value, "arxiv")
        self.assertEqual(SearchSource.GITHUB.value, "github")


class TestSearchResult(unittest.TestCase):
    """Test SearchResult dataclass."""
    
    def test_result_creation(self):
        """Test creating a search result."""
        result = SearchResult(
            id="r1",
            source=SearchSource.WEB,
            title="Test Result",
            content="Test content",
            url="https://example.com",
            author="Test Author",
            relevance_score=0.85
        )
        
        self.assertEqual(result.source, SearchSource.WEB)
        self.assertEqual(result.title, "Test Result")
        self.assertEqual(result.relevance_score, 0.85)
    
    def test_result_auto_id(self):
        """Test automatic ID generation."""
        result = SearchResult(
            id="",
            source=SearchSource.ARXIV,
            title="Test Paper",
            content="Abstract here",
            url="https://arxiv.org/abs/1234"
        )
        
        self.assertIsNotNone(result.id)
        self.assertEqual(len(result.id), 16)
    
    def test_result_to_dict(self):
        """Test result serialization."""
        result = SearchResult(
            id="r1",
            source=SearchSource.GITHUB,
            title="Test Repo",
            content="Description",
            url="https://github.com/test/repo",
            metadata={'stars': 100}
        )
        
        data = result.to_dict()
        self.assertEqual(data['id'], "r1")
        self.assertEqual(data['source'], "github")
        self.assertEqual(data['metadata']['stars'], 100)


class TestSearchQuery(unittest.TestCase):
    """Test SearchQuery dataclass."""
    
    def test_query_creation(self):
        """Test creating a search query."""
        query = SearchQuery(
            query="machine learning",
            sources=[SearchSource.WEB, SearchSource.ARXIV],
            max_results=10,
            sort_by="relevance"
        )
        
        self.assertEqual(query.query, "machine learning")
        self.assertEqual(len(query.sources), 2)
        self.assertEqual(query.max_results, 10)


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter class."""
    
    def test_initialization(self):
        """Test rate limiter initialization."""
        limiter = RateLimiter(calls_per_minute=60)
        self.assertEqual(limiter.calls_per_minute, 60)
        self.assertEqual(limiter.min_interval, 1.0)  # 60/60
    
    def test_custom_rate(self):
        """Test custom rate limit."""
        limiter = RateLimiter(calls_per_minute=120)
        self.assertEqual(limiter.min_interval, 0.5)  # 60/120


class TestResultCache(unittest.TestCase):
    """Test ResultCache class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = ResultCache(ttl_seconds=3600)
    
    def test_cache_set_and_get(self):
        """Test cache set and get operations."""
        results = [
            SearchResult(id="r1", source=SearchSource.WEB, title="T1", 
                        content="C1", url="U1", relevance_score=0.9)
        ]
        
        self.cache.set("query1", "web", results)
        cached = self.cache.get("query1", "web")
        
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].id, "r1")
    
    def test_cache_miss(self):
        """Test cache miss."""
        cached = self.cache.get("nonexistent", "web")
        self.assertIsNone(cached)
    
    def test_cache_expiration(self):
        """Test cache expiration."""
        # Create cache with very short TTL
        short_cache = ResultCache(ttl_seconds=0)
        
        results = [
            SearchResult(id="r1", source=SearchSource.WEB, title="T1", 
                        content="C1", url="U1")
        ]
        
        short_cache.set("query", "web", results)
        
        # Should be expired immediately
        cached = short_cache.get("query", "web")
        self.assertIsNone(cached)
    
    def test_cache_clear(self):
        """Test cache clearing."""
        results = [
            SearchResult(id="r1", source=SearchSource.WEB, title="T1", 
                        content="C1", url="U1")
        ]
        
        self.cache.set("query", "web", results)
        self.cache.clear()
        
        cached = self.cache.get("query", "web")
        self.assertIsNone(cached)


class TestSearchIntegrator(unittest.TestCase):
    """Test SearchIntegrator class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.integrator = SearchIntegrator(
            cache_ttl=3600,
            rate_limit_per_minute=60
        )
    
    def tearDown(self):
        """Clean up after tests."""
        async def cleanup():
            await self.integrator.close()
        asyncio.run(cleanup())
    
    def test_initialization(self):
        """Test integrator initialization."""
        self.assertIsNotNone(self.integrator.cache)
        self.assertIsNotNone(self.integrator.rate_limiter)
    
    def test_web_search_simulation(self):
        """Test web search (simulated)."""
        async def test():
            results = await self.integrator.search_web("test query", max_results=3)
            
            self.assertIsInstance(results, list)
            self.assertLessEqual(len(results), 3)
            
            if results:
                self.assertEqual(results[0].source, SearchSource.WEB)
                self.assertIsNotNone(results[0].title)
        
        asyncio.run(test())
    
    def test_cache_hit(self):
        """Test cache hit on repeated search."""
        async def test():
            # First search
            results1 = await self.integrator.search_web("cached_query", max_results=2)
            
            # Second search - should hit cache
            results2 = await self.integrator.search_web("cached_query", max_results=2)
            
            stats = self.integrator.get_stats()
            self.assertEqual(stats['cache_hits'], 1)
        
        asyncio.run(test())
    
    def test_rank_results(self):
        """Test result ranking."""
        results = [
            SearchResult(id="r1", source=SearchSource.WEB, title="A", 
                        content="C", url="U1", relevance_score=0.5),
            SearchResult(id="r2", source=SearchSource.ARXIV, title="B", 
                        content="C", url="U2", relevance_score=0.9),
            SearchResult(id="r3", source=SearchSource.GITHUB, title="C", 
                        content="C", url="U3", relevance_score=0.7),
        ]
        
        ranked = self.integrator._rank_results(results)
        
        # Should be sorted by relevance
        self.assertEqual(ranked[0].id, "r2")  # Highest score
        self.assertEqual(ranked[1].id, "r3")
        self.assertEqual(ranked[2].id, "r1")
    
    def test_rank_results_deduplication(self):
        """Test result deduplication."""
        results = [
            SearchResult(id="r1", source=SearchSource.WEB, title="A", 
                        content="C", url="https://example.com", relevance_score=0.5),
            SearchResult(id="r2", source=SearchSource.ARXIV, title="B", 
                        content="C", url="https://example.com", relevance_score=0.9),
        ]
        
        ranked = self.integrator._rank_results(results)
        
        # Should deduplicate by URL
        self.assertEqual(len(ranked), 1)
    
    def test_get_stats(self):
        """Test statistics retrieval."""
        stats = self.integrator.get_stats()
        
        self.assertIn('total_searches', stats)
        self.assertIn('cache_hits', stats)
        self.assertIn('api_calls', stats)
        self.assertIn('errors', stats)
    
    def test_clear_cache(self):
        """Test cache clearing."""
        async def test():
            # Add something to cache
            results = await self.integrator.search_web("test", max_results=1)
            
            # Clear cache
            self.integrator.clear_cache()
            
            # Verify cache is empty
            cached = self.integrator.cache.get("test", "web")
            self.assertIsNone(cached)
        
        asyncio.run(test())


class TestArxivParsing(unittest.TestCase):
    """Test ArXiv response parsing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.integrator = SearchIntegrator()
    
    def tearDown(self):
        """Clean up after tests."""
        async def cleanup():
            await self.integrator.close()
        asyncio.run(cleanup())
    
    def test_parse_arxiv_response(self):
        """Test ArXiv XML parsing."""
        # Sample ArXiv response
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <title>Test Paper Title</title>
                <summary>Test abstract for the paper.</summary>
                <id>http://arxiv.org/abs/1234.5678</id>
                <published>2024-01-15T00:00:00Z</published>
                <author><name>John Doe</name></author>
                <author><name>Jane Smith</name></author>
            </entry>
        </feed>"""
        
        results = self.integrator._parse_arxiv_response(xml_content)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Test Paper Title")
        self.assertEqual(results[0].source, SearchSource.ARXIV)
        self.assertEqual(results[0].author, "John Doe, Jane Smith")


class TestGitHubParsing(unittest.TestCase):
    """Test GitHub response parsing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.integrator = SearchIntegrator()
    
    def tearDown(self):
        """Clean up after tests."""
        async def cleanup():
            await self.integrator.close()
        asyncio.run(cleanup())
    
    def test_parse_github_repositories(self):
        """Test GitHub repository response parsing."""
        response_data = {
            'items': [
                {
                    'full_name': 'user/repo1',
                    'description': 'Test repository',
                    'html_url': 'https://github.com/user/repo1',
                    'stargazers_count': 100,
                    'language': 'Python',
                    'forks_count': 20,
                    'created_at': '2023-01-01T00:00:00Z',
                    'owner': {'login': 'user'}
                }
            ]
        }
        
        results = self.integrator._parse_github_response(response_data, "repositories")
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, 'user/repo1')
        self.assertEqual(results[0].metadata['stars'], 100)
        self.assertEqual(results[0].metadata['language'], 'Python')


class TestIntegration(unittest.TestCase):
    """Integration tests for search functionality."""
    
    def test_integrated_search(self):
        """Test integrated search across sources."""
        integrator = SearchIntegrator()
        
        async def test():
            results = await integrator.integrated_search(
                query="machine learning",
                sources=["web"],
                max_results=3
            )
            
            self.assertIn('query', results)
            self.assertIn('total_results', results)
            self.assertIn('by_source', results)
            self.assertIn('ranked_results', results)
            
            await integrator.close()
        
        asyncio.run(test())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSearchSource))
    suite.addTests(loader.loadTestsFromTestCase(TestSearchResult))
    suite.addTests(loader.loadTestsFromTestCase(TestSearchQuery))
    suite.addTests(loader.loadTestsFromTestCase(TestRateLimiter))
    suite.addTests(loader.loadTestsFromTestCase(TestResultCache))
    suite.addTests(loader.loadTestsFromTestCase(TestSearchIntegrator))
    suite.addTests(loader.loadTestsFromTestCase(TestArxivParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestGitHubParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
