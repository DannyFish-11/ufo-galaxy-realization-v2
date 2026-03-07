#!/usr/bin/env python3
"""
Node 104: AgentCPM Integration
AgentCPM 集成节点 - 深度搜索和研究报告生成

功能:
1. AgentCPM-Explore 深度搜索（100+ 轮交互）
2. AgentCPM-Report 研究报告生成
3. AgentDock MCP 工具调用
4. 自动保存到 Memos
5. 任务取消、优先级、流式输出、自定义提示词、结果缓存
"""

import os
import json
import logging
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, AsyncGenerator
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI 应用
app = FastAPI(title="AgentCPM Integration Node", version="1.1.0")

# 配置
AGENTDOCK_URL = os.getenv("AGENTDOCK_URL", "http://localhost:8000")
AGENTCPM_API_KEY = os.getenv("AGENTCPM_API_KEY", "")
AGENTCPM_BASE_URL = os.getenv("AGENTCPM_BASE_URL", "")
MEMOS_URL = os.getenv("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.getenv("MEMOS_TOKEN", "")

# 结果缓存 TTL（秒），默认 1 小时
CACHE_TTL = int(os.getenv("AGENTCPM_CACHE_TTL", "3600"))

# 请求模型
class DeepSearchRequest(BaseModel):
    query: str
    max_turns: int = 100
    tools: List[str] = ["search", "arxiv", "calculator"]
    save_to_memos: bool = True
    priority: int = 5          # 任务优先级：1（最高）~ 10（最低），默认 5
    system_prompt: Optional[str] = None   # 自定义系统提示词

class DeepResearchRequest(BaseModel):
    topic: str
    depth: str = "deep"  # deep, medium, shallow
    output_format: str = "markdown"
    save_to_memos: bool = True
    priority: int = 5          # 任务优先级：1（最高）~ 10（最低），默认 5
    system_prompt: Optional[str] = None   # 自定义系统提示词

class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending, running, completed, failed, cancelled
    progress: int  # 0-100
    priority: int = 5
    result: Optional[Dict] = None
    error: Optional[str] = None

# 任务存储（生产环境应使用 Redis）
tasks: Dict[str, Dict] = {}

# 取消令牌集合
cancelled_tasks: set = set()

# 结果缓存：cache_key -> {"result": ..., "expires_at": datetime}
_result_cache: Dict[str, Dict] = {}


def _cache_key(task_type: str, **params) -> str:
    """生成缓存键"""
    payload = json.dumps({"type": task_type, **params}, sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()


def _get_cached(key: str) -> Optional[Dict]:
    """读取缓存，过期自动失效"""
    entry = _result_cache.get(key)
    if entry and datetime.now() < entry["expires_at"]:
        return entry["result"]
    if entry:
        del _result_cache[key]
    return None


def _set_cache(key: str, result: Dict):
    """写入缓存"""
    _result_cache[key] = {
        "result": result,
        "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL)
    }

# AgentDock 工具调用
async def call_agentdock_tool(tool_name: str, params: Dict) -> Dict:
    """调用 AgentDock MCP 工具"""
    try:
        url = f"{AGENTDOCK_URL}/tools/{tool_name}"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=params)
            response.raise_for_status()
        
        return response.json()
    
    except Exception as e:
        logger.error(f"AgentDock 工具调用失败: {e}")
        raise

# AgentCPM-Explore 深度搜索
async def deep_search(task_id: str, query: str, max_turns: int, tools: List[str],
                      system_prompt: Optional[str] = None):
    """执行深度搜索（支持取消、自定义提示、结果缓存）"""
    try:
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = 10

        # 检查缓存
        ck = _cache_key("deep_search", query=query, max_turns=max_turns, tools=sorted(tools))
        cached = _get_cached(ck)
        if cached:
            logger.info(f"命中缓存: {task_id}")
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            tasks[task_id]["result"] = cached
            return

        # 检查取消
        if task_id in cancelled_tasks:
            tasks[task_id]["status"] = "cancelled"
            cancelled_tasks.discard(task_id)
            return

        default_system = f"你是一个深度搜索助手，可以进行最多 {max_turns} 轮的交互来找到答案。可用工具: {', '.join(tools)}"
        system_content = system_prompt or default_system

        # 如果配置了 AgentCPM API，使用 API
        if AGENTCPM_API_KEY and AGENTCPM_BASE_URL:
            logger.info(f"使用 AgentCPM API 进行深度搜索: {query}")
            
            url = f"{AGENTCPM_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {AGENTCPM_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "agentcpm-explore",
                "messages": [
                    {
                        "role": "system",
                        "content": system_content
                    },
                    {
                        "role": "user",
                        "content": query
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.7
            }
            
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
            
            result = response.json()
            tasks[task_id]["progress"] = 90
            
        else:
            # 使用 Mock 模式（演示）
            logger.warning("未配置 AgentCPM API，使用 Mock 模式")
            
            result = {
                "id": task_id,
                "model": "agentcpm-explore-mock",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"""# 深度搜索结果：{query}

## 搜索过程

经过 {max_turns} 轮深度交互，我找到了以下信息：

### 第 1-10 轮：初步探索
- 使用搜索工具查询相关信息
- 发现多个潜在的信息源
- 交叉验证不同来源的数据

### 第 11-30 轮：深入分析
- 针对关键概念进行深入搜索
- 查阅学术论文和技术文档
- 构建知识图谱

### 第 31-50 轮：综合验证
- 多源交叉验证
- 检查数据一致性
- 识别潜在的矛盾

### 第 51-100 轮：结论形成
- 综合所有信息
- 形成最终答案
- 提供证据链

## 最终结论

关于"{query}"的深度搜索已完成。

**注意**: 这是 Mock 模式的演示结果。要获得真实的深度搜索能力，请配置 AgentCPM API。

## 使用的工具

{', '.join(tools)}

## 搜索统计

- 总轮数: {max_turns}
- 工具调用: {len(tools) * 10}
- 信息源: 15+
- 交叉验证: 5 次

---
*由 UFO³ Galaxy Node_104 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 500,
                    "total_tokens": 600
                }
            }
            
            # 模拟处理时间
            for _ in range(5):
                await asyncio.sleep(1)
                if task_id in cancelled_tasks:
                    tasks[task_id]["status"] = "cancelled"
                    cancelled_tasks.discard(task_id)
                    return
            tasks[task_id]["progress"] = 90
        
        # 再次检查取消
        if task_id in cancelled_tasks:
            tasks[task_id]["status"] = "cancelled"
            cancelled_tasks.discard(task_id)
            return

        # 写入缓存
        _set_cache(ck, result)

        # 保存到 Memos
        if tasks[task_id].get("save_to_memos", False):
            content = result["choices"][0]["message"]["content"]
            await save_to_memos(f"# 深度搜索：{query}\n\n{content}")
        
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["result"] = result
        
        logger.info(f"深度搜索完成: {task_id}")
    
    except Exception as e:
        logger.error(f"深度搜索失败: {e}")
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)

# AgentCPM-Report 研究报告生成
async def generate_research_report(task_id: str, topic: str, depth: str, output_format: str,
                                   system_prompt: Optional[str] = None):
    """生成研究报告（支持取消、自定义提示、结果缓存）"""
    try:
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = 10

        # 检查缓存
        ck = _cache_key("deep_research", topic=topic, depth=depth, output_format=output_format)
        cached = _get_cached(ck)
        if cached:
            logger.info(f"命中缓存: {task_id}")
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["progress"] = 100
            tasks[task_id]["result"] = cached
            return

        # 检查取消
        if task_id in cancelled_tasks:
            tasks[task_id]["status"] = "cancelled"
            cancelled_tasks.discard(task_id)
            return

        default_system = f"你是一个研究报告生成助手，擅长进行深度研究并生成高质量的{output_format}格式报告。研究深度: {depth}"
        system_content = system_prompt or default_system

        # 如果配置了 AgentCPM API，使用 API
        if AGENTCPM_API_KEY and AGENTCPM_BASE_URL:
            logger.info(f"使用 AgentCPM API 生成研究报告: {topic}")
            
            url = f"{AGENTCPM_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {AGENTCPM_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "agentcpm-report",
                "messages": [
                    {
                        "role": "system",
                        "content": system_content
                    },
                    {
                        "role": "user",
                        "content": f"请针对以下主题生成一份详细的研究报告：\n\n{topic}"
                    }
                ],
                "max_tokens": 8192,
                "temperature": 0.7
            }
            
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
            
            result = response.json()
            tasks[task_id]["progress"] = 90
            
        else:
            # 使用 Mock 模式（演示）
            logger.warning("未配置 AgentCPM API，使用 Mock 模式")
            
            result = {
                "id": task_id,
                "model": "agentcpm-report-mock",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"""# 研究报告：{topic}

## 执行摘要

本报告针对"{topic}"进行了深度研究，通过 40 轮深度检索和近 100 轮思维链推理，全面分析了该主题的现状、挑战和未来趋势。

## 研究方法

### 数据收集
- 检索学术论文 50+ 篇
- 分析技术文档 30+ 份
- 调研行业报告 20+ 份

### 分析框架
- SWOT 分析
- PEST 分析
- 趋势预测

## 主要发现

### 1. 当前现状

{topic}领域目前处于快速发展阶段，主要特点包括：

- **技术成熟度**: 中等偏上
- **市场规模**: 持续增长
- **竞争格局**: 多元化

### 2. 核心挑战

- 技术瓶颈
- 人才短缺
- 标准化问题

### 3. 未来趋势

- 智能化升级
- 跨领域融合
- 生态系统建设

## 详细分析

### 技术层面

（此处应包含详细的技术分析，包括架构设计、关键技术、性能指标等）

### 市场层面

（此处应包含市场规模、增长率、主要玩家、竞争态势等）

### 应用层面

（此处应包含典型应用场景、成功案例、最佳实践等）

## 结论与建议

### 结论

基于深度研究，我们得出以下结论：

1. {topic}具有巨大的发展潜力
2. 需要解决关键技术挑战
3. 生态系统建设至关重要

### 建议

1. **短期**（1-2 年）
   - 加强技术研发
   - 培养专业人才
   - 建立行业标准

2. **中期**（3-5 年）
   - 推动产业化应用
   - 构建生态系统
   - 拓展国际市场

3. **长期**（5+ 年）
   - 引领技术创新
   - 建立行业标准
   - 实现全球化布局

## 参考文献

1. 相关论文 1
2. 相关论文 2
3. ...

---

**研究深度**: {depth}  
**输出格式**: {output_format}  
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**注意**: 这是 Mock 模式的演示报告。要获得真实的深度研究能力，请配置 AgentCPM API。

---
*由 UFO³ Galaxy Node_104 (AgentCPM-Report) 生成*
"""
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 2000,
                    "total_tokens": 2200
                }
            }
            
            # 模拟处理时间（每秒检查一次取消）
            for _ in range(10):
                await asyncio.sleep(1)
                if task_id in cancelled_tasks:
                    tasks[task_id]["status"] = "cancelled"
                    cancelled_tasks.discard(task_id)
                    return
            tasks[task_id]["progress"] = 90
        
        # 再次检查取消
        if task_id in cancelled_tasks:
            tasks[task_id]["status"] = "cancelled"
            cancelled_tasks.discard(task_id)
            return

        # 写入缓存
        _set_cache(ck, result)

        # 保存到 Memos
        if tasks[task_id].get("save_to_memos", False):
            content = result["choices"][0]["message"]["content"]
            await save_to_memos(content)
        
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["result"] = result
        
        logger.info(f"研究报告生成完成: {task_id}")
    
    except Exception as e:
        logger.error(f"研究报告生成失败: {e}")
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)

# 保存到 Memos
async def save_to_memos(content: str) -> bool:
    """保存内容到 Memos"""
    try:
        if not MEMOS_TOKEN:
            logger.warning("未配置 MEMOS_TOKEN，跳过保存")
            return False
        
        url = f"{MEMOS_URL}/api/v1/memos"
        headers = {
            "Authorization": f"Bearer {MEMOS_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {
            "content": content,
            "visibility": "PRIVATE"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
        
        logger.info("内容已保存到 Memos")
        return True
    
    except Exception as e:
        logger.error(f"保存到 Memos 失败: {e}")
        return False

# API 端点
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "node": "Node_104_AgentCPM",
        "version": "1.1.0",
        "agentcpm_configured": bool(AGENTCPM_API_KEY and AGENTCPM_BASE_URL),
        "agentdock_url": AGENTDOCK_URL,
        "memos_configured": bool(MEMOS_TOKEN),
        "cache_ttl_seconds": CACHE_TTL
    }

@app.post("/deep_search")
async def create_deep_search(request: DeepSearchRequest, background_tasks: BackgroundTasks):
    """创建深度搜索任务（支持优先级、自定义提示词、结果缓存）"""
    try:
        task_id = f"search_{uuid.uuid4().hex[:12]}"
        
        tasks[task_id] = {
            "task_id": task_id,
            "type": "deep_search",
            "query": request.query,
            "status": "pending",
            "progress": 0,
            "priority": request.priority,
            "save_to_memos": request.save_to_memos,
            "created_at": datetime.now().isoformat()
        }
        
        # 后台执行
        background_tasks.add_task(
            deep_search,
            task_id,
            request.query,
            request.max_turns,
            request.tools,
            request.system_prompt
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "priority": request.priority,
            "message": "深度搜索任务已创建"
        }
    
    except Exception as e:
        logger.error(f"创建深度搜索任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deep_research")
async def create_deep_research(request: DeepResearchRequest, background_tasks: BackgroundTasks):
    """创建深度研究任务（支持优先级、自定义提示词、结果缓存）"""
    try:
        task_id = f"research_{uuid.uuid4().hex[:12]}"
        
        tasks[task_id] = {
            "task_id": task_id,
            "type": "deep_research",
            "topic": request.topic,
            "status": "pending",
            "progress": 0,
            "priority": request.priority,
            "save_to_memos": request.save_to_memos,
            "created_at": datetime.now().isoformat()
        }
        
        # 后台执行
        background_tasks.add_task(
            generate_research_report,
            task_id,
            request.topic,
            request.depth,
            request.output_format,
            request.system_prompt
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "priority": request.priority,
            "message": "深度研究任务已创建"
        }
    
    except Exception as e:
        logger.error(f"创建深度研究任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return tasks[task_id]

@app.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """取消任务（pending 或 running 状态）"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks[task_id]
    status = task.get("status")

    if status in ("completed", "failed", "cancelled"):
        return {
            "success": False,
            "task_id": task_id,
            "message": f"任务已处于终态 '{status}'，无法取消"
        }

    if status == "pending":
        # 未启动，直接标记取消
        tasks[task_id]["status"] = "cancelled"
    else:
        # 运行中，通过取消令牌集合通知后台协程
        cancelled_tasks.add(task_id)

    logger.info(f"任务取消请求已接受: {task_id}")
    return {
        "success": True,
        "task_id": task_id,
        "message": "任务取消请求已接受"
    }

@app.get("/tasks")
async def list_tasks(sort_by_priority: bool = False):
    """列出所有任务（可按优先级排序）"""
    task_list = list(tasks.values())
    if sort_by_priority:
        task_list.sort(key=lambda t: t.get("priority", 5))
    return {
        "total": len(task_list),
        "tasks": task_list
    }


# ── 流式输出端点 ──────────────────────────────────────────────────────────────

async def _stream_mock_content(content: str, chunk_size: int = 50) -> AsyncGenerator[str, None]:
    """将长文本按 chunk_size 字符拆分，以 SSE data: 格式逐块 yield"""
    for i in range(0, len(content), chunk_size):
        chunk = content[i:i + chunk_size]
        yield f"data: {json.dumps({'delta': chunk})}\n\n"
        await asyncio.sleep(0.05)
    yield "data: [DONE]\n\n"


@app.post("/stream_search")
async def stream_deep_search(request: DeepSearchRequest):
    """流式输出深度搜索结果（Server-Sent Events）"""

    default_system = (
        f"你是一个深度搜索助手，可以进行最多 {request.max_turns} 轮的交互来找到答案。"
        f"可用工具: {', '.join(request.tools)}"
    )
    system_content = request.system_prompt or default_system

    if AGENTCPM_API_KEY and AGENTCPM_BASE_URL:
        url = f"{AGENTCPM_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {AGENTCPM_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "agentcpm-explore",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": request.query}
            ],
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": True
        }

        async def _real_stream():
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream("POST", url, headers=headers, json=data) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield line + "\n\n"

        return StreamingResponse(_real_stream(), media_type="text/event-stream")

    # Mock 流式输出
    mock_content = (
        f"# 深度搜索结果：{request.query}\n\n"
        f"经过 {request.max_turns} 轮深度交互，以下是搜索结论……\n\n"
        "**注意**: 这是 Mock 模式的演示流式结果。\n\n"
        f"使用的工具: {', '.join(request.tools)}\n\n"
        f"*由 UFO³ Galaxy Node_104 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )
    return StreamingResponse(
        _stream_mock_content(mock_content),
        media_type="text/event-stream"
    )


@app.post("/stream_research")
async def stream_deep_research(request: DeepResearchRequest):
    """流式输出研究报告（Server-Sent Events）"""

    default_system = (
        f"你是一个研究报告生成助手，擅长进行深度研究并生成高质量的{request.output_format}格式报告。"
        f"研究深度: {request.depth}"
    )
    system_content = request.system_prompt or default_system

    if AGENTCPM_API_KEY and AGENTCPM_BASE_URL:
        url = f"{AGENTCPM_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {AGENTCPM_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "agentcpm-report",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"请针对以下主题生成一份详细的研究报告：\n\n{request.topic}"}
            ],
            "max_tokens": 8192,
            "temperature": 0.7,
            "stream": True
        }

        async def _real_stream():
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream("POST", url, headers=headers, json=data) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield line + "\n\n"

        return StreamingResponse(_real_stream(), media_type="text/event-stream")

    # Mock 流式输出
    mock_content = (
        f"# 研究报告：{request.topic}\n\n"
        f"研究深度: {request.depth} | 输出格式: {request.output_format}\n\n"
        "## 执行摘要\n\n本报告通过深度研究，全面分析了该主题的现状、挑战和未来趋势。\n\n"
        "**注意**: 这是 Mock 模式的演示流式报告。\n\n"
        f"*由 UFO³ Galaxy Node_104 (AgentCPM-Report) 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )
    return StreamingResponse(
        _stream_mock_content(mock_content),
        media_type="text/event-stream"
    )

# 启动服务
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_104_PORT", "8104"))
    uvicorn.run(app, host="0.0.0.0", port=port)
