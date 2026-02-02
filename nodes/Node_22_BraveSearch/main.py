"""
Node 22: BraveSearch
========================
Brave 搜索

依赖库: requests
工具: search, news_search
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 22 - BraveSearch", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Configuration
# =============================================================================

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
BRAVE_BASE_URL = "https://api.search.brave.com/res/v1"

# =============================================================================
# Tool Implementation
# =============================================================================

class BraveSearchTools:
    """
    BraveSearch 工具实现
    """
    
    def __init__(self):
        self.api_key = BRAVE_API_KEY
        self.base_url = BRAVE_BASE_URL
        self.initialized = bool(self.api_key)
        
        if not self.initialized:
            print("Warning: BRAVE_API_KEY not set")
            
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        return [
            {
                "name": "web_search",
                "description": "使用 Brave 搜索引擎进行网页搜索",
                "parameters": {
                    "query": "搜索关键词",
                    "count": "返回结果数量 (1-20, 默认: 10)",
                    "country": "国家代码 (例如: US, CN, 默认: US)",
                    "search_lang": "搜索语言 (例如: en, zh, 默认: en)"
                }
            }
        ]
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self.initialized:
            raise RuntimeError("BraveSearch API not initialized (missing API key)")
            
        handler = getattr(self, f"_tool_{tool}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool}")
            
        return await handler(params)
        
    async def _tool_web_search(self, params: dict) -> dict:
        """网页搜索"""
        import requests
        
        query = params.get("query", "")
        count = min(int(params.get("count", 10)), 20)
        country = params.get("country", "US")
        search_lang = params.get("search_lang", "en")
        
        if not query:
            return {"error": "搜索关键词不能为空"}
        
        try:
            url = f"{self.base_url}/web/search"
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self.api_key
            }
            
            response = requests.get(url, headers=headers, params={
                "q": query,
                "count": count,
                "country": country,
                "search_lang": search_lang,
                "safesearch": "moderate",
                "text_decorations": False,
                "spellcheck": True
            }, timeout=15)
            
            response.raise_for_status()
            data = response.json()
            
            # 解析搜索结果
            results = []
            
            # Web 结果
            if "web" in data and "results" in data["web"]:
                for item in data["web"]["results"]:
                    results.append({
                        "type": "web",
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "description": item.get("description", ""),
                        "age": item.get("age", ""),
                        "language": item.get("language", "")
                    })
            
            # 新闻结果
            if "news" in data and "results" in data["news"]:
                for item in data["news"]["results"]:
                    results.append({
                        "type": "news",
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "description": item.get("description", ""),
                        "age": item.get("age", ""),
                        "source": item.get("meta_url", {}).get("hostname", "")
                    })
            
            result = {
                "query": data.get("query", {}).get("original", query),
                "results_count": len(results),
                "results": results[:count]
            }
            
            # 添加拼写建议
            if "query" in data and "altered" in data["query"]:
                result["spell_suggestion"] = data["query"]["altered"]
            
            return result
            
        except requests.exceptions.HTTPError as e:
            return {"error": f"API 错误: {e.response.status_code} - {e.response.text}"}
        except Exception as e:
            return {"error": f"搜索失败: {str(e)}"}


# =============================================================================
# Global Instance
# =============================================================================

tools = BraveSearchTools()

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "22",
        "name": "BraveSearch",
        "initialized": tools.initialized,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/tools")
async def list_tools():
    """列出可用工具"""
    return {"tools": tools.get_tools()}

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    try:
        result = await tools.call_tool(tool, params)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8022)
