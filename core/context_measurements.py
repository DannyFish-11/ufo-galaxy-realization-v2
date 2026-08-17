"""core/context_measurements.py — 上下文相关的**实测值**，压过目录里的声明
========================================================================

目录(:mod:`core.model_catalog`)里的 ``kv_mb_per_1k_val`` / ``max_ctx_val`` 是
**声明的假设** —— 有人填过就有，没人填过就是 0。这个模块存的是另一种东西：
**这台机器上真的量到了什么**。

为什么要把这两样分开
====================
上一轮做上下文预算时留了一个洞：六个型号的 ``kv_mb_per_1k_val`` 全是 0，于是
``context_budget_for`` 里那整段显存判断**一次都没执行过**。它有调用方，
``check_wiring`` 因此过得去 —— 但它永远不触发，是标准的"接了等于没接"。

而那一栏之所以全是 0，是因为**没人能凭空写出这个数**：KV 单价取决于层数、
KV 头数、头维度、KV 量化类型，还取决于具体的 llama.cpp 构建。写进目录就是又一个
"底下压着假设"的常数 —— 正是这一系列改动一直在拆的东西。

**所以正确的做法不是去猜，是去量。** 加载一次模型，就知道它在这台机器上、这个
上下文长度下，实际吃掉了多少显存 —— 减去权重驻留，除以上下文长度，就是单价。

口径
====
* 目录 = 声明的假设(可以为 0 = 没人填过)；
* 本模块 = 实测的事实(没量过就没有这一条)；
* **实测优先** —— 消费方先问这里，没有再退回目录。

这与 ``runtime_mb_val`` 的立场一致，只是更进一步：那一栏是"量过一次、写进源码"，
这里是"每台机器自己量、自己存"。机器换了、量化换了、llama.cpp 换了，这个数跟着变，
而源码不用动。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from core.atomic_json import atomic_write_json

logger = logging.getLogger("Galaxy.ContextMeasurements")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
#: 与 model_state.json 同一个目录 —— 都是"这台机器的运行时事实"。
_FILE = PROJECT_ROOT / "runtime" / "context_measurements.json"

#: 低于这个值的 KV 单价一律不信。
#:
#: 量出来的差值里混着显存碎片、驱动开销、别的进程 —— 噪声完全可能把结果压到 0 甚至
#: 负数。一个**偏小**的单价会让上下文被开得过大，加载时 OOM;所以宁可判"没量到"。
_MIN_CREDIBLE_KV_MB_PER_1K = 1

#: 高于这个值同样不信 —— 那多半是量的时候有别的东西在抢显存。
_MAX_CREDIBLE_KV_MB_PER_1K = 4096


def _read() -> Dict[str, Dict[str, float]]:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception as exc:  # noqa: BLE001 — 读不到就是没量过，不是错误
        logger.debug("上下文实测值读取失败(按没量过处理): %s", exc)
    return {}


def kv_mb_per_1k(tag: str) -> int:
    """这个型号在**这台机器**上实测的 KV 单价(MB / 1K token)；没量过返回 0。

    返回 0 的语义与目录那一栏一致：**"不知道"，不是"不要钱"**。调用方据此决定
    敢不敢拿显存去缩上下文 —— 不知道就不敢。
    """
    if os.environ.get("GALAXY_IGNORE_CONTEXT_MEASUREMENTS", "").strip().lower() in ("1", "true", "yes", "on"):
        return 0
    rec = _read().get(tag) or {}
    raw = rec.get("kv_mb_per_1k")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        # 这里的 0 和正常路径的 0 **不是一回事**:正常路径的 0 表示"还没量过",
        # 而这里表示"量过、但记录坏了"。两者对调用方的后续动作其实相同(都不敢按
        # 显存放开),所以仍然返回 0;但必须**说出来** —— 否则一个损坏的
        # context_measurements.json 会永远伪装成"这台机器还没量过",而重新量一次
        # 本来就能修好它。
        logger.warning("%s 的 KV 单价记录损坏(值=%r)，按未量过处理；删掉 %s 重新加载一次即可重量", tag, raw, _FILE)
        return 0


def record_kv_cost(tag: str, *, n_ctx: int, kv_mb: float) -> Optional[int]:
    """记下一次实测：*n_ctx* 长度的上下文吃了 *kv_mb* MB 显存。返回换算出的单价。

    不可信的一律**不记**(返回 ``None``)——宁可保持"没量过"，也不要把一个噪声值
    写进去当事实。判据见 ``_MIN_CREDIBLE_KV_MB_PER_1K`` / ``_MAX_CREDIBLE_KV_MB_PER_1K``。
    """
    if not tag or n_ctx <= 0 or kv_mb <= 0:
        return None
    per_1k = int(round(kv_mb / (n_ctx / 1024.0)))
    if not (_MIN_CREDIBLE_KV_MB_PER_1K <= per_1k <= _MAX_CREDIBLE_KV_MB_PER_1K):
        logger.debug("KV 单价 %s MB/1K 不在可信区间，不记(tag=%s n_ctx=%s kv_mb=%s)", per_1k, tag, n_ctx, kv_mb)
        return None

    data = _read()
    data[tag] = {"kv_mb_per_1k": per_1k, "measured_at_n_ctx": int(n_ctx), "measured_kv_mb": round(float(kv_mb), 1)}
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_FILE, data, indent=2, ensure_ascii=False)
        logger.info("记下 %s 的 KV 单价：%s MB/1K token（在 n_ctx=%s 下实测 %.1f MB）", tag, per_1k, n_ctx, kv_mb)
    except Exception as exc:  # noqa: BLE001 — 记不下来不影响本次加载
        logger.debug("上下文实测值写入失败(不影响本次加载): %s", exc)
    return per_1k


def effective_kv_mb_per_1k(tag: str) -> int:
    """KV 单价的**唯一取值处**：实测优先，其次目录声明，都没有返回 0。

    分成两处存、在这里合，是为了让"这个数从哪来"永远说得清 —— 而不是在调用点上
    写一串 ``measured or declared or 0``，那种写法迟早会在某个调用点漏掉一层。
    """
    measured = kv_mb_per_1k(tag)
    if measured > 0:
        return measured
    try:
        from core.model_catalog import exact_model  # noqa: PLC0415

        spec = exact_model(tag)
        return spec.kv_mb_per_1k() if spec is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def measured_source(tag: str) -> str:
    """这个单价是**量来的**还是**目录里写的** —— 给理由串用，一个词。"""
    if kv_mb_per_1k(tag) > 0:
        return "实测"
    try:
        from core.model_catalog import exact_model  # noqa: PLC0415

        spec = exact_model(tag)
        if spec is not None and spec.kv_mb_per_1k() > 0:
            return "目录声明"
    except Exception:  # noqa: BLE001
        pass
    return "未知"
