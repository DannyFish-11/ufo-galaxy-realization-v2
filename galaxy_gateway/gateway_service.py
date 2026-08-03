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

import atexit
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.port_config import get_service_port
from nodes.common.cors_config import get_cors_headers, get_cors_methods, get_cors_origins

# APIRouter 供主网关 app.py 挂载（Phase 5 集成）
router = APIRouter(prefix="/api/v5", tags=["gateway-v5"])


# 独立运行时的 FastAPI 应用（保留向后兼容）——**惰性构造**。
#
# 生产里被服务的只有 galaxy_gateway.app:app(见 Dockerfile.gateway 的 CMD),
# 而本模块唯一的生产消费者 galaxy_gateway/app.py 只取上面的 ``router``。
# 这个独立 app 因此在正常运行中从不被使用。
#
# 它在模块级构造时的真实代价不是 FastAPI() 本身(实测 0.1ms),而是
# ``add_middleware`` 的 **参数在导入时就被求值**:get_cors_origins() 会一路走到
# port_config.instance(),把 130 个节点 + 25 个基础服务的端口配置整个加载一遍 ——
# 实测 267ms,全部花在一个没人服务的对象上。
#
# 用 PEP 562 的模块级 __getattr__ 改成首次访问时才建:``uvicorn
# galaxy_gateway.gateway_service:app`` 这种用法照旧可用(uvicorn 取模块属性时会
# 触发构造),而只 import router 的路径一分钱不花。
def _build_standalone_app() -> FastAPI:
    """构造独立运行用的 app。只有真的要单独跑本服务时才会被调用。"""
    standalone = FastAPI(title="Galaxy Gateway v5.0", version="5.0.0")
    standalone.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=get_cors_methods(),
        allow_headers=get_cors_headers(),
    )
    # 路由注册在模块底部定义(那里才拿得到各 _impl 函数),此处按名字晚绑定调用。
    _register_standalone_routes(standalone)
    return standalone


_standalone_app: Optional[FastAPI] = None


def __getattr__(name: str):
    """PEP 562:让 ``gateway_service.app`` 在首次访问时才真正构造。"""
    if name == "app":
        global _standalone_app
        if _standalone_app is None:
            _standalone_app = _build_standalone_app()
        return _standalone_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================================
# 配置
# ============================================================================

# 节点服务地址
NODE_SERVICES = {
    "memory": os.getenv("MEMORY_SERVICE_URL", "http://localhost:8100"),
    "code": os.getenv("CODE_SERVICE_URL", "http://localhost:8101"),
    "debug": os.getenv("DEBUG_SERVICE_URL", "http://localhost:8102"),
    "knowledge": os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:8103"),
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
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """惰性构造底层 httpx 客户端。

        原先是在 ``__init__`` 里直接建的,而模块底部会在 **import 时**构造 4 个
        NodeClient 单例 —— 于是每次 import 本模块都要建 4 个连接池。实测这一项占
        ``gateway_service`` 导入耗时的 388ms(4 × ~97ms),而网关进程在真正发出
        第一个节点请求之前,这些池子一个都用不上。

        单例本身是对的(避免每次健康检查新建客户端),要改的只是**建的时机**。
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def aclose(self) -> None:
        """H1 fixed: close the underlying HTTP connection pool.

        走 ``_client`` 而不是 ``client`` 属性:从没用过的客户端不该为了关闭而被建出来。
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST 请求"""
        try:
            response = await self.client.post(f"{self.base_url}{endpoint}", json=data)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "error_code": "http_error",
                    "status_code": response.status_code,
                }
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
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "error_code": "http_error",
                    "status_code": response.status_code,
                }
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

# PR-ASYNC-CLIENT: register cleanup to prevent resource leaks on exit

_all_clients = [memory_client, code_client, debug_client, knowledge_client]


async def _close_all_clients():
    for c in _all_clients:
        try:
            # 用 c.aclose() 而非 c.client.aclose():后者会触发惰性属性,
            # 把一个从未使用过的连接池**建出来只为了关掉它**。
            await c.aclose()
        except Exception:
            pass


def _cleanup_clients_sync():
    """Synchronous cleanup for atexit — best-effort close."""
    try:
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_close_all_clients())
        else:
            loop.run_until_complete(_close_all_clients())
    except Exception:
        pass


atexit.register(_cleanup_clients_sync)

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
            "session_id": "auto_learning",
        }

        store_result = await memory_client.post("/store_experience", experience_data)

        if not store_result.get("success"):
            return {"success": False, "error": "存储经验失败"}

        # 2. 识别模式
        pattern_result = await memory_client.post("/identify_patterns", {"min_occurrences": 2})

        # 3. 提取知识
        knowledge_result = await memory_client.post("/extract_knowledge", {"min_confidence": 0.6})

        # 4. 更新知识图谱
        if knowledge_result.get("success") and knowledge_result.get("knowledge"):
            for knowledge in knowledge_result["knowledge"][:5]:  # 限制数量
                # 添加实体
                await knowledge_client.post(
                    "/add_entity",
                    {
                        "name": request.command,
                        "type": "command",
                        "properties": {"success_rate": knowledge.get("confidence", 0.0)},
                    },
                )

        return {
            "success": True,
            "experience_id": store_result.get("experience_id"),
            "patterns_found": pattern_result.get("count", 0),
            "knowledge_extracted": knowledge_result.get("count", 0),
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
        result = {"success": True, "task": request.task, "language": request.language, "steps": []}

        # 步骤 1: 生成代码
        result["steps"].append("生成代码...")
        code_result = await code_client.post(
            "/generate_code", {"requirement": request.task, "language": request.language}
        )

        if not code_result.get("success"):
            return {"success": False, "error": "代码生成失败"}

        code = code_result.get("code", "")
        result["code"] = code
        result["steps"].append(f"✅ 代码生成成功（{len(code)} 字符）")

        # 步骤 2: 检测错误
        if request.auto_debug:
            result["steps"].append("检测错误...")
            error_result = await debug_client.post("/detect_errors", {"code": code, "language": request.language})

            if error_result.get("success") and error_result.get("error_count", 0) > 0:
                result["steps"].append(f"⚠️ 发现 {error_result['error_count']} 个错误")

                # 尝试自动修复
                for error in error_result.get("errors", [])[:3]:  # 限制修复次数
                    result["steps"].append(f"修复错误: {error.get('message', '')}")
                    fix_result = await debug_client.post(
                        "/auto_fix", {"code": code, "error": json.dumps(error), "language": request.language}
                    )

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
            optimize_result = await debug_client.post(
                "/optimize_code", {"code": code, "target": "both", "language": request.language}
            )

            if optimize_result.get("success"):
                optimized_code = optimize_result.get("optimized_code", code)
                if optimized_code != code:
                    result["code"] = optimized_code
                    result["steps"].append("✅ 代码已优化")
                else:
                    result["steps"].append("✅ 代码已是最优")

        # 步骤 4: 学习经验
        await learning_engine.learn_from_experience(
            LearnFromExperienceRequest(
                command=f"自主编程: {request.task}",
                context={"language": request.language},
                actions=[{"type": "generate_code"}, {"type": "debug"}, {"type": "optimize"}],
                result={"code_length": len(result["code"])},
                success=True,
            )
        )

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
        "timestamp": datetime.now().isoformat(),
    }


async def _learn_impl(request: LearnFromExperienceRequest) -> Dict[str, Any]:
    return await learning_engine.learn_from_experience(request)


async def _generate_code_impl(request: GenerateCodeRequest) -> Dict[str, Any]:
    return await code_client.post(
        "/generate_code", {"requirement": request.requirement, "language": request.language, "context": request.context}
    )


async def _debug_code_impl(request: DebugCodeRequest) -> Dict[str, Any]:
    error_result = await debug_client.post("/detect_errors", {"code": request.code, "language": request.language})
    if not error_result.get("success"):
        return error_result
    if error_result.get("error_count", 0) > 0:
        first_error = error_result["errors"][0]
        fix_result = await debug_client.post(
            "/auto_fix", {"code": request.code, "error": json.dumps(first_error), "language": request.language}
        )
        return {"success": True, "errors": error_result["errors"], "fix": fix_result.get("fix")}
    return {"success": True, "errors": [], "message": "未发现错误"}


async def _optimize_code_impl(request: OptimizeCodeRequest) -> Dict[str, Any]:
    return await debug_client.post(
        "/optimize_code", {"code": request.code, "target": request.target, "language": request.language}
    )


async def _reason_impl(request: ReasonRequest) -> Dict[str, Any]:
    return await knowledge_client.post("/reason", {"facts": request.facts, "question": request.question})


async def _auto_program_impl(request: AutonomousProgrammingRequest) -> Dict[str, Any]:
    return await programming_engine.program(request)


async def _stats_impl() -> Dict[str, Any]:
    memory_stats = await memory_client.get("/stats")
    knowledge_stats = await knowledge_client.get("/stats")
    return {
        "success": True,
        "memory": memory_stats,
        "knowledge": knowledge_stats,
        "timestamp": datetime.now().isoformat(),
    }


# ── 注册到独立 app（原有路径，向后兼容）──
#
# 这几行原本在模块级直接执行。它们必须挪进 _register_standalone_routes():
# 只要模块体里出现一次 `app`,PEP 562 的 __getattr__ 就会被触发、把独立 app 立刻
# 建出来 —— 惰性化会当场失效,等于白改。
#
# 注意这里注册的是**根路径**(/health、/stats…),与 router 的 /api/v5 前缀是
# 两个不同的路径面,所以不能用 include_router(router) 代替这一段。
def _register_standalone_routes(standalone: FastAPI) -> None:
    standalone.get("/health")(_health_impl)
    standalone.post("/learn_from_experience")(_learn_impl)
    standalone.post("/generate_code")(_generate_code_impl)
    standalone.post("/debug_code")(_debug_code_impl)
    standalone.post("/optimize_code")(_optimize_code_impl)
    standalone.post("/reason")(_reason_impl)
    standalone.post("/autonomous_programming")(_auto_program_impl)
    standalone.get("/stats")(_stats_impl)


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

    # 注意:这里必须显式调用 _build_standalone_app(),不能写裸 `app`。
    # PEP 562 的模块级 __getattr__ 只在【从模块外部】取属性时触发;模块自身代码里的
    # 裸名字走的是 globals(),取不到就直接 NameError。flake8 的 F821 正是这么抓到的。
    uvicorn.run(_build_standalone_app(), host="0.0.0.0", port=get_service_port("state_machine"))
