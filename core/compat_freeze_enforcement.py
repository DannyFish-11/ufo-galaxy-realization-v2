"""PR-11: compat freeze enforcement.

Turns the existing compatibility inventories into a machine-checkable freeze
budget so new work cannot silently expand the compat footprint without making
that decision explicit.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

COMPAT_FREEZE_ENFORCEMENT_IS_AUTHORITY = "COMPAT_FREEZE_ENFORCEMENT::COMPAT_BUDGET_IS_FROZEN_AT_PR11_V1"
COMPAT_FREEZE_ENFORCEMENT_PR11_SENTINEL = (
    "COMPAT_FREEZE_ENFORCEMENT::NO_NEW_COMPAT_SURFACES_WITHOUT_EXPLICIT_BUDGET_CHANGE_V1"
)
NO_NEW_COMPAT_SURFACES_AFTER_PR11_POLICY = (
    "NO_NEW_COMPAT_SURFACES_AFTER_PR11_POLICY_V1: "
    "After PR-11 the compat inventory is frozen. New compat surfaces require "
    "an explicit budget update and canonical replacement declaration."
)
COMPAT_BUDGET_MUST_NOT_GROW_POLICY = (
    "COMPAT_BUDGET_MUST_NOT_GROW_POLICY_V1: "
    "The total counts of compat retirement records, legacy path records, and "
    "production-baseline legacy declarations must not grow silently."
)
COMPAT_SURFACES_REQUIRE_CANONICAL_REPLACEMENT_POLICY = (
    "COMPAT_SURFACES_REQUIRE_CANONICAL_REPLACEMENT_POLICY_V1: "
    "Every compat surface retained after the freeze point must carry a clear "
    "canonical replacement and removal condition."
)

FROZEN_COMPAT_SURFACE_BUDGET = 10
# 82 → 81:``core.api_manager.APIManager._validate_oneapi`` 那条 legacy 路径随模块
# 一并删除后(main 的 PR #1562),注册表真实条目数少了一条。
#
# 冻结预算的意义是「钉住当前值、只准降不准升」,留在 82 等于白送一个额度给将来
# 新增的 legacy 路径。棘轮下调才是这道门该有的行为 —— 所以是往下调,而不是把断言
# 放宽成 <=。
#
# 这里有两道判定,只看其中一道会得出相反的结论(两边的注释各看到了一半,一并记下):
#   * ``check_compat_freeze`` 的门是**上限**(``count > budget`` 才算违规)——
#     真删掉一条之后不下调,这道门确实不会红;
#   * 而 ``test_default_snapshot_matches_frozen_budgets`` 断的是**相等**
#     (``count == budget``)—— 它当时就红了(assert 81 == 82)。
# 也就是说"不下调也不会红"只对门成立,对测试不成立。棘轮要真起作用,靠的正是
# 那条相等断言:它逼着删完之后必须同步下调,否则额度会悄悄留下来。
FROZEN_LEGACY_PATH_BUDGET = 81
FROZEN_PRODUCTION_BASELINE_LEGACY_BUDGET = 2


@dataclasses.dataclass(frozen=True)
class CompatFreezeSnapshot:
    """Serializable snapshot of compat freeze status."""

    compat_surface_count: int
    legacy_path_count: int
    production_baseline_legacy_count: int
    frozen_compat_surface_budget: int = FROZEN_COMPAT_SURFACE_BUDGET
    frozen_legacy_path_budget: int = FROZEN_LEGACY_PATH_BUDGET
    frozen_production_baseline_legacy_budget: int = FROZEN_PRODUCTION_BASELINE_LEGACY_BUDGET
    violations: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": COMPAT_FREEZE_ENFORCEMENT_IS_AUTHORITY,
            "pr_sentinel": COMPAT_FREEZE_ENFORCEMENT_PR11_SENTINEL,
            "compat_surface_count": self.compat_surface_count,
            "legacy_path_count": self.legacy_path_count,
            "production_baseline_legacy_count": self.production_baseline_legacy_count,
            "frozen_compat_surface_budget": self.frozen_compat_surface_budget,
            "frozen_legacy_path_budget": self.frozen_legacy_path_budget,
            "frozen_production_baseline_legacy_budget": (self.frozen_production_baseline_legacy_budget),
            "is_frozen": len(self.violations) == 0,
            "violations": list(self.violations),
            "policy_sentinels": [
                NO_NEW_COMPAT_SURFACES_AFTER_PR11_POLICY,
                COMPAT_BUDGET_MUST_NOT_GROW_POLICY,
                COMPAT_SURFACES_REQUIRE_CANONICAL_REPLACEMENT_POLICY,
            ],
        }


def build_compat_freeze_snapshot(
    *,
    compat_surface_count: Optional[int] = None,
    legacy_path_count: Optional[int] = None,
    production_baseline_legacy_count: Optional[int] = None,
) -> CompatFreezeSnapshot:
    """Build the current compat-freeze snapshot."""

    if compat_surface_count is None:
        from core.compat_surface_retirement import get_compat_surface_inventory

        compat_surface_count = len(get_compat_surface_inventory())
    if legacy_path_count is None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY

        legacy_path_count = len(LEGACY_PATH_REGISTRY)
    if production_baseline_legacy_count is None:
        from core.production_baseline import LEGACY_PATH_DECLARATIONS

        production_baseline_legacy_count = len(LEGACY_PATH_DECLARATIONS)

    violations: List[str] = []
    if compat_surface_count > FROZEN_COMPAT_SURFACE_BUDGET:
        violations.append("compat_surface_retirement inventory exceeds frozen PR-11 budget")
    if legacy_path_count > FROZEN_LEGACY_PATH_BUDGET:
        violations.append("orchestration_authority legacy path registry exceeds frozen PR-11 budget")
    if production_baseline_legacy_count > FROZEN_PRODUCTION_BASELINE_LEGACY_BUDGET:
        violations.append("production baseline legacy declaration count exceeds frozen PR-11 budget")

    return CompatFreezeSnapshot(
        compat_surface_count=compat_surface_count,
        legacy_path_count=legacy_path_count,
        production_baseline_legacy_count=production_baseline_legacy_count,
        violations=violations,
    )


def build_compat_freeze_summary(
    *,
    compat_surface_count: Optional[int] = None,
    legacy_path_count: Optional[int] = None,
    production_baseline_legacy_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Return a JSON-safe compat-freeze summary."""

    return build_compat_freeze_snapshot(
        compat_surface_count=compat_surface_count,
        legacy_path_count=legacy_path_count,
        production_baseline_legacy_count=production_baseline_legacy_count,
    ).to_dict()
