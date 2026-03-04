"""
UFO Galaxy - LLM 成本可观测性模块（Cost Tracker）
================================================

功能：
1. 记录每次 LLM 调用的 provider、model、token 数量、成本估算
2. 持久化到 JSONL 文件（data/cost_records.jsonl）
3. 提供 API 读取最近 N 条成本记录

使用方法：
    from core.cost_tracker import get_cost_tracker

    tracker = get_cost_tracker()

    # 记录一次调用
    tracker.record(
        provider="openai",
        model="gpt-4o",
        input_tokens=500,
        output_tokens=200,
        task_type="general",
        device_id="device-001",
    )

    # 读取最近 50 条
    records = tracker.get_recent(50)

    # 获取汇总统计
    summary = tracker.get_summary()
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.CostTracker")

# 默认成本表（每千 token 的美元价格）
DEFAULT_COST_TABLE: Dict[str, Dict[str, float]] = {
    "openai": {"input": 0.005, "output": 0.015},
    "anthropic": {"input": 0.003, "output": 0.015},
    "deepseek": {"input": 0.00014, "output": 0.00028},
    "groq": {"input": 0.00059, "output": 0.00079},
    "ollama": {"input": 0.0, "output": 0.0},
    "oneapi": {"input": 0.005, "output": 0.015},
}


@dataclass
class CostRecord:
    """单次 LLM 调用成本记录"""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    task_type: str = "general"
    device_id: str = ""
    latency_ms: float = 0.0
    success: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)


class CostTracker:
    """
    LLM 成本追踪器

    - 记录调用成本到内存 + JSONL 文件
    - 提供统计和查询接口
    """

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data"
        )
        os.makedirs(self._data_dir, exist_ok=True)
        self._log_file = os.path.join(self._data_dir, "cost_records.jsonl")
        # 最近 500 条保存在内存中供快速查询
        self._records: List[CostRecord] = []
        self._load_recent(500)

    # ================================================================
    # 记录
    # ================================================================

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        task_type: str = "general",
        device_id: str = "",
        latency_ms: float = 0.0,
        success: bool = True,
        cost_per_1k_input: Optional[float] = None,
        cost_per_1k_output: Optional[float] = None,
    ) -> CostRecord:
        """记录一次 LLM 调用成本"""
        # 成本估算
        cost_table = DEFAULT_COST_TABLE.get(provider, {"input": 0.005, "output": 0.015})
        c_in = cost_per_1k_input if cost_per_1k_input is not None else cost_table["input"]
        c_out = cost_per_1k_output if cost_per_1k_output is not None else cost_table["output"]
        estimated_cost = (input_tokens / 1000.0 * c_in) + (output_tokens / 1000.0 * c_out)

        rec = CostRecord(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=round(estimated_cost, 8),
            task_type=task_type,
            device_id=device_id,
            latency_ms=latency_ms,
            success=success,
        )

        # 内存缓存
        self._records.append(rec)
        if len(self._records) > 500:
            self._records = self._records[-500:]

        # 持久化
        self._append_to_file(rec)

        logger.debug(
            f"Cost recorded: {provider}/{model} "
            f"in={input_tokens} out={output_tokens} "
            f"cost=${estimated_cost:.6f}"
        )
        return rec

    # ================================================================
    # 查询
    # ================================================================

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """获取最近 N 条成本记录"""
        return [r.to_dict() for r in self._records[-limit:]]

    def get_summary(self) -> Dict:
        """获取成本汇总统计"""
        if not self._records:
            return {
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_usd": 0.0,
                "by_provider": {},
            }

        by_provider: Dict[str, Dict] = {}
        total_cost = 0.0
        total_in = 0
        total_out = 0

        for r in self._records:
            total_cost += r.estimated_cost_usd
            total_in += r.input_tokens
            total_out += r.output_tokens
            p = r.provider
            if p not in by_provider:
                by_provider[p] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            by_provider[p]["calls"] += 1
            by_provider[p]["input_tokens"] += r.input_tokens
            by_provider[p]["output_tokens"] += r.output_tokens
            by_provider[p]["cost_usd"] = round(by_provider[p]["cost_usd"] + r.estimated_cost_usd, 8)

        return {
            "total_calls": len(self._records),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_cost_usd": round(total_cost, 8),
            "by_provider": by_provider,
        }

    # ================================================================
    # 持久化
    # ================================================================

    def _append_to_file(self, rec: CostRecord) -> None:
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Cost record save failed: {e}")

    def _load_recent(self, limit: int = 500) -> None:
        """从文件加载最近 N 条记录到内存"""
        if not os.path.exists(self._log_file):
            return
        try:
            lines = []
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            # 只取最后 limit 行
            _fields = list(CostRecord.__dataclass_fields__.keys())
            for line in lines[-limit:]:
                data = json.loads(line)
                self._records.append(CostRecord(**{
                    k: data[k] for k in _fields if k in data
                }))
            logger.info(f"Loaded {len(self._records)} cost records from file")
        except Exception as e:
            logger.warning(f"Cost record load failed: {e}")


# ============================================================================
# 单例
# ============================================================================

_tracker_instance: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CostTracker()
    return _tracker_instance
