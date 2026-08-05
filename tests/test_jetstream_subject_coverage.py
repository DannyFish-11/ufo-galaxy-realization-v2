"""tests/test_jetstream_subject_coverage.py
============================================

每一个会被发布的主题,都必须被某条 JetStream 流覆盖。

这条测试补的洞
--------------
``NATSBus._publish`` 走的是 **JetStream**(``js.publish``),而 JetStream 要求主题
被某条流覆盖 —— 没有流,publish 当场返回 ``no response from stream``,一条也发
不出去。

修之前 ``_STREAMS`` 只有 ``galaxy.tasks/task.>``、``galaxy.mcp.>``、
``galaxy.events.>`` + ``galaxy.workers.>`` 三条,于是这四个平面在**真实 NATS
服务器上一条都发不出去**:

  * ``galaxy.device.*``     —— 整个 AIP v3 设备协议平面(注册/心跳/接管/…)
  * ``galaxy.capability.*`` —— 能力上报与查询
  * ``galaxy.presence.*``   —— 在场相位
  * ``galaxy.audit.*``      —— 审计记录

而 28 个 AIP v3 发布器全都在、全都被调用、全都返回 ``{"success": ...}`` 里的
失败被当作 best-effort 咽掉了。

为什么一路测试都没发现:进程内降级总线(``NATSBus._local_publish``)**没有流的
概念**,谁发都投得到。全部单机测试与 CI 都跑在那条路径上 —— "发布器齐全"是真的,
"发得出去"是假的。

所以这里不连服务器,改成**静态**核对:把所有会被发布的主题,拿去和 ``_STREAMS``
里的 subject 通配模式做匹配。加了新平面却忘了加流,这条会红。
"""

from __future__ import annotations

import re
from typing import List

import pytest

from core.nats_subjects import _STREAMS, TOTAL_STREAM_MAX_BYTES, NATSTopics, WorkerLifecycleSubjects


def _matches(subject: str, pattern: str) -> bool:
    """NATS subject 通配匹配:``*`` 吃一个 token,``>`` 吃剩下全部。

    逐 token 精确 —— ``task`` 与 ``tasks`` 永不相通,这正是任务平面单复数
    分裂那次的根因。
    """
    s_tokens = subject.split(".")
    p_tokens = pattern.split(".")
    for i, p in enumerate(p_tokens):
        if p == ">":
            return i < len(s_tokens)  # ``>`` 至少要吃到一个 token
        if i >= len(s_tokens):
            return False
        if p != "*" and p != s_tokens[i]:
            return False
    return len(s_tokens) == len(p_tokens)


def _covering_stream(subject: str) -> str:
    for name, cfg in _STREAMS.items():
        for pattern in cfg["subjects"]:
            if _matches(subject, pattern):
                return name
    return ""


# 全仓实际会被发布的主题(含带后缀的具体实例)。
# 新增一个发布平面时,把它的主题加进来 —— 忘了加流,这条测试就会红。
PUBLISHED_SUBJECTS: List[str] = [
    # ── 任务平面:单数(规范) ──
    NATSTopics.task_dispatch("device-01"),
    NATSTopics.task_result("task-01"),
    f"{NATSTopics.TASK_CANCEL}.task-01",
    f"{NATSTopics.TASK_CANCEL_RESULT}.task-01",
    NATSTopics.TASK_DEADLETTER,
    # ── 任务平面:复数(既有运转面,硬编码在 command_router / scheduler / 网关) ──
    "galaxy.tasks.dispatch.device-01",
    "galaxy.tasks.result.task-01",
    "galaxy.tasks.deadletter",
    # ── 设备平面(AIP v3) ──
    NATSTopics.DEVICE_REGISTER,
    NATSTopics.device_heartbeat("device-01"),
    "galaxy.device.heartbeat_ack.device-01",
    "galaxy.device.takeover.device-01",
    "galaxy.device.takeover_response.device-01",
    NATSTopics.DEVICE_STATUS,
    NATSTopics.DEVICE_PRESENCE,
    # ── 能力平面 ──
    NATSTopics.CAPABILITY_REGISTERED,
    NATSTopics.capability_registered("node-04"),
    NATSTopics.CAPABILITY_QUERY,
    NATSTopics.CAPABILITY_REMOVED,
    # ── 在场平面 ──
    NATSTopics.PRESENCE_STATE,
    NATSTopics.PRESENCE_PROJECTION,
    # ── 审计平面 ──
    NATSTopics.AUDIT_COMMAND,
    NATSTopics.AUDIT_RESULT,
    NATSTopics.AUDIT_VIOLATION,
    "galaxy.audit.task_accepted",
    # ── MCP ──
    "galaxy.mcp.calls",
    "galaxy.mcp.results",
    # ── 事件 / worker 生命周期 ──
    "galaxy.events.system_ready",
    WorkerLifecycleSubjects.REGISTER,
    WorkerLifecycleSubjects.HEARTBEAT,
    WorkerLifecycleSubjects.SHUTDOWN,
]


@pytest.mark.parametrize("subject", PUBLISHED_SUBJECTS)
def test_every_published_subject_is_covered_by_a_stream(subject: str):
    """没有流覆盖 = 这个主题上的 publish 全部失败,不是"没持久化"那么轻。"""
    stream = _covering_stream(subject)
    assert stream, (
        f"{subject} 没有任何 JetStream 流覆盖 —— 在真实服务器上这个主题的 "
        f"publish 会全部返回 no response from stream。请在 core/nats_subjects.py "
        f"的 _STREAMS 里补上。"
    )


def test_the_four_planes_that_were_dark_each_have_a_stream():
    """四个曾经整体发不出去的平面,逐个点名。

    上面那条参数化测试是按主题查的;这条按**平面**查,免得将来有人把某个平面的
    主题从清单里删掉,覆盖就跟着一起消失、还没人发现。
    """
    for plane, expected in [
        ("galaxy.device.register", "GALAXY_DEVICE"),
        ("galaxy.capability.registered", "GALAXY_CAPABILITY"),
        ("galaxy.presence.state", "GALAXY_PRESENCE"),
        ("galaxy.audit.command", "GALAXY_AUDIT"),
    ]:
        assert _covering_stream(plane) == expected, f"{plane} 应由 {expected} 覆盖"


def test_task_plane_singular_and_plural_are_both_covered():
    """单复数并存的前提是**两个都在流里**,否则落在流外那半连持久化都没有。"""
    assert _covering_stream("galaxy.task.result.t1") == "GALAXY_TASKS"
    assert _covering_stream("galaxy.tasks.result.t1") == "GALAXY_TASKS"


def test_no_two_streams_overlap_on_the_same_subject():
    """两条流覆盖同一主题会被 JetStream 直接拒(``subjects overlap``),整条流建不起来。

    实测过的形态是别的:``insufficient storage``。但重叠是同一类事故 —— 建流失败,
    那个平面整个哑掉 —— 所以一并钉住。
    """
    seen: dict = {}
    for subject in PUBLISHED_SUBJECTS:
        hits = [name for name, cfg in _STREAMS.items() if any(_matches(subject, p) for p in cfg["subjects"])]
        assert len(hits) == 1, f"{subject} 被 {hits} 同时覆盖 —— JetStream 会拒绝建流"
        seen[subject] = hits[0]


def test_total_stream_budget_stays_within_a_modest_jetstream_store():
    """所有流 max_bytes 之和是**会互相挤兑的额度**,不是各管各的预算。

    JetStream 预留 max_bytes;总和超过服务器 store 上限时,**后建的那条流被拒**,
    那个平面整个发不出去。实测:给审计要 2 GB,在一台 store 上限 3.45 GB 的服务器
    上就把 GALAXY_AUDIT 挤掉了,而失败当时只记在 debug 日志里(已改为 error)。

    3 GB 是个保守的参考线 —— 默认部署与容器里的 JetStream store 常常就这个量级。
    真要调大,先确认目标部署的 store 上限。
    """
    assert TOTAL_STREAM_MAX_BYTES <= 3 * 2**30, (
        f"所有流 max_bytes 之和 {TOTAL_STREAM_MAX_BYTES / 2**30:.2f} GB 超过 3 GB 参考线 —— "
        f"store 上限小于这个数的服务器上,排在后面的流会建不起来,那个平面整个哑掉。"
    )


def test_subject_matcher_is_token_exact():
    """匹配器本身要对 —— 它是上面所有断言的地基。

    ``task`` vs ``tasks`` 这一条尤其:任务平面那次事故就是因为有人以为
    ``galaxy.task.*`` 能匹配到 ``galaxy.tasks.*``。
    """
    assert _matches("galaxy.task.result.t1", "galaxy.task.>")
    assert not _matches("galaxy.tasks.result.t1", "galaxy.task.>"), "task 与 tasks 必须互不匹配"
    assert _matches("galaxy.device.heartbeat.d1", "galaxy.device.>")
    assert not _matches("galaxy.device", "galaxy.device.>"), "``>`` 至少要吃一个 token"
    assert _matches("galaxy.audit.command", "galaxy.audit.*")
    assert not _matches("galaxy.audit.a.b", "galaxy.audit.*"), "``*`` 只吃一个 token"


def test_stream_configs_are_well_formed():
    """每条流都得有 subjects / max_msgs / max_bytes;max_age_s 可选但必须是正数。"""
    for name, cfg in _STREAMS.items():
        assert cfg.get("subjects"), f"{name} 没有 subjects"
        assert isinstance(cfg["max_msgs"], int) and cfg["max_msgs"] > 0, name
        assert isinstance(cfg["max_bytes"], int) and cfg["max_bytes"] > 0, name
        if "max_age_s" in cfg:
            assert cfg["max_age_s"] > 0, f"{name} 的 max_age_s 必须为正"
        for pattern in cfg["subjects"]:
            assert re.fullmatch(r"[A-Za-z0-9_.*>-]+", pattern), f"{name} 的 subject 形状可疑:{pattern}"
