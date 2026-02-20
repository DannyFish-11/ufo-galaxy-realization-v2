"""
Node 01: OneAPI Gateway - 真实可用的多模型 AI 网关
================================================
支持: OpenRouter, 智谱AI, Groq, Claude, OpenWeather, BraveSearch

所有 API 都经过实际测试验证可用。
"""
import os
import time
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 01 - OneAPI Gateway", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ============ API 配置 (从环境变量读取) ============
# 云端 LLM 提供商
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
PIXVERSE_API_KEY = os.getenv("PIXVERSE_API_KEY", "")

# 本地 LLM 配置 (Node 79)
LOCAL_LLM_ENABLED = os.getenv("LOCAL_LLM_ENABLED", "true").lower() == "true"
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:8079")
LOCAL_LLM_PRIORITY = int(os.getenv("LOCAL_LLM_PRIORITY", "1"))  # 1=最高优先级

# 其他工具 API
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# ============ 请求模型 ============
class ChatRequest(BaseModel):
    model: str = "auto"
    messages: List[Dict[str, str]]
    max_tokens: int = 1000
    temperature: float = 0.7

class SearchRequest(BaseModel):
    query: str
    count: int = 10

class WeatherRequest(BaseModel):
    city: str
    units: str = "metric"

# ============ LLM 提供商实现 ============
def call_openrouter(messages: List[Dict], model: str = "openai/gpt-3.5-turbo", max_tokens: int = 1000) -> Dict:
    """OpenRouter API - 已验证可用"""
    if not OPENROUTER_API_KEY:
        return {"error": "OPENROUTER_API_KEY not configured"}
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "openrouter",
            "model": model,
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {})
        }
    except Exception as e:
        return {"error": str(e), "provider": "openrouter"}

def call_zhipu(messages: List[Dict], model: str = "glm-4-flash", max_tokens: int = 1000) -> Dict:
    """智谱 AI API - 已验证可用"""
    if not ZHIPU_API_KEY:
        return {"error": "ZHIPU_API_KEY not configured"}
    
    try:
        response = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={
                "Authorization": f"Bearer {ZHIPU_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "zhipu",
            "model": model,
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {})
        }
    except Exception as e:
        return {"error": str(e), "provider": "zhipu"}

def call_groq(messages: List[Dict], model: str = "llama-3.3-70b-versatile", max_tokens: int = 1000) -> Dict:
    """Groq API - 已验证可用 (注意: llama3-8b-8192 已停用，使用 llama-3.3-70b-versatile)"""
    if not GROQ_API_KEY:
        return {"error": "GROQ_API_KEY not configured"}
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "groq",
            "model": model,
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {})
        }
    except Exception as e:
        return {"error": str(e), "provider": "groq"}

def call_local_llm(messages: List[Dict], model: str = "qwen2.5:7b-instruct-q4_K_M", max_tokens: int = 1000, temperature: float = 0.7) -> Dict:
    """本地 LLM API (通过 Node 79)"""
    if not LOCAL_LLM_ENABLED:
        return {"error": "Local LLM not enabled"}
    
    try:
        # 调用 Node 79 的 OpenAI 兼容 API
        response = requests.post(
            f"{LOCAL_LLM_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            },
            timeout=120  # 本地推理可能较慢
        )
        response.raise_for_status()
        data = response.json()
        
        return {
            "success": True,
            "provider": "local",
            "model": data.get("model", model),
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "cost": 0  # 本地推理无成本
        }
    except Exception as e:
        return {"error": str(e), "provider": "local"}

def call_together(messages: List[Dict], model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo", max_tokens: int = 1000) -> Dict:
    """Together AI API - 支持多种开源模型"""
    if not TOGETHER_API_KEY:
        return {"error": "TOGETHER_API_KEY not configured"}
    
    try:
        response = requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {TOGETHER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "together",
            "model": model,
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {})
        }
    except Exception as e:
        return {"error": str(e), "provider": "together"}

def call_perplexity(messages: List[Dict], model: str = "sonar-pro", max_tokens: int = 1000) -> Dict:
    """Perplexity API - 实时搜索增强的 LLM"""
    if not PERPLEXITY_API_KEY:
        return {"error": "PERPLEXITY_API_KEY not configured"}
    
    try:
        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "perplexity",
            "model": model,
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "citations": data.get("citations", [])  # Perplexity 提供来源引用
        }
    except Exception as e:
        return {"error": str(e), "provider": "perplexity"}

def call_pixverse(prompt: str, image_url: Optional[str] = None) -> Dict:
    """Pixverse API - 视频生成"""
    if not PIXVERSE_API_KEY:
        return {"error": "PIXVERSE_API_KEY not configured"}
    
    try:
        payload = {"prompt": prompt}
        if image_url:
            payload["image_url"] = image_url
        
        response = requests.post(
            "https://api.pixverse.ai/v1/generate",
            headers={
                "Authorization": f"Bearer {PIXVERSE_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=120  # 视频生成需要更长时间
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "pixverse",
            "video_url": data.get("video_url"),
            "task_id": data.get("task_id"),
            "status": data.get("status")
        }
    except Exception as e:
        return {"error": str(e), "provider": "pixverse"}

def call_claude(messages: List[Dict], model: str = "claude-3-5-sonnet-20241022", max_tokens: int = 1000) -> Dict:
    """Anthropic Claude API"""
    if not CLAUDE_API_KEY:
        return {"error": "CLAUDE_API_KEY not configured"}
    
    # Claude API 格式转换
    system_msg = ""
    claude_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_msg = msg["content"]
        else:
            claude_messages.append(msg)
    
    try:
        payload = {"model": model, "max_tokens": max_tokens, "messages": claude_messages}
        if system_msg:
            payload["system"] = system_msg
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "provider": "claude",
            "model": model,
            "content": data["content"][0]["text"],
            "usage": data.get("usage", {})
        }
    except Exception as e:
        return {"error": str(e), "provider": "claude"}

def get_weather(city: str, units: str = "metric") -> Dict:
    """OpenWeather API - 已验证可用"""
    if not OPENWEATHER_API_KEY:
        return {"error": "OPENWEATHER_API_KEY not configured"}
    
    try:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": OPENWEATHER_API_KEY, "units": units, "lang": "zh_cn"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "city": data["name"],
            "country": data["sys"]["country"],
            "temperature": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "wind_speed": data["wind"]["speed"]
        }
    except Exception as e:
        return {"error": str(e)}

def web_search(query: str, count: int = 10) -> Dict:
    """BraveSearch API - 已验证可用"""
    if not BRAVE_API_KEY:
        return {"error": "BRAVE_API_KEY not configured"}
    
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": BRAVE_API_KEY},
            params={"q": query, "count": count},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "description": item.get("description")
            })
        return {"success": True, "query": query, "results": results}
    except Exception as e:
        return {"error": str(e)}

# ============ API 端点 ============
@app.get("/health")
async def health():
    """健康检查 - 显示哪些 API 可用"""
    providers = []
    
    # 检查本地 LLM
    if LOCAL_LLM_ENABLED:
        try:
            resp = requests.get(f"{LOCAL_LLM_URL}/health", timeout=2)
            if resp.status_code == 200:
                providers.append("local")
        except Exception:
            pass
    
    # 检查云端提供商
    if OPENROUTER_API_KEY: providers.append("openrouter")
    if ZHIPU_API_KEY: providers.append("zhipu")
    if GROQ_API_KEY: providers.append("groq")
    if TOGETHER_API_KEY: providers.append("together")
    if PERPLEXITY_API_KEY: providers.append("perplexity")
    if CLAUDE_API_KEY: providers.append("claude")
    
    tools = []
    if OPENWEATHER_API_KEY: tools.append("weather")
    if BRAVE_API_KEY: tools.append("search")
    if PIXVERSE_API_KEY: tools.append("video_generation")
    
    return {
        "status": "healthy" if providers else "degraded",
        "node_id": "01",
        "name": "OneAPI Gateway",
        "available_providers": providers,
        "available_tools": tools,
        "local_llm_enabled": LOCAL_LLM_ENABLED,
        "local_llm_priority": LOCAL_LLM_PRIORITY if LOCAL_LLM_ENABLED else None,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    models = []
    
    # 本地 LLM 模型
    if LOCAL_LLM_ENABLED:
        try:
            resp = requests.get(f"{LOCAL_LLM_URL}/v1/models", timeout=2)
            if resp.status_code == 200:
                local_models = resp.json().get("data", [])
                for model in local_models:
                    models.append({
                        "id": f"local/{model['id']}",
                        "provider": "local",
                        "cost": 0,
                        "priority": LOCAL_LLM_PRIORITY
                    })
        except Exception:
            pass
    
    # 云端模型
    if OPENROUTER_API_KEY:
        models.extend([
            {"id": "openrouter/gpt-4", "provider": "openrouter", "cost": "medium"},
            {"id": "openrouter/gpt-3.5-turbo", "provider": "openrouter", "cost": "low"},
            {"id": "openrouter/claude-3-opus", "provider": "openrouter", "cost": "high"}
        ])
    if ZHIPU_API_KEY:
        models.extend([
            {"id": "zhipu/glm-4-flash", "provider": "zhipu", "cost": "low"},
            {"id": "zhipu/glm-4", "provider": "zhipu", "cost": "medium"}
        ])
    if GROQ_API_KEY:
        models.extend([
            {"id": "groq/llama-3.3-70b-versatile", "provider": "groq", "cost": "free"},
            {"id": "groq/mixtral-8x7b-32768", "provider": "groq", "cost": "free"}
        ])
    if TOGETHER_API_KEY:
        models.extend([
            {"id": "together/meta-llama/Llama-3.3-70B-Instruct-Turbo", "provider": "together", "cost": "low"},
            {"id": "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", "provider": "together", "cost": "medium"},
            {"id": "together/Qwen/Qwen2.5-72B-Instruct-Turbo", "provider": "together", "cost": "low"},
            {"id": "together/deepseek-ai/DeepSeek-V3", "provider": "together", "cost": "low"}
        ])
    if CLAUDE_API_KEY:
        models.extend([
            {"id": "claude/claude-3-5-sonnet-20241022", "provider": "claude", "cost": "high"},
            {"id": "claude/claude-3-haiku-20240307", "provider": "claude", "cost": "low"}
        ])
    
    return {"object": "list", "data": models}

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, authorization: str = Header(None)):
    """聊天补全 - OpenAI 兼容格式"""
    model = request.model
    messages = [m.dict() if hasattr(m, 'dict') else m for m in request.messages]
    max_tokens = request.max_tokens
    
    # 自动选择提供商
    if model == "auto" or "/" not in model:
        # 智能路由策略
        # 优先级: local (免费+快) > groq (快) > zhipu (中文) > openrouter > claude
        
        # 1. 尝试本地 LLM
        if LOCAL_LLM_ENABLED and LOCAL_LLM_PRIORITY == 1:
            result = call_local_llm(messages, max_tokens=max_tokens, temperature=request.temperature)
            if "error" not in result:
                # 本地成功，直接返回
                pass
            else:
                # 本地失败，Fallback 到云端
                if GROQ_API_KEY:
                    result = call_groq(messages, max_tokens=max_tokens)
                elif ZHIPU_API_KEY:
                    result = call_zhipu(messages, max_tokens=max_tokens)
                elif OPENROUTER_API_KEY:
                    result = call_openrouter(messages, max_tokens=max_tokens)
                elif CLAUDE_API_KEY:
                    result = call_claude(messages, max_tokens=max_tokens)
                else:
                    raise HTTPException(status_code=503, detail=f"Local LLM failed and no cloud provider available: {result['error']}")
        
        # 2. 云端优先，本地备用
        elif GROQ_API_KEY:
            result = call_groq(messages, max_tokens=max_tokens)
        elif TOGETHER_API_KEY:
            result = call_together(messages, max_tokens=max_tokens)
        elif ZHIPU_API_KEY:
            result = call_zhipu(messages, max_tokens=max_tokens)
        elif OPENROUTER_API_KEY:
            result = call_openrouter(messages, max_tokens=max_tokens)
        elif CLAUDE_API_KEY:
            result = call_claude(messages, max_tokens=max_tokens)
        elif LOCAL_LLM_ENABLED:
            # 所有云端都不可用，使用本地
            result = call_local_llm(messages, max_tokens=max_tokens, temperature=request.temperature)
        else:
            raise HTTPException(status_code=503, detail="No LLM provider configured")
    else:
        # 指定提供商
        if "/" in model:
            provider, model_name = model.split("/", 1)
        else:
            # 没有 /，直接使用本地 LLM
            provider = "local"
            model_name = model
        
        if provider == "local":
            result = call_local_llm(messages, model_name, max_tokens, request.temperature)
        elif provider == "openrouter":
            result = call_openrouter(messages, model_name, max_tokens)
        elif provider == "zhipu":
            result = call_zhipu(messages, model_name, max_tokens)
        elif provider == "groq":
            result = call_groq(messages, model_name, max_tokens)
        elif provider == "together":
            result = call_together(messages, model_name, max_tokens)
        elif provider == "perplexity":
            result = call_perplexity(messages, model_name, max_tokens)
        elif provider == "claude":
            result = call_claude(messages, model_name, max_tokens)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": result.get("model", model),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result["content"]},
            "finish_reason": "stop"
        }],
        "usage": result.get("usage", {}),
        "provider": result.get("provider")
    }

@app.post("/tools/weather")
async def api_weather(request: WeatherRequest):
    """获取天气"""
    result = get_weather(request.city, request.units)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.post("/tools/search")
async def api_search(request: SearchRequest):
    """网页搜索"""
    result = web_search(request.query, request.count)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.get("/tools")
async def list_tools():
    """列出可用工具"""
    return {
        "tools": [
            {"name": "chat", "description": "与 AI 对话", "endpoint": "/v1/chat/completions"},
            {"name": "weather", "description": "获取天气信息", "endpoint": "/tools/weather"},
            {"name": "search", "description": "网页搜索", "endpoint": "/tools/search"}
        ]
    }

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "chat":
        messages = params.get("messages", [])
        model = params.get("model", "auto")
        max_tokens = params.get("max_tokens", 1000)
        
        if model == "auto" or "/" not in model:
            if GROQ_API_KEY:
                return call_groq(messages, max_tokens=max_tokens)
            elif ZHIPU_API_KEY:
                return call_zhipu(messages, max_tokens=max_tokens)
            elif OPENROUTER_API_KEY:
                return call_openrouter(messages, max_tokens=max_tokens)
            elif CLAUDE_API_KEY:
                return call_claude(messages, max_tokens=max_tokens)
        return {"error": "No provider available"}
    elif tool == "weather":
        return get_weather(params.get("city", "Beijing"))
    elif tool == "search":
        return web_search(params.get("query", ""))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

@app.post("/generate_video")
async def generate_video(prompt: str, image_url: Optional[str] = None):
    """视频生成接口 - 使用 Pixverse"""
    result = call_pixverse(prompt, image_url)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result
