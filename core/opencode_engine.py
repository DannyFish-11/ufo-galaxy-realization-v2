"""
UFO Galaxy - OpenCode 引擎
===========================

提供代码生成、多模型支持和配置管理能力。
通过 MultiLLMRouter 调用真实 LLM 提供商生成代码。

环境变量：
  OPENCODE_PROVIDER  - 指定提供商（如 openai / anthropic / google / deepseek），
                       未设置则由路由器自动选择编码能力最优的提供商。
  OPENCODE_MODEL     - 指定模型名称，未设置则使用路由器为该提供商选出的默认模型。
  OPENCODE_TIMEOUT   - 单次 LLM 调用超时秒数（默认 60）。
"""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OpenCode")

# 代码生成专用系统提示
_SYSTEM_PROMPT = (
    "You are an expert software engineer. "
    "When asked to generate code, output ONLY the code block with no extra commentary "
    "unless the user specifically asks for explanations. "
    "Wrap the code in a markdown fenced code block with the language identifier."
)


class ModelProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GOOGLE = "google"
    OLLAMA = "ollama"


@dataclass
class CodeGenerationResult:
    generation_id: str
    prompt: str
    language: str
    code: str
    model: str
    success: bool
    error: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "generation_id": self.generation_id,
            "prompt": self.prompt,
            "language": self.language,
            "code": self.code,
            "model": self.model,
            "provider": self.provider,
            "success": self.success,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


def _extract_code(raw: str, language: Optional[str]) -> str:
    """从 LLM 响应中提取代码块内容。"""
    lines = raw.strip().splitlines()
    inside = False
    collected: List[str] = []
    lang = (language or "").lower()
    for line in lines:
        stripped = line.strip()
        if not inside:
            if stripped.startswith("```"):
                inside = True
                # 跳过 ```python / ```js 等开头行
                continue
        else:
            if stripped == "```":
                break
            collected.append(line)
    if collected:
        return "\n".join(collected)
    # 若无代码块标记，直接返回原始内容（部分模型不加标记）
    return raw.strip()


class OpenCodeEngine:
    """OpenCode 引擎 - 通过 MultiLLMRouter 进行真实 LLM 代码生成。"""

    def __init__(self):
        self.generation_history: List[CodeGenerationResult] = []
        # 优先读环境变量；可通过 configure() 在运行时覆盖
        self._configured_model: Optional[str] = os.environ.get("OPENCODE_MODEL") or None
        self._configured_provider: Optional[str] = os.environ.get("OPENCODE_PROVIDER") or None
        self._timeout: float = float(os.environ.get("OPENCODE_TIMEOUT", "60"))
        self._installed: bool = True  # 不再依赖外部二进制
        logger.info(
            "OpenCode 引擎已初始化 | provider=%s model=%s timeout=%.0fs",
            self._configured_provider or "auto",
            self._configured_model or "auto",
            self._timeout,
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def generate_code_async(
        self,
        prompt: str,
        language: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> CodeGenerationResult:
        """
        使用 MultiLLMRouter 生成代码（异步版本，推荐在 FastAPI 路由中使用）。

        若未配置任何 LLM 提供商，返回带明确错误信息的失败结果，不抛出异常。
        """
        from core.multi_llm_router import get_llm_router, ProviderStatus

        gen_id = f"codegen_{uuid.uuid4().hex[:12]}"
        lang = language or "python"
        effective_provider = provider or self._configured_provider
        effective_model = model or self._configured_model
        start_ts = time.time()

        # ── 检查路由器是否有可用提供商 ────────────────────────────────────
        router = get_llm_router()
        available = [
            name for name, cfg in router.providers.items()
            if cfg.status != ProviderStatus.DOWN
        ]
        if not available:
            err = (
                "OpenCodeEngine: 没有可用的 LLM 提供商。"
                "请设置至少一个 API Key（如 OPENAI_API_KEY / GEMINI_API_KEY / "
                "DEEPSEEK_API_KEY / ANTHROPIC_API_KEY）后重试。"
            )
            logger.error(err)
            result = CodeGenerationResult(
                generation_id=gen_id,
                prompt=prompt,
                language=lang,
                code="",
                model=effective_model or "none",
                provider="none",
                success=False,
                error=err,
                latency_ms=0.0,
            )
            self.generation_history.append(result)
            return result

        # ── 构建消息 ──────────────────────────────────────────────────────
        user_content = f"Generate {lang} code for the following task:\n\n{prompt}"
        if context:
            user_content += f"\n\nAdditional context:\n{context}"
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # ── 调用 LLM（带超时） ────────────────────────────────────────────
        try:
            llm_response = await asyncio.wait_for(
                router.chat(
                    messages,
                    task_type="coding",
                    provider=effective_provider,
                    model=effective_model,
                    temperature=0.2,
                    max_tokens=4096,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            err = (
                f"OpenCodeEngine: LLM 调用超时（{self._timeout:.0f}s）。"
                "可通过 OPENCODE_TIMEOUT 环境变量调整超时时间。"
            )
            logger.error(err)
            result = CodeGenerationResult(
                generation_id=gen_id,
                prompt=prompt,
                language=lang,
                code="",
                model=effective_model or "none",
                provider=effective_provider or "none",
                success=False,
                error=err,
                latency_ms=(time.time() - start_ts) * 1000,
            )
            self.generation_history.append(result)
            return result
        except Exception as exc:
            err = f"OpenCodeEngine: LLM 调用失败 — {exc}"
            logger.error(err, exc_info=True)
            result = CodeGenerationResult(
                generation_id=gen_id,
                prompt=prompt,
                language=lang,
                code="",
                model=effective_model or "none",
                provider=effective_provider or "none",
                success=False,
                error=err,
                latency_ms=(time.time() - start_ts) * 1000,
            )
            self.generation_history.append(result)
            return result

        # ── 解析响应 ──────────────────────────────────────────────────────
        raw_code = llm_response.content or ""
        code = _extract_code(raw_code, lang)
        latency_ms = (time.time() - start_ts) * 1000

        logger.info(
            "OpenCodeEngine 代码生成成功 | provider=%s model=%s lang=%s latency=%.0fms gen_id=%s",
            llm_response.provider,
            llm_response.model,
            lang,
            latency_ms,
            gen_id,
        )

        result = CodeGenerationResult(
            generation_id=gen_id,
            prompt=prompt,
            language=lang,
            code=code,
            model=llm_response.model,
            provider=llm_response.provider,
            success=True,
            latency_ms=latency_ms,
        )
        self.generation_history.append(result)
        return result

    def generate_code(
        self,
        prompt: str,
        language: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> CodeGenerationResult:
        """
        同步封装（在非 async 上下文中使用）。

        此方法在新的独立事件循环中运行异步代码，避免与已有事件循环冲突。
        在 FastAPI 路由等 async 上下文中请直接使用 generate_code_async()，
        不要在已有事件循环中调用此方法。
        """
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self.generate_code_async(
                        prompt=prompt,
                        language=language,
                        model=model,
                        provider=provider,
                        context=context,
                    )
                )
            finally:
                loop.close()
        except Exception as exc:
            gen_id = f"codegen_{uuid.uuid4().hex[:12]}"
            err = f"OpenCodeEngine: 同步调用失败 — {exc}"
            logger.error(err, exc_info=True)
            result = CodeGenerationResult(
                generation_id=gen_id,
                prompt=prompt,
                language=language or "python",
                code="",
                model=model or self._configured_model or "none",
                provider=provider or self._configured_provider or "none",
                success=False,
                error=err,
            )
            self.generation_history.append(result)
            return result

    def configure(
        self,
        model: str,
        provider: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict:
        """配置默认提供商和模型。"""
        known_providers = {p.value for p in ModelProvider}
        if provider not in known_providers:
            return {
                "success": False,
                "error": f"不支持的提供商: {provider}。支持: {sorted(known_providers)}",
            }
        self._configured_provider = provider
        self._configured_model = model
        logger.info("OpenCodeEngine 配置更新 | provider=%s model=%s", provider, model)
        return {"success": True, "model": model, "provider": provider}

    def install(self) -> dict:
        self._installed = True
        return {"success": True, "message": "OpenCode engine ready (LLM-backed)"}

    def get_status(self) -> dict:
        """返回引擎状态，包含配置的提供商、模型及可用性信息。"""
        from core.multi_llm_router import get_llm_router, ProviderStatus

        router = get_llm_router()
        available_providers = [
            name for name, cfg in router.providers.items()
            if cfg.status != ProviderStatus.DOWN
        ]
        router_status = router.get_status()

        effective_provider = self._configured_provider or (available_providers[0] if available_providers else None)
        effective_model = self._configured_model
        if effective_model is None and effective_provider and effective_provider in router.providers:
            effective_model = router.providers[effective_provider].default_model

        return {
            "installed": self._installed,
            "generation_count": len(self.generation_history),
            "configured_provider": self._configured_provider,
            "configured_model": self._configured_model,
            "effective_provider": effective_provider,
            "effective_model": effective_model,
            "available_providers": available_providers,
            "provider_count": router_status.get("total_providers", 0),
            "healthy_provider_count": router_status.get("healthy_providers", 0),
            "timeout_seconds": self._timeout,
        }

    def get_supported_models(self) -> dict:
        return {
            "openai": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
            "anthropic": ["claude-opus-4-20250514", "claude-sonnet-4-20250514"],
            "deepseek": ["deepseek-chat", "deepseek-coder"],
            "google": ["gemini-2.0-flash", "gemini-2.0-pro"],
            "ollama": ["codellama", "deepseek-coder"],
        }
