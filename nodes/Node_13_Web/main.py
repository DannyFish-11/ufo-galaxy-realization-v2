"""
Node 13: Web Operations
UFO Galaxy 64-Core MCP Matrix - Core Tool Node

Provides comprehensive web/HTTP operations:
- HTTP requests (GET, POST, PUT, DELETE, etc.)
- Web scraping and content extraction
- API interactions
- File downloads
- Session management
- Proxy support

Author: UFO Galaxy Team
Version: 5.0.0
"""

import os
import sys
import json
import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "13")
NODE_NAME = os.getenv("NODE_NAME", "WebOperations")
NODE_PORT = int(os.getenv("NODE_PORT", "8013"))
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/home/ubuntu/downloads")
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
MAX_DOWNLOAD_SIZE = int(os.getenv("MAX_DOWNLOAD_SIZE", str(500 * 1024 * 1024)))  # 500MB

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class HttpRequest(BaseModel):
    url: str
    method: HttpMethod = HttpMethod.GET
    headers: Optional[Dict[str, str]] = None
    params: Optional[Dict[str, str]] = None
    body: Optional[Union[str, Dict[str, Any]]] = None
    json_body: Optional[Dict[str, Any]] = None
    timeout: int = DEFAULT_TIMEOUT
    follow_redirects: bool = True
    verify_ssl: bool = True
    proxy: Optional[str] = None


class ScrapeRequest(BaseModel):
    url: str
    selectors: Optional[Dict[str, str]] = None  # name -> CSS selector
    extract_links: bool = False
    extract_images: bool = False
    extract_text: bool = True
    timeout: int = DEFAULT_TIMEOUT
    headers: Optional[Dict[str, str]] = None


class DownloadRequest(BaseModel):
    url: str
    output_path: Optional[str] = None
    filename: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: int = 300
    chunk_size: int = 8192


class ApiRequest(BaseModel):
    base_url: str
    endpoint: str
    method: HttpMethod = HttpMethod.GET
    headers: Optional[Dict[str, str]] = None
    params: Optional[Dict[str, str]] = None
    body: Optional[Dict[str, Any]] = None
    auth_type: Optional[str] = None  # bearer, basic, api_key
    auth_value: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT


class BatchRequest(BaseModel):
    requests: List[HttpRequest]
    concurrent_limit: int = 5


# =============================================================================
# Web Operations Service
# =============================================================================

class WebService:
    """Core web operations service."""
    
    def __init__(self, download_dir: str = DOWNLOAD_DIR):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, httpx.AsyncClient] = {}
        logger.info(f"WebService initialized with download dir: {self.download_dir}")
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Get default request headers."""
        return {
            "User-Agent": "UFO-Galaxy/5.0 (WebOperations Node)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate"
        }
    
    async def http_request(self, request: HttpRequest) -> Dict[str, Any]:
        """Execute HTTP request."""
        headers = self._get_default_headers()
        if request.headers:
            headers.update(request.headers)
        
        try:
            async with httpx.AsyncClient(
                timeout=request.timeout,
                follow_redirects=request.follow_redirects,
                verify=request.verify_ssl,
                proxy=request.proxy
            ) as client:
                
                # Prepare request kwargs
                kwargs = {
                    "headers": headers,
                    "params": request.params
                }
                
                if request.json_body:
                    kwargs["json"] = request.json_body
                elif request.body:
                    if isinstance(request.body, dict):
                        kwargs["json"] = request.body
                    else:
                        kwargs["content"] = request.body
                
                # Execute request
                response = await client.request(
                    request.method.value,
                    request.url,
                    **kwargs
                )
                
                # Parse response
                content_type = response.headers.get("content-type", "")
                
                if "application/json" in content_type:
                    try:
                        body = response.json()
                    except (json.JSONDecodeError, ValueError):
                        body = response.text
                else:
                    body = response.text
                
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": body,
                    "url": str(response.url),
                    "elapsed_ms": response.elapsed.total_seconds() * 1000
                }
                
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timeout",
                "url": request.url
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": str(e),
                "url": request.url
            }
        except Exception as e:
            logger.error(f"HTTP request error: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": request.url
            }
    
    async def scrape(self, request: ScrapeRequest) -> Dict[str, Any]:
        """Scrape web page content."""
        headers = self._get_default_headers()
        if request.headers:
            headers.update(request.headers)
        
        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                response = await client.get(request.url, headers=headers)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                result = {
                    "success": True,
                    "url": request.url,
                    "title": soup.title.string if soup.title else None,
                    "status_code": response.status_code
                }
                
                # Extract text content
                if request.extract_text:
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text(separator='\n', strip=True)
                    result["text"] = text[:50000]  # Limit text size
                
                # Extract by selectors
                if request.selectors:
                    result["extracted"] = {}
                    for name, selector in request.selectors.items():
                        elements = soup.select(selector)
                        result["extracted"][name] = [
                            el.get_text(strip=True) for el in elements
                        ]
                
                # Extract links
                if request.extract_links:
                    links = []
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if href.startswith(('http://', 'https://')):
                            links.append({
                                "url": href,
                                "text": a.get_text(strip=True)
                            })
                        elif href.startswith('/'):
                            links.append({
                                "url": urljoin(request.url, href),
                                "text": a.get_text(strip=True)
                            })
                    result["links"] = links[:500]  # Limit links
                
                # Extract images
                if request.extract_images:
                    images = []
                    for img in soup.find_all('img', src=True):
                        src = img['src']
                        if not src.startswith(('http://', 'https://')):
                            src = urljoin(request.url, src)
                        images.append({
                            "url": src,
                            "alt": img.get('alt', ''),
                            "title": img.get('title', '')
                        })
                    result["images"] = images[:200]  # Limit images
                
                return result
                
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}",
                "url": request.url
            }
        except Exception as e:
            logger.error(f"Scrape error: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": request.url
            }
    
    async def download(self, request: DownloadRequest) -> Dict[str, Any]:
        """Download file from URL."""
        headers = self._get_default_headers()
        if request.headers:
            headers.update(request.headers)
        
        # Determine output path
        if request.output_path:
            output_path = Path(request.output_path)
        else:
            # Extract filename from URL or use default
            if request.filename:
                filename = request.filename
            else:
                parsed = urlparse(request.url)
                filename = Path(parsed.path).name or "download"
            output_path = self.download_dir / filename
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                async with client.stream("GET", request.url, headers=headers) as response:
                    response.raise_for_status()
                    
                    # Check content length
                    content_length = int(response.headers.get("content-length", 0))
                    if content_length > MAX_DOWNLOAD_SIZE:
                        return {
                            "success": False,
                            "error": f"File too large: {content_length} bytes",
                            "url": request.url
                        }
                    
                    # Download file
                    downloaded = 0
                    with open(output_path, 'wb') as f:
                        async for chunk in response.aiter_bytes(request.chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if downloaded > MAX_DOWNLOAD_SIZE:
                                return {
                                    "success": False,
                                    "error": "Download size exceeded limit",
                                    "url": request.url
                                }
                    
                    return {
                        "success": True,
                        "url": request.url,
                        "output_path": str(output_path),
                        "size": downloaded,
                        "content_type": response.headers.get("content-type")
                    }
                    
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}",
                "url": request.url
            }
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": request.url
            }
    
    async def api_request(self, request: ApiRequest) -> Dict[str, Any]:
        """Execute API request with authentication."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        if request.headers:
            headers.update(request.headers)
        
        # Add authentication
        if request.auth_type and request.auth_value:
            if request.auth_type == "bearer":
                headers["Authorization"] = f"Bearer {request.auth_value}"
            elif request.auth_type == "basic":
                import base64
                encoded = base64.b64encode(request.auth_value.encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            elif request.auth_type == "api_key":
                headers["X-API-Key"] = request.auth_value
        
        # Build URL
        url = urljoin(request.base_url.rstrip('/') + '/', request.endpoint.lstrip('/'))
        
        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                kwargs = {
                    "headers": headers,
                    "params": request.params
                }
                
                if request.body:
                    kwargs["json"] = request.body
                
                response = await client.request(
                    request.method.value,
                    url,
                    **kwargs
                )
                
                try:
                    body = response.json()
                except (json.JSONDecodeError, ValueError):
                    body = response.text

                return {
                    "success": response.is_success,
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": body,
                    "url": str(response.url)
                }
                
        except Exception as e:
            logger.error(f"API request error: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url
            }
    
    async def batch_request(self, request: BatchRequest) -> Dict[str, Any]:
        """Execute multiple HTTP requests concurrently."""
        semaphore = asyncio.Semaphore(request.concurrent_limit)
        
        async def limited_request(req: HttpRequest) -> Dict[str, Any]:
            async with semaphore:
                return await self.http_request(req)
        
        tasks = [limited_request(req) for req in request.requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "success": False,
                    "error": str(result),
                    "url": request.requests[i].url
                })
            else:
                processed_results.append(result)
        
        success_count = sum(1 for r in processed_results if r.get("success"))
        
        return {
            "success": True,
            "total": len(results),
            "successful": success_count,
            "failed": len(results) - success_count,
            "results": processed_results
        }


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title=f"Node {NODE_ID}: {NODE_NAME}",
    description="Web operations service for UFO Galaxy",
    version="5.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

web_service = WebService()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/request")
async def http_request(request: HttpRequest):
    """Execute HTTP request."""
    return await web_service.http_request(request)


@app.post("/get")
async def http_get(url: str, params: Optional[Dict[str, str]] = None):
    """Simple GET request."""
    request = HttpRequest(url=url, method=HttpMethod.GET, params=params)
    return await web_service.http_request(request)


@app.post("/post")
async def http_post(url: str, body: Optional[Dict[str, Any]] = None):
    """Simple POST request."""
    request = HttpRequest(url=url, method=HttpMethod.POST, json_body=body)
    return await web_service.http_request(request)


@app.post("/scrape")
async def scrape_page(request: ScrapeRequest):
    """Scrape web page content."""
    return await web_service.scrape(request)


@app.post("/download")
async def download_file(request: DownloadRequest):
    """Download file from URL."""
    return await web_service.download(request)


@app.post("/api")
async def api_request(request: ApiRequest):
    """Execute API request."""
    return await web_service.api_request(request)


@app.post("/batch")
async def batch_request(request: BatchRequest):
    """Execute batch HTTP requests."""
    return await web_service.batch_request(request)


@app.get("/parse-url")
async def parse_url(url: str):
    """Parse URL components."""
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "netloc": parsed.netloc,
        "path": parsed.path,
        "params": parsed.params,
        "query": parsed.query,
        "fragment": parsed.fragment,
        "hostname": parsed.hostname,
        "port": parsed.port
    }


if __name__ == "__main__":
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME} on port {NODE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)
