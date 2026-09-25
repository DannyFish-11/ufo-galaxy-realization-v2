"""core/meta/operators — 三个算子的登记表。

一个 Kernel、三个算子、每个算子一个可写面（见 :mod:`core.meta.kernel`）：

* ``data_rsi``    —— 放大已有能力并标定其边界；可写面 ``core/eval/cases/``、``config/assessment_claims.json``
* ``harness_rsi`` —— 编辑脚手架，不碰权重；可写面 ``config/genomes/``
* ``model_rsi``   —— 经有界训练内化进参数；阶段一只留接口，不开写

登记表只存构造函数，按名字取用 —— 导入本包不会实例化任何算子。算子模块在自己的文件里
定义，并在这里的 ``OPERATOR_REGISTRY`` 字面量里登记。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def _harness_rsi() -> Any:
    from core.meta.operators.harness_rsi import HarnessRSIOperator

    return HarnessRSIOperator()


#: 名字 → 构造函数。
OPERATOR_REGISTRY: Dict[str, Callable[[], Any]] = {"harness_rsi": _harness_rsi}


def registered_operators() -> List[str]:
    return sorted(OPERATOR_REGISTRY)


def build_operator(name: str) -> Any:
    try:
        factory = OPERATOR_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"没有登记名为 {name!r} 的算子；已登记：{registered_operators()}") from exc
    return factory()


__all__ = ["OPERATOR_REGISTRY", "build_operator", "registered_operators"]
