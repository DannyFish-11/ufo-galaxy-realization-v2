"""
Node 21: Notion
====================
Notion API 集成

依赖库: requests
工具: create_page, query_database, update_page
"""

import os
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 21 - Notion", version="1.0.0")

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

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# =============================================================================
# Tool Implementation
# =============================================================================

class NotionTools:
    """
    Notion 工具实现
    """
    
    def __init__(self):
        self.api_key = NOTION_API_KEY
        self.base_url = NOTION_BASE_URL
        self.version = NOTION_VERSION
        self.initialized = bool(self.api_key)
        
        if not self.initialized:
            print("Warning: NOTION_API_KEY not set")
        
    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": self.version
        }
        
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        return [
            {
                "name": "create_page",
                "description": "在 Notion 数据库中创建新页面",
                "parameters": {
                    "database_id": "数据库 ID",
                    "title": "页面标题",
                    "properties": "页面属性 (JSON 格式)"
                }
            },
            {
                "name": "query_database",
                "description": "查询 Notion 数据库",
                "parameters": {
                    "database_id": "数据库 ID",
                    "filter": "过滤条件 (JSON 格式, 可选)",
                    "sorts": "排序条件 (JSON 格式, 可选)"
                }
            },
            {
                "name": "update_page",
                "description": "更新 Notion 页面",
                "parameters": {
                    "page_id": "页面 ID",
                    "properties": "要更新的属性 (JSON 格式)"
                }
            },
            {
                "name": "get_page",
                "description": "获取 Notion 页面详情",
                "parameters": {
                    "page_id": "页面 ID"
                }
            }
        ]
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self.initialized:
            raise RuntimeError("Notion API not initialized (missing API key)")
            
        handler = getattr(self, f"_tool_{tool}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool}")
            
        return await handler(params)
        
    async def _tool_create_page(self, params: dict) -> dict:
        """创建页面"""
        database_id = params.get("database_id", "")
        title = params.get("title", "")
        properties = params.get("properties", {})
        
        if not database_id:
            return {"error": "数据库 ID 不能为空"}
        
        try:
            url = f"{self.base_url}/pages"
            
            # 构建页面数据
            page_data = {
                "parent": {"database_id": database_id},
                "properties": {
                    "title": {
                        "title": [
                            {
                                "text": {
                                    "content": title
                                }
                            }
                        ]
                    }
                }
            }
            
            # 合并自定义属性
            if isinstance(properties, dict):
                page_data["properties"].update(properties)
            
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=page_data,
                timeout=15
            )
            
            response.raise_for_status()
            data = response.json()
            
            return {
                "success": True,
                "page_id": data["id"],
                "url": data["url"],
                "created_time": data["created_time"]
            }
            
        except requests.exceptions.HTTPError as e:
            return {"error": f"API 错误: {e.response.status_code} - {e.response.text}"}
        except Exception as e:
            return {"error": f"创建页面失败: {str(e)}"}
    
    async def _tool_query_database(self, params: dict) -> dict:
        """查询数据库"""
        database_id = params.get("database_id", "")
        filter_obj = params.get("filter", None)
        sorts = params.get("sorts", None)
        
        if not database_id:
            return {"error": "数据库 ID 不能为空"}
        
        try:
            url = f"{self.base_url}/databases/{database_id}/query"
            
            query_data = {}
            if filter_obj:
                query_data["filter"] = filter_obj
            if sorts:
                query_data["sorts"] = sorts
            
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=query_data,
                timeout=15
            )
            
            response.raise_for_status()
            data = response.json()
            
            # 解析结果
            results = []
            for item in data.get("results", []):
                results.append({
                    "id": item["id"],
                    "url": item["url"],
                    "created_time": item["created_time"],
                    "last_edited_time": item["last_edited_time"],
                    "properties": item.get("properties", {})
                })
            
            return {
                "success": True,
                "results_count": len(results),
                "results": results,
                "has_more": data.get("has_more", False)
            }
            
        except requests.exceptions.HTTPError as e:
            return {"error": f"API 错误: {e.response.status_code} - {e.response.text}"}
        except Exception as e:
            return {"error": f"查询数据库失败: {str(e)}"}
    
    async def _tool_update_page(self, params: dict) -> dict:
        """更新页面"""
        page_id = params.get("page_id", "")
        properties = params.get("properties", {})
        
        if not page_id:
            return {"error": "页面 ID 不能为空"}
        
        try:
            url = f"{self.base_url}/pages/{page_id}"
            
            update_data = {
                "properties": properties
            }
            
            response = requests.patch(
                url,
                headers=self._get_headers(),
                json=update_data,
                timeout=15
            )
            
            response.raise_for_status()
            data = response.json()
            
            return {
                "success": True,
                "page_id": data["id"],
                "last_edited_time": data["last_edited_time"]
            }
            
        except requests.exceptions.HTTPError as e:
            return {"error": f"API 错误: {e.response.status_code} - {e.response.text}"}
        except Exception as e:
            return {"error": f"更新页面失败: {str(e)}"}
    
    async def _tool_get_page(self, params: dict) -> dict:
        """获取页面"""
        page_id = params.get("page_id", "")
        
        if not page_id:
            return {"error": "页面 ID 不能为空"}
        
        try:
            url = f"{self.base_url}/pages/{page_id}"
            
            response = requests.get(
                url,
                headers=self._get_headers(),
                timeout=15
            )
            
            response.raise_for_status()
            data = response.json()
            
            return {
                "success": True,
                "page_id": data["id"],
                "url": data["url"],
                "created_time": data["created_time"],
                "last_edited_time": data["last_edited_time"],
                "properties": data.get("properties", {})
            }
            
        except requests.exceptions.HTTPError as e:
            return {"error": f"API 错误: {e.response.status_code} - {e.response.text}"}
        except Exception as e:
            return {"error": f"获取页面失败: {str(e)}"}


# =============================================================================
# Global Instance
# =============================================================================

tools = NotionTools()

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "21",
        "name": "Notion",
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
    uvicorn.run(app, host="0.0.0.0", port=8021)
