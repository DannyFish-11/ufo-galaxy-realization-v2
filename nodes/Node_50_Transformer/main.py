"""
Node 50: Transformer - 真实的自然语言理解 (NLU)
=============================================
使用 LLM 进行真正的自然语言理解。
支持意图识别、实体提取、任务分解、对话管理。
"""
import os
import json
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 50 - Transformer NLU", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# API 配置
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ONEAPI_BASE_URL = os.getenv("ONEAPI_BASE_URL", "http://localhost:8001/v1")
ONEAPI_API_KEY = os.getenv("ONEAPI_API_KEY", "")

# ============ 请求模型 ============
class NLURequest(BaseModel):
    text: str
    context: Optional[List[Dict[str, str]]] = None

class TaskRequest(BaseModel):
    text: str
    available_tools: Optional[List[str]] = None

class DialogRequest(BaseModel):
    user_input: str
    history: Optional[List[Dict[str, str]]] = None
    system_prompt: Optional[str] = None

# ============ LLM 调用 ============
def call_llm(messages: List[Dict], max_tokens: int = 1000) -> Optional[str]:
    """调用 LLM，按优先级尝试多个提供商"""
    
    # Groq (最快)
    if GROQ_API_KEY:
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": max_tokens},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
        except: pass
    
    # 智谱 (中文好)
    if ZHIPU_API_KEY:
        try:
            response = requests.post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers={"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"},
                json={"model": "glm-4-flash", "messages": messages, "max_tokens": max_tokens},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
        except: pass
    
    # OpenRouter
    if OPENROUTER_API_KEY:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={"model": "openai/gpt-3.5-turbo", "messages": messages, "max_tokens": max_tokens},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
        except: pass
    
    # OneAPI (本地)
    if ONEAPI_API_KEY:
        try:
            response = requests.post(
                f"{ONEAPI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ONEAPI_API_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-3.5-turbo", "messages": messages, "max_tokens": max_tokens},
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
        except: pass
    
    return None

def parse_json_response(result: str) -> Dict:
    """解析 LLM 返回的 JSON"""
    try:
        if "```json" in result:
            json_str = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_str = result.split("```")[1].split("```")[0]
        else:
            json_str = result
        return json.loads(json_str.strip())
    except:
        return None

# ============ NLU 功能 ============
class NLUTools:
    def __init__(self):
        self.initialized = bool(GROQ_API_KEY or ZHIPU_API_KEY or OPENROUTER_API_KEY or ONEAPI_API_KEY)
    
    def understand(self, text: str, context: Optional[List[Dict]] = None) -> Dict:
        """理解用户输入，提取意图和实体"""
        system_prompt = """分析用户输入，返回 JSON:
{"intent": "query/command/chat/unknown", "intent_confidence": 0.0-1.0, "entities": [{"type": "类型", "value": "值"}], "sentiment": "positive/negative/neutral", "summary": "一句话总结"}"""
        
        messages = [{"role": "system", "content": system_prompt}]
        if context: messages.extend(context)
        messages.append({"role": "user", "content": text})
        
        result = call_llm(messages)
        if not result:
            return {"error": "LLM not available", "fallback": True, "intent": "unknown", "entities": [], "summary": text}
        
        parsed = parse_json_response(result)
        if parsed:
            parsed["success"] = True
            parsed["raw_text"] = text
            return parsed
        return {"success": True, "intent": "unknown", "entities": [], "summary": result, "raw_text": text}
    
    def decompose_task(self, text: str, available_tools: Optional[List[str]] = None) -> Dict:
        """将复杂任务分解为可执行步骤"""
        tools_str = ", ".join(available_tools) if available_tools else "click, type, search, screenshot, open_app, send_message, get_weather, generate_video"
        
        system_prompt = f"""将任务分解为步骤。可用工具: {tools_str}
返回 JSON: {{"task_summary": "总结", "steps": [{{"step_id": 1, "action": "工具", "params": {{}}, "description": "描述"}}], "complexity": "low/medium/high"}}"""
        
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]
        
        result = call_llm(messages, max_tokens=2000)
        if not result:
            return {"error": "LLM not available", "fallback": True, "steps": [{"step_id": 1, "action": "manual", "description": text}]}
        
        parsed = parse_json_response(result)
        if parsed:
            parsed["success"] = True
            return parsed
        return {"success": True, "task_summary": text, "steps": [{"step_id": 1, "action": "manual", "description": result}]}
    
    def dialog(self, user_input: str, history: Optional[List[Dict]] = None, system_prompt: Optional[str] = None) -> Dict:
        """对话管理"""
        default_system = "你是 UFO³ Galaxy 智能助手，可以控制电脑手机、搜索信息、生成内容、执行自动化任务。简洁友好地回复。"
        
        messages = [{"role": "system", "content": system_prompt or default_system}]
        if history: messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        
        result = call_llm(messages)
        if not result:
            return {"error": "LLM not available", "response": "抱歉，我暂时无法回复。"}
        
        return {"success": True, "response": result, "user_input": user_input, "timestamp": datetime.now().isoformat()}
    
    def extract_command(self, text: str) -> Dict:
        """从自然语言提取可执行命令"""
        system_prompt = """提取命令，返回 JSON:
{"has_command": true/false, "command_type": "ui_action/search/generate/system/chat", "action": "动作", "target": "目标", "params": {}, "confidence": 0.0-1.0}"""
        
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]
        
        result = call_llm(messages)
        if not result:
            return {"has_command": False, "command_type": "chat", "error": "LLM not available"}
        
        parsed = parse_json_response(result)
        if parsed:
            parsed["success"] = True
            return parsed
        return {"success": True, "has_command": False, "command_type": "chat", "raw_response": result}
    
    def get_tools(self):
        return [
            {"name": "understand", "description": "理解用户输入，提取意图和实体", "parameters": {"text": "用户输入", "context": "上下文(可选)"}},
            {"name": "decompose", "description": "将复杂任务分解为可执行步骤", "parameters": {"text": "任务描述", "available_tools": "可用工具列表(可选)"}},
            {"name": "dialog", "description": "对话管理", "parameters": {"user_input": "用户输入", "history": "对话历史(可选)", "system_prompt": "系统提示(可选)"}},
            {"name": "extract_command", "description": "从自然语言提取可执行命令", "parameters": {"text": "用户输入"}}
        ]
    
    async def call_tool(self, tool: str, params: dict):
        if tool == "understand": return self.understand(params.get("text", ""), params.get("context"))
        elif tool == "decompose": return self.decompose_task(params.get("text", ""), params.get("available_tools"))
        elif tool == "dialog": return self.dialog(params.get("user_input", ""), params.get("history"), params.get("system_prompt"))
        elif tool == "extract_command": return self.extract_command(params.get("text", ""))
        elif tool == "extract_intent": return self.understand(params.get("text", ""))
        elif tool == "extract_entities": return self.understand(params.get("text", ""))
        return {"error": f"Unknown tool: {tool}"}

tools = NLUTools()

# ============ API 端点 ============
@app.get("/health")
async def health():
    return {
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "50",
        "name": "Transformer NLU",
        "llm_available": tools.initialized,
        "providers": {"groq": bool(GROQ_API_KEY), "zhipu": bool(ZHIPU_API_KEY), "openrouter": bool(OPENROUTER_API_KEY), "oneapi": bool(ONEAPI_API_KEY)},
        "timestamp": datetime.now().isoformat()
    }

@app.get("/tools")
async def list_tools():
    return {"tools": tools.get_tools()}

@app.post("/understand")
async def api_understand(request: NLURequest):
    result = tools.understand(request.text, request.context)
    if "error" in result and not result.get("fallback"): raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/decompose")
async def api_decompose(request: TaskRequest):
    result = tools.decompose_task(request.text, request.available_tools)
    if "error" in result and not result.get("fallback"): raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/dialog")
async def api_dialog(request: DialogRequest):
    result = tools.dialog(request.user_input, request.history, request.system_prompt)
    if "error" in result and "response" not in result: raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/extract_command")
async def api_extract_command(request: NLURequest):
    return tools.extract_command(request.text)

@app.post("/mcp/call")
async def mcp_call(request: dict):
    try:
        result = await tools.call_tool(request.get("tool"), request.get("params", {}))
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
