"""core.health_evidence_policy — 「没有健康证据的设备算几分」，只此一处

要解决什么
==========
本仓有**两套**设备健康登记，各自对「这台设备我从没测过」给出**满分**：

===============================================  =============  =====================
登记表                                            无记录时        谁在用
===============================================  =============  =====================
``core.unified.device_health.DeviceHealthScorer``  ``1.0`` 满分   UDM 的 get_device_health
``core.control_plane.device_health_registry``      ``100.0`` 满分 device_pool_manager
                                                                 → constellation_runtime
===============================================  =============  =====================

后者是**活的选择路径**。实测（走活的 ``device_pool_manager``）：

    从没测过的设备      _health_score() = 100.0
    实测很差的设备      _health_score() =  29.83
    → 零证据胜出，被 max(candidates, key=score) 选中

也就是说：**一台可能根本是死的设备，会排在一台实测很差但确实在工作的设备前面。**

而 ``core/cross_device_responsiveness_contract.py`` 里明写着相反的策略 ——
``EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY``：证据缺失必须下调，绝不乐观上调。
两边对同一件事的判断是反的，而各自看都很合理（"新设备先给个面子" vs "没证据不能算好"）。

判据
====
证据缺失既不是「好」也不是「坏」，是**未知**。所以取中性：

* **绝不排在实测健康的设备前面** —— 那是当前这条缺陷，会让可能已经死掉的设备优先接活。
* **也不至于饿死** —— 排在实测很差的设备之后就意味着一台新设备永远拿不到第一次机会，
  而它的健康分只能靠接活才积累得出来。那是另一种死锁。

于是落在中点。这不是一个精调出来的数，是「未知就该在已知好与已知坏之间」这条判断的
直接后果 —— 真要调，调的是这条判断，不是这个数。

``DeviceHealthScorer.score()`` 原来的 docstring 把 1.0 称作 "neutral score"，而 1.0 是
它的**上界**。命名上的这一步错位正是缺陷的源头：把满分叫成中性，就没人会觉得它可疑。
"""

from __future__ import annotations

__all__ = [
    "NO_EVIDENCE_FRACTION",
    "has_health_evidence",
    "no_evidence_score",
]

#: 未知设备的健康分占满分的比例。中点 —— 见模块头的判据。
NO_EVIDENCE_FRACTION: float = 0.5


def no_evidence_score(scale_max: float = 1.0) -> float:
    """返回「无健康证据」时应当给的分数。

    Args:
        scale_max: 该登记表的满分。``DeviceHealthScorer`` 是 ``1.0``，
            ``DeviceHealthRegistry`` 是 ``100.0``。两套刻度不同是历史遗留，
            但**判据必须同源**，所以由本函数按刻度换算，而不是两边各写一个字面量。

    Returns:
        中性分。
    """
    return float(scale_max) * NO_EVIDENCE_FRACTION


def has_health_evidence(sample_count: int) -> bool:
    """这台设备有没有健康证据。

    单独暴露出来，是因为「分数」和「有没有证据」是**两件事**，而把它们压成一个数正是
    上面那条缺陷的成因：0.5 分既可能是"测过、就是中等"，也可能是"没测过"，下游分不出来。
    响应性契约（``core.cross_device_responsiveness_contract``）要的 ``evidence_available``
    就是这一位。
    """
    return int(sample_count or 0) > 0
