"""core/llm_types.py — 路由层的**共用契约**:任务类型、提供商配置、一次回答。

从 ``core/multi_llm_router.py`` 拆出来的。拆的理由不是"那个文件太长"这种笼统的话,
是一件具体的事:适配器要用这几个类型,路由器也要用,而适配器本身又该从路由器里
搬出去(见 ``core/llm_adapters.py``)。共用的东西留在其中一边,另一边就得反向 import,
于是两个模块互相 import —— 循环 import 的坑不会在写的时候暴露,会在某天换了一处
import 顺序之后突然炸,而且报错指向的位置与真正的原因毫无关系。

所以把契约单独放一层:这一层**不 import 本仓任何别的模块**,谁都可以放心 import 它。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class TaskType(Enum):
    """任务类型 → 决定模型选择策略"""

    REASONING = "reasoning"  # 复杂推理 → 强模型
    FAST_RESPONSE = "fast_response"  # 快速问答 → 快模型
    CODING = "coding"  # 代码生成 → 代码模型
    CREATIVE = "creative"  # 创作 → 创意模型
    ANALYSIS = "analysis"  # 分析 → 均衡模型
    PLANNING = "planning"  # 规划 → 强推理模型
    AGENT_CONTROL = "agent_control"  # Agent 指令生成
    GENERAL = "general"


class ProviderStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class ProviderConfig:
    """单个提供商配置"""

    name: str
    api_key: str
    base_url: str
    models: List[str]
    default_model: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_json_mode: bool = True
    timeout: float = 60.0
    multimodal: bool = False  # 是否原生支持多模态（图像/音频/视频输入）
    env_key: str = ""  # 对应的环境变量名（用于可用性提示）
    # PR-HA: 硬件感知 + 多模态优先新增字段
    source_type: str = "api"  # "api" / "local" / "hf_local" / "oneapi"
    hardware_tier: str = "remote"  # "gpu_full" / "gpu_quantized" / "cpu" / "remote"
    supports_vision: bool = False  # 是否支持图像输入（VLM能力）
    supports_audio: bool = False  # 是否支持音频输入
    kv_cache_enabled: bool = False  # 是否启用KV cache（借鉴vLLM）
    prefix_cache_enabled: bool = False  # 是否启用前缀缓存（借鉴SGLang RadixAttention）
    quantization: str = "none"  # "none" / "q4" / "q5" / "q8" / "awq" / "gptq"
    # 运行时状态
    status: ProviderStatus = ProviderStatus.HEALTHY
    latency_avg_ms: float = 0.0
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None
    last_used: float = 0.0
    down_since: float = 0.0  # 标记为 DOWN 的时刻(见 is_available())

    def __post_init__(self) -> None:
        # base_url 规范化收口在类型本身:任何构造路径(发现/面板保存/持久化
        # 恢复)传进无协议头或空的 URL,都在这里一次修好,而不是指望每个
        # 调用点自己记得。空值对本地 provider 回退默认地址,避免运行时
        # 才炸 "Request URL is missing an 'http://' or 'https://' protocol."
        raw = (self.base_url or "").strip()
        if not raw and self.name == "ollama":
            raw = os.environ.get("OLLAMA_URL", "").strip() or "http://localhost:11434"
        if raw and not raw.startswith(("http://", "https://")):
            raw = f"http://{raw}"
        self.base_url = raw

    def is_available(self, recovery_seconds: float = 60.0) -> bool:
        """该 provider 现在是否该被当作候选。

        修复:status 字段一旦被打成 DOWN(连续 5 次失败),此前【没有任何自愈
        路径】——route()/route_multimodal_first()/select_brain_for_task() 等
        十几处候选筛选全部一律排除 DOWN,而重新变回候选的唯一办法是成功调用
        一次；但 DOWN 的 provider 永远不会被选为候选,自然也永远没机会成功调用，
        于是一旦 DOWN 就【整个进程生命周期】卡死,除非手动触发 refresh_llm_router()
        (保存一次 llm 类配置)或重启——同一个类里的断路器(ProviderCircuitBreaker)
        反而设计对了(OPEN 到期自动进 HALF_OPEN 重新试探)，两套健康判断互相矛盾。
        这里让 DOWN 状态也按同样的冷却窗口自动过期，恢复候选资格，真正出问题时
        断路器仍会在 chat() 调用前再拦一道。
        """
        if self.status != ProviderStatus.DOWN:
            return True
        return bool(self.down_since) and (time.time() - self.down_since) >= recovery_seconds


@dataclass
class RoutingDecision:
    """路由决策"""

    provider: str
    model: str
    reason: str
    alternatives: List[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """统一响应"""

    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    tool_calls: Optional[List[Dict]] = None
    raw_response: Optional[Dict] = None
    # L2 级联路由元数据
    cascade_stage: int = 0  # 0-based:第几档答出来的(0=最便宜那档)
    cascade_escalated: bool = False  # 是否发生过升级(便宜档不合格才升到更贵档)
