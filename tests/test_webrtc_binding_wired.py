"""WebRTC 任务绑定:那条断了的链路现在接上了。

改之前是什么样
--------------
``core/webrtc_task_lifecycle.py`` 有 1041 行 + 1013 行测试:绑定记录、传输状态→
生命周期动作分类、终态拆除,全都写好了、测过了、从 ``core.runtime`` 导出去了。
``CommandRouter`` 里有 ``requires_webrtc`` 握手闸,AIP v3 里有 ``WEBRTC_BIND``
消息类型,特性开关默认 enabled。

**但生产代码里一个调用点都没有:**

===================================  ==========
API                                  生产调用点
===================================  ==========
bind_webrtc_session_to_task          0
teardown_binding_on_task_terminal    0
list_active_webrtc_task_bindings     0
apply_transport_state_to_task_...    2
===================================  ==========

绑定从来没被建立过,于是 ``WebRTCSessionManager._notify_transport_state`` 每次都在
第一步返回 —— 它先 ``get_webrtc_task_binding(task_id)``,拿到 ``None``,打一条
"no binding found; transport state will not be propagated" 就结束。拆除自然也永远
不触发。整套东西是**备好的料**,而且仓库自己在 ``core/canonical_capability_status.py``
里如实登记为 EXPERIMENTAL:"structural scaffolding ... not verified as operational"。

这个文件钉的就是"那根线接上了",以及接在**唯一不会漏的那两个点**上。
"""

from __future__ import annotations

import pytest

from core.canonical_task import CanonicalTask, TaskLifecycle
from core.webrtc_task_lifecycle import (
    TERMINAL_TASK_LIFECYCLES,
    bind_webrtc_session_to_task,
    get_webrtc_task_binding,
    list_active_webrtc_task_bindings,
    reset_webrtc_task_session_registry,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_webrtc_task_session_registry()
    yield
    reset_webrtc_task_session_registry()


# ══════════════════════════════════════════════════════════════════════════
# A. 终态真的会拆掉绑定
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("terminal", [TaskLifecycle.COMPLETED, TaskLifecycle.FAILED, TaskLifecycle.CANCELLED])
def test_a01_a_terminal_task_tears_the_binding_down(terminal):
    task = CanonicalTask()
    bind_webrtc_session_to_task(task_id=task.task_id, webrtc_session_id="dev-a", device_id="dev-a")
    assert len(list_active_webrtc_task_bindings()) == 1

    task.advance_lifecycle(terminal)
    assert list_active_webrtc_task_bindings() == []


@pytest.mark.parametrize("ongoing", [TaskLifecycle.RUNNING, TaskLifecycle.DISPATCHED, TaskLifecycle.ROUTED])
def test_a02_a_non_terminal_transition_keeps_the_binding(ongoing):
    task = CanonicalTask()
    bind_webrtc_session_to_task(task_id=task.task_id, webrtc_session_id="dev-a", device_id="dev-a")
    task.advance_lifecycle(ongoing)
    assert len(list_active_webrtc_task_bindings()) == 1


def test_a03_degraded_is_not_terminal_for_teardown():
    """传输降级但仍可用时任务转 DEGRADED **继续跑** —— 这时候拆会话正好是错的。

    注意 DEGRADED 在 CanonicalTask 那边也盖 completed_at 时间戳,所以很容易被
    顺手当成终态。这条挡的就是那个顺手。
    """
    assert "degraded" not in TERMINAL_TASK_LIFECYCLES
    task = CanonicalTask()
    bind_webrtc_session_to_task(task_id=task.task_id, webrtc_session_id="dev-a", device_id="dev-a")
    task.advance_lifecycle(TaskLifecycle.DEGRADED)
    assert len(list_active_webrtc_task_bindings()) == 1


def test_a04_a_task_without_a_binding_is_a_safe_no_op():
    """绝大多数任务不用 WebRTC。它们走到终态时这里什么都不该发生,更不该报错。"""
    task = CanonicalTask()
    task.advance_lifecycle(TaskLifecycle.COMPLETED)
    assert list_active_webrtc_task_bindings() == []


def test_a05_teardown_is_idempotent():
    task = CanonicalTask()
    bind_webrtc_session_to_task(task_id=task.task_id, webrtc_session_id="dev-a", device_id="dev-a")
    task.advance_lifecycle(TaskLifecycle.COMPLETED)
    task.advance_lifecycle(TaskLifecycle.CANCELLED)
    assert list_active_webrtc_task_bindings() == []


# ══════════════════════════════════════════════════════════════════════════
# B. 接在唯一不会漏的那两个点上
# ══════════════════════════════════════════════════════════════════════════


def test_b01_teardown_hangs_off_the_single_lifecycle_transition():
    """挂在 advance_lifecycle 上,不挂在各个"任务做完了"的调用点上。

    那是生命周期**唯一的**转移处;散到调用点上必然漏一条,而漏掉那条的表现是:
    任务早就结束了,一个 WebRTC 会话还绑着它。
    """
    import inspect

    body = inspect.getsource(CanonicalTask.advance_lifecycle)
    assert "teardown_binding_on_task_terminal" in body
    assert "TERMINAL_TASK_LIFECYCLES" in body, "终态集合被就地重列了 —— 加一档时必漏改一处"


def test_b02_bind_hangs_off_the_router_where_both_ids_exist():
    """绑定收在 CommandRouter:proxy 只知道设备,不知道任务;而绑定的两端恰恰是
    task_id 与 device_id,只有这一层同时握着两者。"""
    import inspect

    from core.command_router import CommandRouter

    body = inspect.getsource(CommandRouter.route_envelope)
    assert "bind_webrtc_session_to_task" in body


def test_b03_the_terminal_set_has_exactly_one_definition():
    """此前它是某个函数体里的局部集合,而策略哨兵又用散文重复写了一遍。
    两份清单加一档时必漏改一处。"""
    import inspect

    from core import webrtc_task_lifecycle as wtl

    src = inspect.getsource(wtl)
    # 集合字面量只该出现在模块级常量那一处
    assert src.count('{"completed", "failed", "cancelled"}') == 1


def test_b04_the_transport_relay_can_now_find_a_binding():
    """改之前这一步永远拿到 None —— 整条链路就断在这儿。"""
    task = CanonicalTask()
    bind_webrtc_session_to_task(task_id=task.task_id, webrtc_session_id="dev-a", device_id="dev-a")
    assert get_webrtc_task_binding(task.task_id) is not None


def test_b05_binding_failure_does_not_block_a_ready_task():
    """绑不上是可观测的问题,但不该拦住一个 WebRTC 已经就绪的任务。"""
    import inspect

    from core.command_router import CommandRouter

    body = inspect.getsource(CommandRouter.route_envelope)
    idx = body.index("bind_webrtc_session_to_task")
    assert "except Exception" in body[idx : idx + 1400]


def test_b06_the_capability_status_still_says_what_it_is():
    """接了一根线不等于这套东西就"可用了"。仓库把 WebRTC 登记为 EXPERIMENTAL,
    那条登记是诚实的、当前有效的 —— 这次没有去改它。

    真要改成 operational,得有真机验证过的证据,不是接通了调用点就算。
    """
    from core.canonical_capability_status import WEBRTC_IS_EXPERIMENTAL_STATUS

    assert "EXPERIMENTAL" in WEBRTC_IS_EXPERIMENTAL_STATUS
