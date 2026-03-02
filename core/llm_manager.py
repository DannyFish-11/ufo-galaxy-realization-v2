import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger("llm_manager")


class ModelConfig(BaseModel):
    provider: str = "oneapi"
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    temperature: float = 0.7


class TokenUsage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_cost: float
    timestamp: str


# ============================================================================
# 提供商优先级链 — 按 .env 中实际配置的 Key 自动构建
# ============================================================================

_ENV_PROVIDER_CHAIN = [
    # (env_key_name, base_url, default_model, supports_tools)
    ("OPENAI_API_KEY",     "OPENAI_API_BASE",    "https://api.openai.com/v1",       "gpt-4o",                      True),
    ("DEEPSEEK_API_KEY",   None,                 "https://api.deepseek.com/v1",     "deepseek-chat",                True),
    ("OPENROUTER_API_KEY", None,                 "https://openrouter.ai/api/v1",    "openai/gpt-4o-mini",           True),
    ("GROQ_API_KEY",       None,                 "https://api.groq.com/openai/v1",  "llama-3.3-70b-versatile",      True),
    ("XAI_API_KEY",        None,                 "https://api.x.ai/v1",             "grok-2-latest",                True),
    ("ANTHROPIC_API_KEY",  None,                 "https://api.anthropic.com/v1",    "claude-sonnet-4-20250514",     False),  # Anthropic 有不同的 API
    ("ZHIPU_API_KEY",      None,                 "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash",             True),
]


class LLMManager:
    """
    统一 LLM 管理器

    客户端获取优先级:
    1. config.json 中的 OneAPI 聚合层 (如已配置)
    2. .env / 环境变量中的各 Provider API Key (自动 fallback 链)
    3. 若全部无 → 抛出明确错误提示
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.oneapi_client: Optional[Any] = None
        self.oneapi_config: Optional[Dict] = None
        self.usage_log: List[TokenUsage] = []
        self.default_model = "gpt-4o"

        # 环境变量 fallback 客户端链
        self._env_clients: List[Dict[str, Any]] = []

        self._load_env_file()
        self._load_config()
        self._build_env_client_chain()

    # ================================================================
    # 初始化
    # ================================================================

    def _load_env_file(self):
        """加载项目根目录 .env 到 os.environ (不覆盖已有值)"""
        project_root = Path(self.config_path).resolve().parent
        # 尝试多个可能的 .env 位置
        for candidate in [
            project_root / ".env",
            project_root.parent / ".env",
            Path.cwd() / ".env",
        ]:
            if candidate.exists():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                k, v = k.strip(), v.strip()
                                if k and k not in os.environ:
                                    os.environ[k] = v
                    logger.info(f"LLMManager: 已加载 .env: {candidate}")
                except Exception as e:
                    logger.warning(f"LLMManager: 加载 .env 失败: {e}")
                break

    def _load_config(self):
        """加载 config.json — 优先 OneAPI 聚合层"""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)

            oneapi_base = config.get("oneapi_base_url")
            oneapi_key = config.get("oneapi_key")

            if oneapi_base and oneapi_key and AsyncOpenAI:
                self.oneapi_client = AsyncOpenAI(
                    api_key=oneapi_key,
                    base_url=oneapi_base,
                )
                self.oneapi_config = {"base_url": oneapi_base, "api_key": oneapi_key}
                logger.info(f"OneAPI 聚合层已激活: {oneapi_base}")

            self.default_model = config.get("default_llm_model", "gpt-4o")
        except Exception as e:
            logger.error(f"加载 LLM 配置失败: {e}")

    def _build_env_client_chain(self):
        """从环境变量构建 Provider fallback 链"""
        if AsyncOpenAI is None:
            logger.warning("openai SDK 未安装，无法构建 env client chain")
            return

        for env_key, base_url_env, default_base, default_model, supports_tools in _ENV_PROVIDER_CHAIN:
            api_key = os.environ.get(env_key, "")
            if not api_key or api_key.startswith("your-") or api_key.startswith("sk-YOUR"):
                continue

            # Anthropic 走不同的 API 格式，暂时跳过 (用 OpenRouter 代替)
            if env_key == "ANTHROPIC_API_KEY":
                continue

            base_url = default_base
            if base_url_env:
                base_url = os.environ.get(base_url_env, default_base)

            try:
                client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                self._env_clients.append({
                    "provider": env_key.replace("_API_KEY", "").replace("_URL", "").lower(),
                    "client": client,
                    "model": default_model,
                    "supports_tools": supports_tools,
                    "env_key": env_key,
                })
                logger.info(f"LLM Provider 就绪: {env_key} → {base_url} ({default_model})")
            except Exception as e:
                logger.warning(f"构建 {env_key} 客户端失败: {e}")

        if not self.oneapi_client and not self._env_clients:
            logger.warning(
                "⚠️ 无可用 LLM Provider！请在 .env 中设置至少一个 API Key "
                "(OPENAI_API_KEY, DEEPSEEK_API_KEY, GROQ_API_KEY 等)"
            )

    # ================================================================
    # 核心 API
    # ================================================================

    def get_client(self) -> Any:
        """获取可用客户端 (OneAPI 优先, 否则 env chain 第一个)"""
        if self.oneapi_client:
            return self.oneapi_client
        if self._env_clients:
            return self._env_clients[0]["client"]
        raise ValueError(
            "无可用 LLM。请配置以下任一:\n"
            "1. config.json → oneapi_base_url + oneapi_key\n"
            "2. .env → OPENAI_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY 等"
        )

    def get_default_model(self) -> str:
        """获取当前默认模型名"""
        if self.oneapi_client:
            return self.default_model
        if self._env_clients:
            return self._env_clients[0]["model"]
        return self.default_model

    async def chat_completion(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
        model_alias: str = None,
        **kwargs,
    ) -> Any:
        """
        统一 Chat Completion — 自动 fallback:
        1. OneAPI (如已配置)
        2. 环境变量 Provider 链 (逐个尝试)
        """
        # 构建候选列表
        candidates = []

        if self.oneapi_client:
            candidates.append({
                "provider": "oneapi",
                "client": self.oneapi_client,
                "model": model_alias or self.default_model,
                "supports_tools": True,
            })

        for ec in self._env_clients:
            candidates.append({
                "provider": ec["provider"],
                "client": ec["client"],
                "model": model_alias or ec["model"],
                "supports_tools": ec["supports_tools"],
            })

        if not candidates:
            raise ValueError(
                "无可用 LLM Provider。请在 Dashboard API CONFIG 中设置 API Key。"
            )

        last_error = None
        for cand in candidates:
            try:
                start_time = datetime.now()

                # 如果 provider 不支持 tools 且 tools 被传入, 跳过
                call_tools = tools if (tools and cand["supports_tools"]) else None

                call_kwargs = {k: v for k, v in kwargs.items() if v is not None}
                response = await cand["client"].chat.completions.create(
                    model=cand["model"],
                    messages=messages,
                    tools=call_tools,
                    **call_kwargs,
                )

                # 记录 usage
                if response.usage:
                    usage_record = TokenUsage(
                        model=cand["model"],
                        input_tokens=response.usage.prompt_tokens or 0,
                        output_tokens=response.usage.completion_tokens or 0,
                        total_cost=0.0,
                        timestamp=start_time.isoformat(),
                    )
                    self.usage_log.append(usage_record)
                    logger.info(
                        f"LLM 调用成功: [{cand['provider']}] {cand['model']}, "
                        f"Tokens: {response.usage.prompt_tokens}/{response.usage.completion_tokens}"
                    )

                return response

            except Exception as e:
                last_error = e
                logger.warning(f"LLM [{cand['provider']}] {cand['model']} 调用失败: {e}")
                continue

        raise ValueError(f"所有 LLM Provider 均失败。最后错误: {last_error}")

    # ================================================================
    # 便捷方法
    # ================================================================

    async def simple_chat(self, user_message: str, system_prompt: str = None) -> str:
        """简单对话 — 返回纯文本回复"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        response = await self.chat_completion(messages=messages)
        return response.choices[0].message.content or ""

    def reload(self):
        """热重载: 重新读取环境变量并重建客户端链"""
        self.oneapi_client = None
        self._env_clients = []
        self._load_config()
        self._build_env_client_chain()
        logger.info(f"LLMManager reload: {len(self._env_clients)} env clients, "
                     f"oneapi={'yes' if self.oneapi_client else 'no'}")

    def is_available(self) -> bool:
        """检查是否有可用的 LLM Provider"""
        return bool(self.oneapi_client or self._env_clients)

    def get_provider_status(self) -> List[Dict[str, Any]]:
        """获取所有 Provider 状态"""
        result = []
        if self.oneapi_client:
            result.append({
                "provider": "oneapi",
                "model": self.default_model,
                "source": "config.json",
                "active": True,
            })
        for ec in self._env_clients:
            result.append({
                "provider": ec["provider"],
                "model": ec["model"],
                "source": f".env ({ec['env_key']})",
                "active": True,
                "supports_tools": ec["supports_tools"],
            })
        return result

    def get_usage_summary(self) -> Dict[str, Any]:
        """获取 Token 使用统计"""
        total_cost = sum(u.total_cost for u in self.usage_log)
        by_model: Dict[str, Dict] = {}
        for u in self.usage_log:
            if u.model not in by_model:
                by_model[u.model] = {"input": 0, "output": 0, "cost": 0.0}
            by_model[u.model]["input"] += u.input_tokens
            by_model[u.model]["output"] += u.output_tokens
            by_model[u.model]["cost"] += u.total_cost

        return {
            "total_cost": total_cost,
            "by_model": by_model,
            "history_count": len(self.usage_log),
        }
