#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_layer03_criterion_defects.py

任务 #53 最后一批：``desktop_presence_runtime`` / ``computer_use_loop`` /
``windows_execution_arbiter`` / ``device_control_service`` 四个文件里查实的判据缺陷。

四条，互不相干，共同点还是**失效都是静默的**。
"""

from __future__ import annotations

import ast
import concurrent.futures
import inspect
import time

import pytest


def _code_only(obj) -> str:
    """源码里**只留代码**，注释一律丢掉。

    这些"判据有没有引权威"的断言是按源码文本判的，而修复通常会在旁边留一段
    解释性注释、把**旧代码原样引一遍**。直接 grep 会把注释里的旧写法当成还在
    的活代码，于是断言在已经修好的文件上照红（第一版就是这么红的）。
    ``ast.unparse`` 丢注释、留 docstring，正合用。两点要注意：
    取方法的源码是缩进的，得先 ``dedent``；``unparse`` 会把字符串统一成单引号，
    所以下面的断言一律用单引号写字面量。
    """
    import textwrap

    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(obj))))


# ---------------------------------------------------------------------------
# 一、成功判据：反思与预测器那套完全不看 result["success"]
# ---------------------------------------------------------------------------
#
# 原来：_success = not result.get("error") and not result.get("failed")
# 而本仓最常见的失败形状是软失败 —— {"success": False, "response": "抱歉…"}，
# 不带 error/failed 键。于是失败被当成功喂进 reflect_retrospective 与
# predictor.record_outcome，自适应预测器把失败策略标定成"好用"。


_SOFT_FAILURE = {"success": False, "response": "抱歉，我没能打开那个应用"}
_SOFT_SUCCESS = {"success": True, "response": "已打开"}
_HARD_FAILURE = {"error": "boom"}


def test_soft_failure_is_not_counted_as_success():
    """**这就是被修掉的那条。** 旧口径对这个 payload 算出 True。"""
    from core.flow_aware_result_convergence import derive_result_success

    old = not _SOFT_FAILURE.get("error") and not _SOFT_FAILURE.get("failed")
    assert old is True, "前提变了：旧口径本来就该把这个软失败判成成功"

    new, _ = derive_result_success(_SOFT_FAILURE)
    assert new is False, "软失败仍被判成成功 —— 预测器会继续被污染"


@pytest.mark.parametrize(
    "payload,expected",
    [(_SOFT_FAILURE, False), (_SOFT_SUCCESS, True), (_HARD_FAILURE, True)],
)
def test_convergence_authority_reads_the_success_key(payload, expected):
    """区分度：新口径不是"一律判失败"，硬失败那条它也确实**不**改判。

    ``{"error": "boom"}`` 没有 success/status 键，权威按文档保守判 True。
    这跟旧口径结论一致 —— 说明改动只影响真正分歧的那一档。
    """
    from core.flow_aware_result_convergence import derive_result_success

    assert derive_result_success(payload)[0] is expected


def _success_criterion_call_sites(module) -> int:
    """数**真正的调用**，不是 import 行。

    第一版这条写成 ``src.count("derive_result_success") >= 2``，而两条 import
    语句本身就贡献了 2 —— 把调用删掉它照样绿。反向验证时才发现（拆了 seam 只红
    了 3 条，这条没红）。改成按 AST 数 Call 节点。
    """
    tree = ast.parse(inspect.getsource(module))
    names = {"derive_result_success", "_derive_success"}
    return sum(
        1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names
    )


def _has_handrolled_success_criterion(module) -> bool:
    """有没有人又手拼 ``not <x>.get("error") and not <x>.get("failed")``。

    按 AST 结构判，不按渲染出来的字符串判 —— ``ast.unparse`` 会给布尔操作数
    补括号（``a and (not b)``），照字面量 grep 匹配不上，这也是第一版没红的原因。
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.And):
            continue
        keys = set()
        for operand in node.values:
            if not (isinstance(operand, ast.UnaryOp) and isinstance(operand.op, ast.Not)):
                continue
            call = operand.operand
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and call.args
                and isinstance(call.args[0], ast.Constant)
            ):
                keys.add(call.args[0].value)
        if {"error", "failed"} <= keys:
            return True
    return False


def test_reflection_and_billing_both_go_through_the_authority():
    """两处消费方都必须引权威，不许各拼一套。"""
    import core.desktop_presence_runtime as dpr

    assert not _has_handrolled_success_criterion(dpr), "反思那套自拼判据又回来了（不看 result['success']）"
    assert _success_criterion_call_sites(dpr) >= 2, "反思与计费应各自**调用**一次收敛权威（import 不算）"


# ---------------------------------------------------------------------------
# 二、active_perception 不在 _dispatch 的已知来源表里
# ---------------------------------------------------------------------------


def test_active_perception_is_a_known_source():
    """与 ``ambient`` 完全同形，当时只补了后者。

    功能上兜底分支恰好走对，但每个自发目标都刷一条 "unknown source" 警告，
    把主体自己的通道标成外来未知调用者。
    """
    import core.desktop_presence_runtime as dpr

    src = _code_only(dpr.DesktopPresenceRuntime._dispatch)
    assert "'active_perception'" in src, "_submit_autonomous_goal 用的来源仍不在白名单里"
    # 白名单与实际提交处必须用同一个字符串
    assert "'active_perception'" in _code_only(dpr), "来源常量对不上"


# ---------------------------------------------------------------------------
# 三、route_command 的同步派发超时
# ---------------------------------------------------------------------------


def test_the_old_shape_of_the_timeout_did_nothing():
    """先钉住成因本身：``with ThreadPoolExecutor`` 会把 timeout 吃掉。

    ``__exit__`` 调 ``shutdown(wait=True)``，一直阻塞到任务真跑完才把
    TimeoutError 抛出去 —— 既没提前返回，又把已经算出来的结果丢掉。
    """
    t0 = time.time()
    with pytest.raises(concurrent.futures.TimeoutError):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(time.sleep, 0.6)
            fut.result(timeout=0.05)
    elapsed = time.time() - t0
    assert elapsed >= 0.55, f"这次没复现出来（{elapsed:.2f}s）—— 下面几条就证明不了什么"


def test_timeout_error_is_not_a_runtime_error():
    """原来的 ``except RuntimeError`` 接不住它，异常会直接外抛。"""
    assert not issubclass(concurrent.futures.TimeoutError, RuntimeError)


def test_route_command_no_longer_swallows_its_own_timeout():
    """修复后的形状：不用 ``with``，超时走 ``shutdown(wait=False)``。"""
    from core.windows_execution_arbiter import WindowsExecutionArbiter

    src = _code_only(WindowsExecutionArbiter.route_command)
    assert "shutdown(wait=False)" in src, "超时后仍会等线程跑完 —— timeout 等于没设"
    assert "concurrent.futures.TimeoutError" in src, "超时仍没被显式接住"
    assert "timeout=30" not in src, "又写死 30 秒了"


def test_sync_dispatch_budget_is_derived_from_the_real_loop_budget(monkeypatch):
    """预算必须跟着 computer_use 的常量走，不是凭空一个数。

    第 4 级委托 ``run_computer_use_task``，上界 = max_steps × (规划 60s + 静置)。
    原来写死 30 秒，与被它包住的东西差一个数量级。
    """
    from core.windows_execution_arbiter import _sync_dispatch_budget_s

    monkeypatch.setenv("GALAXY_CU_MAX_STEPS", "15")
    monkeypatch.setenv("GALAXY_CU_SETTLE_S", "1.0")
    default_budget = _sync_dispatch_budget_s()
    assert default_budget > 900, f"预算 {default_budget:.0f}s 仍远小于闭环真实上界 ~915s"

    monkeypatch.setenv("GALAXY_CU_MAX_STEPS", "3")
    assert _sync_dispatch_budget_s() < default_budget / 3, "调小 max_steps 预算没跟着降 —— 判据没同源"


# ---------------------------------------------------------------------------
# 四、scroll 两套参数口径
# ---------------------------------------------------------------------------


class _Recorder:
    """只记下 ``scroll()`` 实际收到的参数。"""

    def __init__(self):
        self.calls = []

    async def scroll(self, device_id, direction="down", amount=500):
        self.calls.append((direction, amount))
        return {"success": True}


async def _run_scroll(params):
    from core.device_control_service import DeviceControlService

    svc = DeviceControlService.__new__(DeviceControlService)
    rec = _Recorder()
    svc.scroll = rec.scroll
    await DeviceControlService.execute_action(svc, device_id="local", action="scroll", params=params)
    return rec.calls[0]


@pytest.mark.asyncio
async def test_scroll_up_does_not_become_scroll_down():
    """**这就是被修掉的那条。** clicks 正数=向上，旧代码一律 down 500。"""
    direction, amount = await _run_scroll({"clicks": 3, "x": 800, "y": 500})
    assert direction == "up", f"「向上滚 3 格」被执行成了 {direction} —— 方向相反"
    assert amount > 0


@pytest.mark.asyncio
async def test_scroll_down_stays_down():
    direction, _ = await _run_scroll({"clicks": -3, "x": 800, "y": 500})
    assert direction == "down", "负数 clicks 的契约是向下"


@pytest.mark.asyncio
async def test_scroll_magnitude_tracks_clicks():
    """幅度必须跟着 clicks 走，不能恒取默认的 500。"""
    _, small = await _run_scroll({"clicks": -1})
    _, big = await _run_scroll({"clicks": -5})
    assert big > small, f"1 格与 5 格滚出一样的幅度（{small} vs {big}）—— clicks 又被吃掉了"
    assert big == 5 * small


@pytest.mark.asyncio
async def test_legacy_direction_amount_callers_still_work():
    """区分度：老口径的调用方不能被改坏。"""
    direction, amount = await _run_scroll({"direction": "up", "amount": 250})
    assert (direction, amount) == ("up", 250)

    direction, amount = await _run_scroll({})
    assert (direction, amount) == ("down", 500), "无参默认值变了"


# ---------------------------------------------------------------------------
# 五、operator 审计边界：chat 算出的受众必须真的送达
# ---------------------------------------------------------------------------


def test_runtime_no_longer_discards_the_callers_audience():
    """``is_operator_request`` 不许再被无条件 pop 掉。

    原来 runtime 把它从 kwargs 里剔除，再用 ``source == "operator"`` 自己算 ——
    而 chat 永远传 ``source="chat"`` ⇒ 恒为 False ⇒ OpenClawd 把所有
    OPERATOR_AUDIT_TRUTH 键 pop 干净 ⇒ chat 那整套边界逻辑对 metadata 空转。
    """
    import core.desktop_presence_runtime as dpr

    src = _code_only(dpr.DesktopPresenceRuntime.handle_request)
    assert "_explicit_operator" in src, "调用方传的受众又被丢掉了"
    # 显式值优先，没传才退回按 source 判
    assert "source == 'operator'" in src, "source='operator' 本身仍应算运维请求"


def test_chat_passes_the_audience_before_dispatch():
    """必须在**派发之前**传。等结果回来再算就晚了 —— 键已经被删了。"""
    import core.routes.chat as chat_mod

    src = _code_only(chat_mod)
    assert "is_operator_request=_is_operator_request(req)" in src, "chat 没有把受众传给 runtime"


@pytest.mark.parametrize(
    "context,expected",
    [
        ([{"response_audience": "operator"}], True),
        ([{"response_audience": "audit"}], True),
        ([{"operator_mode": "true"}], True),
        ([{"response_audience": "user"}], False),
        ([], False),
        # context 完全不传（ChatRequest 不接受 None，模型层就造不出那个值）
        (..., False),
    ],
)
def test_audience_criterion_discriminates(context, expected):
    """区分度：受众判据本身要真的分得开，不能一律 True 或一律 False。"""
    from core.routes.chat import ChatRequest, _is_operator_request

    req = ChatRequest(message="hi") if context is ... else ChatRequest(message="hi", context=context)
    assert _is_operator_request(req) is expected


# ---------------------------------------------------------------------------
# 六、policy 护栏：接通，但默认全放行
# ---------------------------------------------------------------------------


def test_policy_defaults_to_no_enforcement(monkeypatch):
    """默认行为必须与接通前逐字一致 —— 不拦任何东西。"""
    from core.windows_execution_arbiter import _effective_policy

    monkeypatch.delenv("GALAXY_EXEC_POLICY_ENFORCE", raising=False)
    assert _effective_policy(None) is None, "默认就开始拦了 —— 这是没人要求的 fail-closed"


def test_explicitly_passed_policy_always_wins(monkeypatch):
    """**这就是"接通"的含义**：调用方传了 policy，它就必须生效。

    原来三个真实调用点都不传，``if policy is not None`` 永远为假，整块护栏不可达。
    """
    from core.windows_execution_arbiter import _effective_policy

    monkeypatch.delenv("GALAXY_EXEC_POLICY_ENFORCE", raising=False)
    sentinel = object()
    assert _effective_policy(sentinel) is sentinel, "显式传入的 policy 被忽略了"


def test_enforcement_can_be_turned_on(monkeypatch):
    """开关打开时按真实相位解析，能解析出东西来。"""
    from core.windows_execution_arbiter import _effective_policy

    monkeypatch.setenv("GALAXY_EXEC_POLICY_ENFORCE", "1")
    assert _effective_policy(None) is not None, "开关打开却没解析出策略 —— 等于没接通"


def test_a_failed_phase_read_does_not_become_a_ban(monkeypatch):
    """读不到相位不许变成"拦下一切"。

    ``get_current_phase()`` 读失败时返回 "silent"（→ observe_only），
    **"真的静默"与"读不出来"同值**。所以解析一旦出错就必须放行，
    不能把一次读取失败升级成封禁。
    """
    import core.windows_execution_arbiter as wea

    monkeypatch.setenv("GALAXY_EXEC_POLICY_ENFORCE", "1")
    monkeypatch.setattr(
        wea,
        "_effective_policy",
        wea._effective_policy,  # 保持原函数，只让它内部的解析炸掉
    )
    import core.lumiv_websocket_bridge as bridge

    def _boom() -> str:
        raise RuntimeError("bridge unavailable")

    monkeypatch.setattr(bridge, "get_current_phase", _boom)
    assert wea._effective_policy(None) is None, "相位读取失败被升级成了封禁"


def test_execute_actually_consults_the_resolver():
    """护栏必须真的从 ``_effective_policy`` 取，不是继续只看形参。"""
    from core.windows_execution_arbiter import WindowsExecutionArbiter

    src = _code_only(WindowsExecutionArbiter.execute)
    assert "_effective_policy(policy)" in src, "execute 还没走统一的策略取值口"
