"""
core/tool_guardian.py
======================
C阶段 2C — 工具/MCP 调用守护与回滚

功能：
  B: 风险/权限评分 + 拦截（工具调用前评分，超阈值拦截）
  A: 失败回滚/重试（工具调用失败时可回滚或重试）

设计原则：
  - 默认不影响现有路径：仅当 GuardedCallConfig.enabled=True 时生效
  - 向后兼容：直接调用 call_with_guardian() 包装任意 async callable
  - 风险等级复用 ToolRiskLevel（来自 core/tool_permissions.py）
  - 可通过配置关闭守护（CI/测试环境不阻塞）

使用示例:
    from core.tool_guardian import call_with_guardian, GuardedCallConfig

    cfg = GuardedCallConfig(enabled=True, max_retries=2, rollback_fn=my_rollback)
    result = await call_with_guardian(
        fn=mcp_loader.call_tool,
        fn_args=("server_id", "tool_name", args),
        tool_name="tool_name",
        config=cfg,
    )
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("Galaxy.ToolGuardian")


# ============================================================================
# 风险等级（与 tool_permissions.py 一致）
# ============================================================================

class ToolRiskLevel(str, Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


# ============================================================================
# 内置风险评分规则（可通过 GuardedCallConfig.extra_rules 扩展）
# ============================================================================

_DEFAULT_RISK_RULES: List[Dict[str, Any]] = [
    # pattern（子串匹配，小写）→ risk_level, score
    {"pattern": "delete",       "level": ToolRiskLevel.DANGEROUS, "score": 0.8},
    {"pattern": "remove",       "level": ToolRiskLevel.DANGEROUS, "score": 0.75},
    {"pattern": "format",       "level": ToolRiskLevel.CRITICAL,  "score": 0.95},
    {"pattern": "system_cmd",   "level": ToolRiskLevel.CRITICAL,  "score": 0.95},
    {"pattern": "exec",         "level": ToolRiskLevel.CRITICAL,  "score": 0.90},
    {"pattern": "write",        "level": ToolRiskLevel.MODERATE,  "score": 0.5},
    {"pattern": "upload",       "level": ToolRiskLevel.MODERATE,  "score": 0.5},
    {"pattern": "screenshot",   "level": ToolRiskLevel.SAFE,      "score": 0.1},
    {"pattern": "read",         "level": ToolRiskLevel.SAFE,      "score": 0.1},
    {"pattern": "list",         "level": ToolRiskLevel.SAFE,      "score": 0.05},
    {"pattern": "search",       "level": ToolRiskLevel.SAFE,      "score": 0.05},
]

# 拦截阈值：score >= this → blocked
_DEFAULT_BLOCK_SCORE = 0.95  # 仅 CRITICAL 级默认拦截


# ============================================================================
# 守护配置
# ============================================================================

@dataclass
class GuardedCallConfig:
    """工具调用守护配置。

    Attributes:
        enabled:          是否启用守护（False = 直通，不影响现有代码）
        max_retries:      调用失败最多重试次数（0 = 不重试）
        retry_delay_s:    重试间隔（秒）
        block_score:      风险得分 >= 此值时拦截调用（默认 0.95）
        rollback_fn:      可选异步回滚函数，签名 async (tool_name, args, result) -> None
        extra_rules:      追加的风险评分规则（格式同 _DEFAULT_RISK_RULES）
        audit_log:        是否记录调用日志（默认 True）
    """
    enabled: bool = False
    max_retries: int = 1
    retry_delay_s: float = 0.5
    block_score: float = _DEFAULT_BLOCK_SCORE
    rollback_fn: Optional[Callable[..., Coroutine]] = None
    extra_rules: List[Dict[str, Any]] = field(default_factory=list)
    audit_log: bool = True


# ============================================================================
# 风险评分
# ============================================================================

def score_tool_risk(tool_name: str, extra_rules: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """计算工具调用风险得分。

    Returns:
        {
            "score": float,          # 0.0 ~ 1.0
            "level": ToolRiskLevel,
            "matched_pattern": str,
        }
    """
    name_lower = tool_name.lower()
    rules = _DEFAULT_RISK_RULES + (extra_rules or [])

    best: Dict[str, Any] = {
        "score": 0.1,
        "level": ToolRiskLevel.SAFE,
        "matched_pattern": "(default)",
    }
    for rule in rules:
        if rule["pattern"] in name_lower:
            if rule["score"] > best["score"]:
                best = {
                    "score": rule["score"],
                    "level": rule["level"],
                    "matched_pattern": rule["pattern"],
                }
    return best


# ============================================================================
# 审计日志（内存 ring-buffer，最近 200 条）
# ============================================================================

_AUDIT_RING: List[Dict[str, Any]] = []
_AUDIT_MAX = 200


def _audit(entry: Dict[str, Any]) -> None:
    global _AUDIT_RING
    _AUDIT_RING.append(entry)
    if len(_AUDIT_RING) > _AUDIT_MAX:
        _AUDIT_RING = _AUDIT_RING[-_AUDIT_MAX:]


def get_guardian_audit_log(n: int = 50) -> List[Dict[str, Any]]:
    """返回最近 n 条守护审计日志（供 API 接口暴露）。"""
    return list(_AUDIT_RING[-n:])


# ============================================================================
# 核心: call_with_guardian
# ============================================================================

async def call_with_guardian(
    fn: Callable[..., Coroutine],
    fn_args: tuple = (),
    fn_kwargs: Dict[str, Any] = None,
    tool_name: str = "unknown_tool",
    config: Optional[GuardedCallConfig] = None,
) -> Any:
    """守护包装器：对任意 async callable 进行风险拦截 + 失败重试/回滚。

    当 config.enabled=False（默认）时直接透传，不影响现有代码路径。

    Args:
        fn:         要调用的异步函数
        fn_args:    位置参数
        fn_kwargs:  关键字参数
        tool_name:  工具名（用于风险评分和日志）
        config:     守护配置（None = 使用默认配置 enabled=False）

    Returns:
        fn 的返回值

    Raises:
        ToolGuardianBlockedError: 风险得分超过阈值时
        最后一次重试仍失败时重新抛出原始异常
    """
    cfg = config or GuardedCallConfig()
    fn_kwargs = fn_kwargs or {}

    # 直通路径（守护未启用）
    if not cfg.enabled:
        return await fn(*fn_args, **fn_kwargs)

    # ── 风险评分 ──
    risk = score_tool_risk(tool_name, cfg.extra_rules)
    t_start = time.monotonic()

    if cfg.audit_log:
        _audit({
            "event": "pre_call",
            "tool": tool_name,
            "risk_score": risk["score"],
            "risk_level": risk["level"],
            "ts": t_start,
        })

    if risk["score"] >= cfg.block_score:
        reason = (
            f"[ToolGuardian] 工具调用被拦截: tool={tool_name} "
            f"score={risk['score']:.2f} (>= {cfg.block_score}) "
            f"level={risk['level']} pattern={risk['matched_pattern']}"
        )
        logger.warning(reason)
        if cfg.audit_log:
            _audit({"event": "blocked", "tool": tool_name, "reason": reason, "ts": time.monotonic()})
        raise ToolGuardianBlockedError(reason, tool_name=tool_name, risk=risk)

    # ── 执行 + 重试 ──
    last_exc: Optional[Exception] = None
    last_result: Any = None
    attempts = 0

    for attempt in range(cfg.max_retries + 1):
        attempts = attempt + 1
        try:
            result = await fn(*fn_args, **fn_kwargs)
            latency_ms = (time.monotonic() - t_start) * 1000
            if cfg.audit_log:
                _audit({
                    "event": "success",
                    "tool": tool_name,
                    "attempt": attempts,
                    "latency_ms": round(latency_ms, 1),
                    "ts": time.monotonic(),
                })
            logger.debug(
                "[ToolGuardian] 调用成功: tool=%s attempt=%d latency=%.1fms",
                tool_name, attempts, latency_ms,
            )
            return result

        except Exception as exc:
            last_exc = exc
            last_result = None
            logger.warning(
                "[ToolGuardian] 调用失败 (attempt %d/%d): tool=%s err=%s",
                attempts, cfg.max_retries + 1, tool_name, exc,
            )
            if cfg.audit_log:
                _audit({
                    "event": "failure",
                    "tool": tool_name,
                    "attempt": attempts,
                    "error": str(exc),
                    "ts": time.monotonic(),
                })

            # 若未到最大重试次数，等待后继续
            if attempt < cfg.max_retries:
                await asyncio.sleep(cfg.retry_delay_s)
            else:
                # 最终失败：尝试回滚
                if cfg.rollback_fn is not None:
                    try:
                        await cfg.rollback_fn(tool_name, fn_args, fn_kwargs, exc)
                        if cfg.audit_log:
                            _audit({
                                "event": "rollback_ok",
                                "tool": tool_name,
                                "ts": time.monotonic(),
                            })
                        logger.info("[ToolGuardian] 回滚完成: tool=%s", tool_name)
                    except Exception as rb_exc:
                        logger.error("[ToolGuardian] 回滚失败: tool=%s err=%s", tool_name, rb_exc)
                        if cfg.audit_log:
                            _audit({
                                "event": "rollback_failed",
                                "tool": tool_name,
                                "error": str(rb_exc),
                                "ts": time.monotonic(),
                            })
                raise last_exc

    # should never reach here
    raise RuntimeError(f"[ToolGuardian] 意外结束: tool={tool_name}")


# ============================================================================
# 异常
# ============================================================================

class ToolGuardianBlockedError(Exception):
    """工具调用被风险评分拦截时抛出。"""

    def __init__(self, message: str, tool_name: str = "", risk: Dict = None):
        super().__init__(message)
        self.tool_name = tool_name
        self.risk = risk or {}


# ============================================================================
# 便捷: 带守护的 MCP 调用
# ============================================================================

async def guarded_mcp_call(
    mcp_loader_instance: Any,
    server_id: str,
    tool_name: str,
    arguments: Dict[str, Any] = None,
    config: Optional[GuardedCallConfig] = None,
) -> Dict[str, Any]:
    """对 MCPLoader.call_tool 的守护包装（可选启用）。

    等价于 mcp_loader.call_tool(server_id, tool_name, arguments)，
    但当 config.enabled=True 时会先进行风险评分和失败重试/回滚。
    """
    return await call_with_guardian(
        fn=mcp_loader_instance.call_tool,
        fn_args=(server_id, tool_name),
        fn_kwargs={"arguments": arguments or {}},
        tool_name=tool_name,
        config=config,
    )
