"""Node 10: Slack"""
import os, requests
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 10 - Slack", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SLACK_TOKEN = os.getenv("SLACK_TOKEN", "")

class SlackTools:
    def __init__(self):
        self.token = SLACK_TOKEN
        self.initialized = bool(self.token)
    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
    def get_tools(self):
        return [
            {"name": "send_message", "description": "发送 Slack 消息", "parameters": {"channel": "频道 ID", "text": "消息内容"}},
            {"name": "list_channels", "description": "列出频道", "parameters": {}}
        ]
    async def call_tool(self, tool, params):
        if not self.initialized: raise RuntimeError("Slack not initialized")
        return await getattr(self, f"_tool_{tool}")(params)
    async def _tool_send_message(self, params):
        try:
            r = requests.post("https://slack.com/api/chat.postMessage", headers=self._headers(), json={"channel": params.get("channel"), "text": params.get("text")}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}
    async def _tool_list_channels(self, params):
        try:
            r = requests.get("https://slack.com/api/conversations.list", headers=self._headers(), timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

tools = SlackTools()
@app.get("/health")
async def health():
    return {"status": "healthy" if tools.initialized else "degraded", "node_id": "10", "name": "Slack", "timestamp": datetime.now().isoformat()}
@app.get("/tools")
async def list_tools():
    return {"tools": tools.get_tools()}
@app.post("/mcp/call")
async def mcp_call(request: dict):
    try:
        return {"success": True, "result": await tools.call_tool(request.get("tool"), request.get("params", {}))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
