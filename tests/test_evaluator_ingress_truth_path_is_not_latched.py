"""治理产物能否写进真相运行时,不该取决于"本模块第一次被 import 那一刻"。

## 修的是什么

``core/android_evaluator_artifact_ingress.py`` 原先这样判断真相入口能不能走::

    try:
        from core.android_participant_truth_ingress import ingest_... as _ingest_truth_message
        _TRUTH_INGRESS_AVAILABLE = True
    except ImportError:
        _TRUTH_INGRESS_AVAILABLE = False
        _ingest_truth_message = None
    ...
    if _TRUTH_INGRESS_AVAILABLE and _ingest_truth_message is not None:
        ...写入 FlowTruthAlignmentRuntime...

两个标志都在**模块 import 那一刻**定死。只要本模块第一次被 import 时那个上游
恰好导不进来(循环 import、上游处于半初始化状态、测试替换过 sys.modules……),
标志就在**整个进程剩余生命周期里**永远是 False:

* 治理产物照样报 ``was_stored=True`` —— 调用方以为成功了;
* 但**再也不会**写进 FlowTruthAlignmentRuntime;
* 而且只在 **debug** 级留一行日志。

一次偶发的 import 失败,把一条治理链路永久关掉,还不吭声。

## 怎么发现的

``tests/test_pr4v2_android_evaluator_artifact_governance_flow.py`` 的 J01/J03
单独跑全过,在 CI 某个分片的排列下报红::

    J01: ingest_android_evaluator_artifact() must write to
         FlowTruthAlignmentRuntime (AC2)      assert 0 > 0
    J03: truth_ownership dimension must reflect the governance artifact,
         not 'unknown' (AC3)

也就是说:**治理真相是否被记录,取决于进程里此前 import 过什么**。

需要说清楚的一点:这是**存量**问题,不是本轮改出来的 —— 两条用例在 origin/main
上单跑同样全过。是本轮新增测试文件改变了分片成员(分片按文件名轮转分配,加一个
文件会把它之后的文件挪一片),把这条潜伏的顺序依赖换了个分片曝光出来。

## 修法

判定改为**调用时**解析(``_resolve_truth_ingress()``),让一次偶发的 import 失败
只影响那一次调用,而不是永久废掉整条路径;取不到时日志从 debug 升到 warning
—— 一条治理链路断了,不该只在 debug 里说。
"""

from __future__ import annotations

import pytest

import core.android_evaluator_artifact_ingress as ingress


def _make_message(device_id: str) -> dict:
    return {
        "type": "evaluator_artifact",
        "device_id": device_id,
        "evaluator_kind": "governance",
        "session_id": f"s-{device_id}",
        "payload": {"is_compliant": True, "verdict_label": "ok"},
    }


@pytest.fixture
def flow_runtime():
    flow = pytest.importorskip("core.flow_level_truth_ownership")
    flow.reset_flow_truth_alignment_runtime()
    yield flow.get_flow_truth_alignment_runtime()
    flow.reset_flow_truth_alignment_runtime()


def test_truth_path_survives_an_import_time_failure(flow_runtime, monkeypatch):
    """**核心回归。**

    模拟"本模块 import 那一刻上游导不进来"这个已经发生过的失效态:把
    import 期锁定的两个标志按失败态设置,再走一次 ingest。

    改之前:这条路径被永久关掉,``total_decisions`` 纹丝不动。
    改之后:调用时重新解析,照样写进去。
    """
    monkeypatch.setattr(ingress, "_TRUTH_INGRESS_AVAILABLE", False, raising=False)
    monkeypatch.setattr(ingress, "_ingest_truth_message", None, raising=False)

    before = flow_runtime.build_snapshot().total_decisions
    outcome = ingress.ingest_android_evaluator_artifact(_make_message("dev-latch"))

    assert outcome.was_stored is True, "前置条件不成立:产物本身没存下来"
    after = flow_runtime.build_snapshot().total_decisions
    assert after > before, "import 期标志为失败态时,治理产物就再也写不进真相运行时了 —— 路径被永久锁死"


def test_normal_path_still_writes(flow_runtime):
    """不能为了兜住失效态就把正常路径也改坏。"""
    before = flow_runtime.build_snapshot().total_decisions
    ingress.ingest_android_evaluator_artifact(_make_message("dev-normal"))

    assert flow_runtime.build_snapshot().total_decisions > before


def test_unavailable_truth_ingress_is_reported_at_warning_level(monkeypatch, caplog):
    """真相入口取不到时必须**说出来**,而且不能只在 debug 级说。

    一条治理链路断掉却只留一行 debug,等于没留 —— 生产日志级别通常在 INFO 及以上。
    """
    import builtins

    real_import = builtins.__import__

    def _fail_truth_ingress(name, *args, **kwargs):
        if name == "core.android_participant_truth_ingress":
            raise ImportError("模拟上游不可用")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(ingress, "_ingest_truth_message", None, raising=False)
    monkeypatch.setattr(builtins, "__import__", _fail_truth_ingress)

    with caplog.at_level("WARNING"):
        assert ingress._resolve_truth_ingress() is None

    assert any(
        "FlowTruthAlignmentRuntime" in rec.message or "真相入口" in rec.message for rec in caplog.records
    ), f"真相入口不可用却没有 WARNING 级日志,记录到的是:{[r.message for r in caplog.records]}"


def test_resolver_prefers_the_already_imported_function():
    """上游正常可用时,解析必须命中已 import 的那个函数,不做多余的 import 尝试。"""
    resolved = ingress._resolve_truth_ingress()
    assert resolved is not None
    if ingress._ingest_truth_message is not None:
        assert resolved is ingress._ingest_truth_message
