"""
Galaxy - OpenCode API 路由
==========================

提供代码生成相关端点：

  POST /api/v1/opencode/generate   - 使用 LLM 生成代码
  GET  /api/v1/opencode/status     - 引擎健康 / 配置状态
  POST /api/v1/opencode/configure  - 配置默认提供商和模型
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API")

# ── 请求 / 响应模型 ──────────────────────────────────────────────────────────


class GenerateCodeRequest(BaseModel):
    prompt: str
    language: Optional[str] = "python"
    model: Optional[str] = None
    provider: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class ConfigureRequest(BaseModel):
    model: str
    provider: str
    temperature: float = 0.7


# ── 路由工厂（与其他子模块一致） ─────────────────────────────────────────────


def create_router(service_manager=None, config=None) -> APIRouter:
    """创建 OpenCode 路由。"""
    router = APIRouter()

    # 进程级单例（模块加载时初始化，避免并发竞争）
    _engine_holder: list = []

    def _get_engine():
        if not _engine_holder:
            from core.opencode_engine import OpenCodeEngine
            _engine_holder.append(OpenCodeEngine())
        return _engine_holder[0]

    # ── POST /api/v1/opencode/generate ────────────────────────────────────

    @router.post("/api/v1/opencode/generate")
    async def opencode_generate(req: GenerateCodeRequest):
        """
        使用配置的 LLM 提供商生成代码。

        若未配置任何 LLM API Key，返回明确的错误信息（不静默返回空代码）。
        """
        try:
            engine = _get_engine()
            result = await engine.generate_code_async(
                prompt=req.prompt,
                language=req.language,
                model=req.model,
                provider=req.provider,
                context=req.context,
            )
            status_code = 200 if result.success else 503
            return JSONResponse(result.to_dict(), status_code=status_code)
        except Exception as exc:
            logger.exception("opencode_generate 未捕获异常: %s", exc)
            return JSONResponse(
                {"success": False, "error": f"内部错误: {exc}"},
                status_code=500,
            )

    # ── GET /api/v1/opencode/status ───────────────────────────────────────

    @router.get("/api/v1/opencode/status")
    async def opencode_status():
        """
        返回 OpenCode 引擎的健康状态，包含：
        - 配置的提供商 / 模型
        - 实际生效的提供商 / 模型
        - 当前可用的 LLM 提供商列表
        """
        try:
            engine = _get_engine()
            return JSONResponse({"success": True, **engine.get_status()})
        except Exception as exc:
            logger.exception("opencode_status 未捕获异常: %s", exc)
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )

    # ── POST /api/v1/opencode/configure ──────────────────────────────────

    @router.post("/api/v1/opencode/configure")
    async def opencode_configure(req: ConfigureRequest):
        """配置 OpenCode 引擎默认使用的提供商和模型。"""
        try:
            engine = _get_engine()
            result = engine.configure(
                model=req.model,
                provider=req.provider,
                temperature=req.temperature,
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)
        except Exception as exc:
            logger.exception("opencode_configure 未捕获异常: %s", exc)
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )

    return router
