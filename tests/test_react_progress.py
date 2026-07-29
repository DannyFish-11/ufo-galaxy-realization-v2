"""core/react_progress.py 的契约测试。

对应 ReAct 循环里原本的两块空白:
- 结果只有"成/败"二元,分不出该重试还是该换路;
- 无进展检测只看"连续同名 3 次",拦不住交替打转、隔开重复、反复同错。
"""

from __future__ import annotations

import pytest

from core.react_progress import (
    ProgressTracker,
    ToolOutcome,
    classify_tool_outcome,
)

# ── 1. 失败分类学 ──────────────────────────────────────────────────────


def test_plain_success():
    assert classify_tool_outcome({"success": True, "result": 42}) is ToolOutcome.SUCCESS


def test_missing_success_key_is_contract_violation_not_success():
    """最要紧的一条:没有 success 键**绝不能**默认判成功。

    原实现 result.get("success", True) 会把它当成功放行 —— 与 L4 那条
    "未知命令返回 unknown 却记 SUCCESS" 是同一个病。
    """
    assert classify_tool_outcome({"result": "something"}) is ToolOutcome.CONTRACT_VIOLATION
    assert classify_tool_outcome({}) is ToolOutcome.CONTRACT_VIOLATION


def test_non_dict_result_is_contract_violation():
    for bad in ("plain string", 123, None, ["list"]):
        assert classify_tool_outcome(bad) is ToolOutcome.CONTRACT_VIOLATION


def test_needs_confirmation_is_denied_not_failure():
    """需确认时 success 恒 False,但它不是"工具坏了",不该被重试。"""
    r = {"success": False, "needs_confirmation": True, "tool": "node__09__shell"}
    assert classify_tool_outcome(r) is ToolOutcome.DENIED
    assert classify_tool_outcome(r).retriable is False


@pytest.mark.parametrize(
    "err",
    ["权限拒绝: 高风险操作", "Permission denied", "操作需要用户确认（风险等级: high）"],
)
def test_permission_errors_are_denied(err):
    assert classify_tool_outcome({"success": False, "error": err}) is ToolOutcome.DENIED


@pytest.mark.parametrize(
    "err",
    ["未知工具前缀: foo__bar", "unknown tool: x", "无效 MCP 工具名: mcp__a", "参数校验失败: 缺少必填 path"],
)
def test_deterministic_errors_are_permanent(err):
    out = classify_tool_outcome({"success": False, "error": err})
    assert out is ToolOutcome.PERMANENT
    assert out.retriable is False, "确定性失败重试无意义"


@pytest.mark.parametrize(
    "err",
    ["工具 node__08__fetch 执行超时 (30s)", "Connection refused", "503 Service Unavailable", "rate limit exceeded"],
)
def test_transient_errors_are_retriable(err):
    out = classify_tool_outcome({"success": False, "error": err})
    assert out is ToolOutcome.TRANSIENT
    assert out.retriable is True, "只有瞬时故障值得重试"


def test_business_failure_is_failed_and_not_retriable():
    out = classify_tool_outcome({"success": False, "error": "文件内容为空"})
    assert out is ToolOutcome.FAILED
    assert out.retriable is False


def test_only_transient_is_retriable():
    """把"可重试"这件事钉死在唯一一类上。"""
    retriable = {o for o in ToolOutcome if o.retriable}
    assert retriable == {ToolOutcome.TRANSIENT}


# ── 2. 无进展检测 ──────────────────────────────────────────────────────


def _ok():
    return ToolOutcome.SUCCESS


def test_identical_call_repeated_is_stuck_even_when_not_adjacent():
    """原实现的连续同名计数器会被中间的其它调用清零,这里不会。"""
    t = ProgressTracker()
    args = {"path": "/tmp/a"}
    assert t.record("read_file", args, _ok()).stuck is False
    assert t.record("other_tool", {"q": 1}, _ok()).stuck is False  # 中间插一个别的
    assert t.record("read_file", args, _ok()).stuck is False
    v = t.record("read_file", args, _ok())
    assert v.stuck is True and v.kind == "repeat"
    assert "完全相同的参数" in v.reason


def test_same_tool_different_args_is_not_stuck():
    """同一工具但参数在变 = 在探索,不该被误判成打转。"""
    t = ProgressTracker()
    for i in range(5):
        assert t.record("read_file", {"path": f"/tmp/{i}"}, _ok()).stuck is False


def test_two_tools_thrashing_is_detected():
    """A B A B A B —— 每一步都不是"连续同名",原实现完全看不见。"""
    t = ProgressTracker()
    verdict = None
    for i in range(6):
        name = "search" if i % 2 == 0 else "read"
        verdict = t.record(name, {"i": i}, _ok())
    assert verdict.stuck is True and verdict.kind == "thrash"
    assert "反复来回" in verdict.reason


def test_repeated_identical_error_is_detected_even_with_varying_args():
    """参数每次都不同,但撞的是同一堵墙。"""
    t = ProgressTracker()
    err = "Connection refused to 10.0.0.5:8080"
    v = None
    for i in range(3):
        v = t.record("fetch", {"url": f"http://x/{i}"}, ToolOutcome.TRANSIENT, error=err)
    assert v.stuck is True and v.kind == "same_error"


def test_error_fingerprint_normalizes_digits():
    """同一个错误只是时间戳/端口不同,应算作同一个。"""
    t = ProgressTracker()
    v = None
    for i in range(3):
        v = t.record("fetch", {"i": i}, ToolOutcome.FAILED, error=f"timeout after {i*100}ms at 10:0{i}")
    assert v.stuck is True and v.kind == "same_error"


def test_successful_varied_work_never_flagged():
    """正常推进的任务(工具在变、参数在变、都成功)绝不能被误停。"""
    t = ProgressTracker()
    for i, name in enumerate(["scan", "read", "analyze", "write", "verify", "report"]):
        assert t.record(name, {"step": i}, _ok()).stuck is False


def test_argument_key_order_does_not_create_false_novelty():
    """dict 顺序不同不等于新调用,否则重复检测会被顺序抖动绕过。"""
    t = ProgressTracker()
    t.record("f", {"a": 1, "b": 2}, _ok())
    t.record("f", {"b": 2, "a": 1}, _ok())
    v = t.record("f", {"a": 1, "b": 2}, _ok())
    assert v.stuck is True and v.kind == "repeat"


def test_unserialisable_arguments_do_not_crash():
    """参数不可序列化时退回 repr,不能把循环带崩。"""

    class Weird:
        pass

    t = ProgressTracker()
    obj = Weird()
    for _ in range(2):
        assert t.record("f", {"o": obj}, _ok()).stuck is False
    assert t.record("f", {"o": obj}, _ok()).stuck is True
