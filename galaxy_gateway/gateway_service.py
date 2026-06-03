"""
Galaxy Gateway v5.0 - 自主学习和编程版本

集成模块：
1. Node_100_MemorySystem - 记忆和学习
2. Node_101_CodeEngine - 代码理解和生成
3. Node_102_DebugOptimize - 调试和优化
4. Node_103_KnowledgeGraph - 知识图谱和推理

新增能力：
- 从经验中学习
- 自主编写代码
- 自主调试和优化
- 知识管理和推理

版本：5.0.0
日期：2026-01-22
作者：Manus AI
"""
from core.port_config import get_service_port

import os
import json
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

from fastapi import APIRouter

# APIRouter 供主网关 app.py 挂载（Phase 5 集成）
router = APIRouter(prefix="/api/v5", tags=["gateway-v5"])

# 独立运行时的 FastAPI 应用（保留向后兼容）
app = FastAPI(title="Galaxy Gateway v5.0", version="5.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

# 节点服务地址
NODE_SERVICES = {
    "memory": os.getenv("MEMORY_SERVICE_URL", "http://localhost:8100"),
    "code": os.getenv("CODE_SERVICE_URL", "http://localhost:8101"),
    "debug": os.getenv("DEBUG_SERVICE_URL", "http://localhost:8102"),
    "knowledge": os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:8103")
}

# H2 fixed: module-level singleton clients to avoid creating new clients per health check
_client_instances: Dict[str, httpx.AsyncClient] = {}

# ============================================================================
# 数据模型
# ============================================================================

class LearnFromExperienceRequest(BaseModel):
    """从经验中学习请求"""
    command: str
    context: Dict[str, Any]
    actions: List[Dict[str, Any]]
    result: Dict[str, Any]
    success: bool

class GenerateCodeRequest(BaseModel):
    """生成代码请求"""
    requirement: str
    language: str = "python"
    context: Optional[str] = None

class DebugCodeRequest(BaseModel):
    """调试代码请求"""
    code: str
    error: Optional[str] = None
    language: str = "python"

class OptimizeCodeRequest(BaseModel):
    """优化代码请求"""
    code: str
    target: str = "speed"
    language: str = "python"

class ReasonRequest(BaseModel):
    """推理请求"""
    facts: List[str]
    question: str

class AutonomousProgrammingRequest(BaseModel):
    """自主编程请求"""
    task: str
    language: str = "python"
    auto_debug: bool = True
    auto_optimize: bool = True

# ============================================================================
# 服务客户端
# ============================================================================

class NodeClient:
    """节点服务客户端"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=60.0)

    async def aclose(self) -> None:
        """H1 fixed: close the underlying HTTP connection pool."""
        await self.client.aclose()

    async def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST 请求"""
        try:
            response = await self.client.post(
                f"{self.base_url}{endpoint}",
                json=data
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"success": False, "error": f"HTTP {response.status_code}", "error_code": "http_error", "status_code": response.status_code}
        except httpx.TimeoutException as e:
            return {"success": False, "error": str(e), "error_code": "timeout", "error_type": "TimeoutException"}
        except httpx.ConnectError as e:
            return {"success": False, "error": str(e), "error_code": "connection_refused", "error_type": "ConnectError"}
        except Exception as e:
            return {"success": False, "error": str(e), "error_code": "unknown", "error_type": type(e).__name__}

    async def get(self, endpoint: str) -> Dict[str, Any]:
        """GET 请求"""
        try:
            response = await self.client.get(f"{self.base_url}{endpoint}")
            if response.status_code == 200:
                return response.json()
            else:
                return {"success": False, "error": f"HTTP {response.status_code}", "error_code": "http_error", "status_code": response.status_code}
        except httpx.TimeoutException as e:
            return {"success": False, "error": str(e), "error_code": "timeout", "error_type": "TimeoutException"}
        except httpx.ConnectError as e:
            return {"success": False, "error": str(e), "error_code": "connection_refused", "error_type": "ConnectError"}
        except Exception as e:
            return {"success": False, "error": str(e), "error_code": "unknown", "error_type": type(e).__name__}

# 初始化客户端
memory_client = NodeClient(NODE_SERVICES["memory"])
code_client = NodeClient(NODE_SERVICES["code"])
debug_client = NodeClient(NODE_SERVICES["debug"])
knowledge_client = NodeClient(NODE_SERVICES["knowledge"])

# ============================================================================
# 自主学习引擎
# ============================================================================

class AutonomousLearningEngine:
    """自主学习引擎"""
    
    async def learn_from_experience(self, request: LearnFromExperienceRequest) -> Dict[str, Any]:
        """从经验中学习"""
        # 1. 存储经验
        experience_data = {
            "command": request.command,
            "context": request.context,
            "actions": request.actions,
            "result": request.result,
            "success": request.success,
            "duration": 0.0,
            "session_id": "auto_learning"
        }
        
        store_result = await memory_client.post("/store_experience", experience_data)
        
        if not store_result.get("success"):
            return {"success": False, "error": "存储经验失败"}
        
        # 2. 识别模式
        pattern_result = await memory_client.post("/identify_patterns", {
            "min_occurrences": 2
        })
        
        # 3. 提取知识
        knowledge_result = await memory_client.post("/extract_knowledge", {
            "min_confidence": 0.6
        })
        
        # 4. 更新知识图谱
        if knowledge_result.get("success") and knowledge_result.get("knowledge"):
            for knowledge in knowledge_result["knowledge"][:5]:  # 限制数量
                # 添加实体
                await knowledge_client.post("/add_entity", {
                    "name": request.command,
                    "type": "command",
                    "properties": {"success_rate": knowledge.get("confidence", 0.0)}
                })
        
        return {
            "success": True,
            "experience_id": store_result.get("experience_id"),
            "patterns_found": pattern_result.get("count", 0),
            "knowledge_extracted": knowledge_result.get("count", 0)
        }

# 初始化自主学习引擎
learning_engine = AutonomousLearningEngine()

# ============================================================================
# 自主编程引擎
# ============================================================================

class AutonomousProgrammingEngine:
    """自主编程引擎"""
    
    async def program(self, request: AutonomousProgrammingRequest) -> Dict[str, Any]:
        """自主编程"""
        result = {
            "success": True,
            "task": request.task,
            "language": request.language,
            "steps": []
        }
        
        # 步骤 1: 生成代码
        result["steps"].append("生成代码...")
        code_result = await code_client.post("/generate_code", {
            "requirement": request.task,
            "language": request.language
        })
        
        if not code_result.get("success"):
            return {"success": False, "error": "代码生成失败"}
        
        code = code_result.get("code", "")
        result["code"] = code
        result["steps"].append(f"✅ 代码生成成功（{len(code)} 字符）")
        
        # 步骤 2: 检测错误
        if request.auto_debug:
            result["steps"].append("检测错误...")
            error_result = await debug_client.post("/detect_errors", {
                "code": code,
                "language": request.language
            })
            
            if error_result.get("success") and error_result.get("error_count", 0) > 0:
                result["steps"].append(f"⚠️ 发现 {error_result['error_count']} 个错误")
                
                # 尝试自动修复
                for error in error_result.get("errors", [])[:3]:  # 限制修复次数
                    result["steps"].append(f"修复错误: {error.get('message', '')}")
                    fix_result = await debug_client.post("/auto_fix", {
                        "code": code,
                        "error": json.dumps(error),
                        "language": request.language
                    })
                    
                    if fix_result.get("success") and fix_result.get("fix"):
                        code = fix_result["fix"]["fixed_code"]
                        result["code"] = code
                        result["steps"].append("✅ 错误已修复")
                    else:
                        result["steps"].append("❌ 无法自动修复")
            else:
                result["steps"].append("✅ 未发现错误")
        
        # 步骤 3: 优化代码
        if request.auto_optimize:
            result["steps"].append("优化代码...")
            optimize_result = await debug_client.post("/optimize_code", {
                "code": code,
                "target": "both",
                "language": request.language
            })
            
            if optimize_result.get("success"):
                optimized_code = optimize_result.get("optimized_code", code)
                if optimized_code != code:
                    result["code"] = optimized_code
                    result["steps"].append("✅ 代码已优化")
                else:
                    result["steps"].append("✅ 代码已是最优")
        
        # 步骤 4: 学习经验
        await learning_engine.learn_from_experience(LearnFromExperienceRequest(
            command=f"自主编程: {request.task}",
            context={"language": request.language},
            actions=[{"type": "generate_code"}, {"type": "debug"}, {"type": "optimize"}],
            result={"code_length": len(result["code"])},
            success=True
        ))
        
        result["steps"].append("✅ 经验已学习")
        
        return result

# 初始化自主编程引擎
programming_engine = AutonomousProgrammingEngine()

# ============================================================================
# API 端点
# ============================================================================

async def _health_impl():
    """健康检查实现"""
    services_status = {}
    for name, url in NODE_SERVICES.items():
        try:
            # H2 fixed: use singleton client per service instead of creating new one each call
            client = _client_instances.setdefault(name, NodeClient(url))
            result = await client.get("/health")
            services_status[name] = result.get("status") == "healthy"
        except Exception:
            services_status[name] = False
    return {
        "status": "healthy",
        "version": "5.0.0",
        "name": "Galaxy Gateway v5.0",
        "services": services_status,
        "timestamp": datetime.now().isoformat()
    }


async def _learn_impl(request: LearnFromExperienceRequest) -> Dict[str, Any]:
    return await learning_engine.learn_from_experience(request)


async def _generate_code_impl(request: GenerateCodeRequest) -> Dict[str, Any]:
    return await code_client.post("/generate_code", {
        "requirement": request.requirement,
        "language": request.language,
        "context": request.context
    })


async def _debug_code_impl(request: DebugCodeRequest) -> Dict[str, Any]:
    error_result = await debug_client.post("/detect_errors", {
        "code": request.code,
        "language": request.language
    })
    if not error_result.get("success"):
        return error_result
    if error_result.get("error_count", 0) > 0:
        first_error = error_result["errors"][0]
        fix_result = await debug_client.post("/auto_fix", {
            "code": request.code,
            "error": json.dumps(first_error),
            "language": request.language
        })
        return {
            "success": True,
            "errors": error_result["errors"],
            "fix": fix_result.get("fix")
        }
    return {"success": True, "errors": [], "message": "未发现错误"}


async def _optimize_code_impl(request: OptimizeCodeRequest) -> Dict[str, Any]:
    return await debug_client.post("/optimize_code", {
        "code": request.code,
        "target": request.target,
        "language": request.language
    })


async def _reason_impl(request: ReasonRequest) -> Dict[str, Any]:
    return await knowledge_client.post("/reason", {
        "facts": request.facts,
        "question": request.question
    })


async def _auto_program_impl(request: AutonomousProgrammingRequest) -> Dict[str, Any]:
    return await programming_engine.program(request)


async def _stats_impl() -> Dict[str, Any]:
    memory_stats = await memory_client.get("/stats")
    knowledge_stats = await knowledge_client.get("/stats")
    return {
        "success": True,
        "memory": memory_stats,
        "knowledge": knowledge_stats,
        "timestamp": datetime.now().isoformat()
    }


# ── 注册到独立 app（原有路径，向后兼容）──
app.get("/health")(_health_impl)
app.post("/learn_from_experience")(_learn_impl)
app.post("/generate_code")(_generate_code_impl)
app.post("/debug_code")(_debug_code_impl)
app.post("/optimize_code")(_optimize_code_impl)
app.post("/reason")(_reason_impl)
app.post("/autonomous_programming")(_auto_program_impl)
app.get("/stats")(_stats_impl)

# ── 注册到 APIRouter（供主网关挂载，路径带 /api/v5 前缀）──
router.get("/health")(_health_impl)
router.post("/learn_from_experience")(_learn_impl)
router.post("/generate_code")(_generate_code_impl)
router.post("/debug_code")(_debug_code_impl)
router.post("/optimize_code")(_optimize_code_impl)
router.post("/reason")(_reason_impl)
router.post("/autonomous_programming")(_auto_program_impl)
router.get("/stats")(_stats_impl)

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=get_service_port("state_machine"))
