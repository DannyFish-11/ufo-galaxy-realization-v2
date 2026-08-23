"""tests/test_execution_isolation.py
=======================================
模型自己写出来的代码,跑在多硬的边界里。

修的是"能力在、路没接、判据不说实话"
------------------------------------
``SafeExecutor`` 的执行策略写着"优先委托 Node_09_Sandbox,降级到内置",而 Node_09
有自带的 Dockerfile(非 root)、``container_start_node`` 能把它跑进 Docker/Podman、
``container_runtime`` 能探运行时 —— 三块拼图齐全。断在一行::

    node09_url = os.environ.get("NODE09_SANDBOX_URL", "")   # 默认空串
    if self._node09_url:                                    # → 恒假

于是容器那条路**从来没被走到过**,代码一直跑在用户自己的内核、自己的用户身份下;
而 ``container_start_node`` 全仓只有面板上一个 HTTP 端点在调,要人手动点。

本文件钉三件事:判据只有一处、降级必须留痕、以及"宁可不跑也不在裸机上跑"那个
模式**真的会拒绝执行**(而不是嘴上说说然后照跑)。

不起容器、不触网:运行时探测与探活全部注入。
"""

from __future__ import annotations

import asyncio
import time

import pytest

import core.execution_isolation as ei
from core.execution_isolation import IsolationDecision, IsolationUnavailable, resolve_isolation


class _Resp:
    def __init__(self, code=200):
        self.status_code = code


class _Http:
    """探活替身。``alive`` 里的地址答 200,其余抛(= 连不上)。"""

    def __init__(self, alive=()):
        self.alive = set(alive)
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        base = url.rsplit("/health", 1)[0]
        if base in self.alive:
            return _Resp(200)
        raise OSError("connection refused")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("GALAXY_EXECUTION_ISOLATION", raising=False)
    monkeypatch.delenv("NODE09_SANDBOX_URL", raising=False)
    ei.reset_start_attempt()
    yield
    ei.reset_start_attempt()


# ══════════════════════════════════════════════════════════════════════════
# A. 判据:走哪一层
# ══════════════════════════════════════════════════════════════════════════


def test_a01_container_when_sandbox_is_reachable(monkeypatch):
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    d = resolve_isolation(client=_Http(alive={"http://127.0.0.1:7996"}), allow_start=False)
    assert d.tier == "container"
    assert d.is_isolated is True
    assert d.degraded is False


def test_a02_builtin_when_no_container_runtime(monkeypatch):
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    d = resolve_isolation(client=_Http(), allow_start=False)
    assert d.tier == "builtin"
    assert d.degraded is True, "回落到裸机必须算降级"
    assert "没装" in d.reason


def test_a03_builtin_is_never_reported_as_isolated(monkeypatch):
    """``is_isolated`` 是调用方唯一该信的那一位 —— 内置档一律为假。

    内置档是同一内核、同一用户、文件系统全可读。把它算成"有边界",
    等于让上层以为自己安全。
    """
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    d = resolve_isolation(client=_Http(), allow_start=False)
    assert d.tier == "builtin"
    assert d.is_isolated is False


def test_a04_explicit_endpoint_wins_and_needs_no_local_runtime(monkeypatch):
    """沙箱跑在别的机器上时,本机有没有 Docker 无关紧要。"""
    monkeypatch.setenv("NODE09_SANDBOX_URL", "http://sandbox-host:7996")
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    d = resolve_isolation(client=_Http(alive={"http://sandbox-host:7996"}), allow_start=False)
    assert d.tier == "container"
    assert d.endpoint == "http://sandbox-host:7996"


def test_a05_unreachable_explicit_endpoint_does_not_pretend(monkeypatch):
    monkeypatch.setenv("NODE09_SANDBOX_URL", "http://sandbox-host:7996")
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    d = resolve_isolation(client=_Http(), allow_start=False)
    assert d.tier == "builtin" and d.degraded is True


def test_a06_no_port_no_local_probe(monkeypatch):
    """端口读不出来时不该去探一个拼错的地址。"""
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 0)
    http = _Http()
    resolve_isolation(client=http, allow_start=False)
    assert http.asked == []


# ══════════════════════════════════════════════════════════════════════════
# B. 人的意愿:三档模式
# ══════════════════════════════════════════════════════════════════════════


def test_b01_builtin_mode_is_not_a_degrade(monkeypatch):
    """人明确要求的不算降级 —— 降级说的是"本来该更硬、没做到"。"""
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "builtin")
    d = resolve_isolation(client=_Http(), allow_start=False)
    assert d.tier == "builtin"
    assert d.degraded is False


def test_b02_container_mode_refuses_rather_than_degrades(monkeypatch):
    """这个模式的**全部含义**就是"宁可不跑,也不在裸机上跑"。

    降级会把它变成一句没有效力的话 —— 那正是本仓最不容许的形态。
    """
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "container")
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    with pytest.raises(IsolationUnavailable):
        resolve_isolation(client=_Http(), allow_start=False)


def test_b03_container_mode_passes_when_reachable(monkeypatch):
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "container")
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    d = resolve_isolation(client=_Http(alive={"http://127.0.0.1:7996"}), allow_start=False)
    assert d.tier == "container"


def test_b04_a_typo_does_not_silently_disable_isolation(monkeypatch):
    """拼错的取值按 auto 处理 —— 按"关掉"处理会让一个笔误静默降低安全等级。"""
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "containr")
    assert ei.isolation_mode() == "auto"


def test_b05_mode_vocabulary_is_closed():
    assert set(ei.ISOLATION_MODES) == {"auto", "container", "builtin"}


def test_b06_only_implemented_tiers_are_listed():
    """不给 microvm 留一个永远不会被返回的空取值 —— 那就是又一次"看起来接上了"。"""
    assert set(ei.ISOLATION_TIERS) == {"container", "builtin"}


# ══════════════════════════════════════════════════════════════════════════
# C. 后台拉起:不能卡在用户请求里
# ══════════════════════════════════════════════════════════════════════════


def test_c01_start_is_kicked_off_but_not_awaited(monkeypatch):
    """``container_start_node`` 首次要 build 镜像,它自己的超时上限是 1800 秒。

    在一次用户请求里同步等它是不可接受的 —— 所以探测同步、拉起后台。
    """
    calls = []
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    monkeypatch.setattr(ei, "_kick_off_container", lambda rt: calls.append(rt))
    d = resolve_isolation(client=_Http(), allow_start=True)
    assert calls == ["docker"]
    assert d.tier == "builtin", "拉起是后台的,这一次仍然落在内置"


def test_c02_read_only_report_never_starts_anything(monkeypatch):
    """体检是只读观测,不该顺手改变运行时状态。"""
    calls = []
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    monkeypatch.setattr(ei, "_kick_off_container", lambda rt: calls.append(rt))
    ei.isolation_report(client=_Http())
    assert calls == []


def test_c06_report_never_carries_exception_text(monkeypatch):
    """报告是 HTTP 端点的返回值,``str(exc)`` 放进去就是异常信息经响应外泄。

    客户端拿到的那句话与异常里那句**同源**(两边都调 ``blocked_reason``),
    所以既不外泄也不会措辞漂移。
    """
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "container")

    def _raise(**_kw):
        raise IsolationUnavailable("SECRET-INTERNAL-DETAIL")

    monkeypatch.setattr(ei, "resolve_isolation", _raise)
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    rep = ei.isolation_report(client=_Http())
    assert rep["blocked"] is True
    assert "SECRET-INTERNAL-DETAIL" not in str(rep)
    assert "error" not in rep, "装异常文本的那个字段已经换成布尔 blocked"


def test_c07_the_two_sides_say_the_same_thing():
    """一边 str(exc) 一边重写一遍,措辞迟早漂移 —— 所以两边都调 blocked_reason。"""
    assert ei.blocked_reason("", started=False) == ei.blocked_reason("", started=False)
    assert "没装" in ei.blocked_reason("", started=False)
    assert "已在后台" in ei.blocked_reason("docker", started=True)
    assert "没起着" in ei.blocked_reason("docker", started=False)


def test_c03_the_report_does_not_claim_a_start_it_did_not_do(monkeypatch):
    """第一版这里说了假话:allow_start=False 的那条路上照样写"已在后台拉起"。

    而这句 reason 正是给人看着判断该动哪里的 —— 它说谎,人就会去等一个
    根本没在拉的东西。
    """
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    monkeypatch.setattr(ei, "_kick_off_container", lambda rt: None)
    reason = ei.isolation_report(client=_Http())["decision"]["reason"]
    assert "已用" not in reason and "已在后台" not in reason


def test_c04_the_real_start_happens_once_not_every_execution(monkeypatch):
    """起不来通常是环境问题;每次执行都重试只会把每次执行都拖慢、日志刷满。

    钉的是**真正的拉起**只发生一次,不是"_kick_off_container 被调了几次" ——
    后者每次都会被调到,挡在里面的是模块级的 _start_attempted。
    """
    import core.node_lifecycle as nl

    started = []
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    monkeypatch.setattr(nl, "container_start_node", lambda n: (started.append(n), {"ok": False, "error": "x"})[1])

    for _ in range(3):
        resolve_isolation(client=_Http(), allow_start=True)
    # 拉起在后台线程里跑,给它一点时间落下来
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert len(started) == 1, f"真正的拉起应当只发生一次,实际 {len(started)} 次"


def test_c05_runtime_probe_delegates_to_the_existing_authority():
    """容器运行时探测不该有第二份 —— core.container_runtime 连"两个都装选哪个"
    的持久化都管着。"""
    import inspect

    body = inspect.getsource(ei.container_runtime_name)
    assert "container_runtime" in body
    assert "shutil.which" not in body


# ══════════════════════════════════════════════════════════════════════════
# D. 结果自己说它跑在哪 —— 降级必须留痕
# ══════════════════════════════════════════════════════════════════════════


def _run(code="print(1+1)", **kw):
    from core.safe_executor import SafeExecutor

    return asyncio.run(SafeExecutor().execute(code, **kw))


def test_d01_result_carries_where_it_actually_ran(monkeypatch):
    """在这一位之前,结果里根本说不出这件事。"""
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    r = _run()
    assert r.success is True
    assert r.isolation["tier"] == "builtin"
    assert r.isolation["is_isolated"] is False


def test_d02_default_isolation_field_assumes_the_worst():
    """拿不到判据时**不能让人以为自己有边界**。"""
    from core.safe_executor import ExecutionResult

    fresh = ExecutionResult()
    assert fresh.isolation["is_isolated"] is False
    assert fresh.isolation["degraded"] is True


def test_d03_a_sandbox_failure_leaves_a_trace(monkeypatch):
    """回落是必要的(不能让任务因为沙箱抽风直接失败),但不能悄悄回落。"""
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "docker")
    monkeypatch.setattr(ei, "_node09_port", lambda: 7996)
    monkeypatch.setattr(
        ei,
        "resolve_isolation",
        lambda **kw: IsolationDecision(tier="container", endpoint="http://127.0.0.1:7996", runtime="docker"),
    )
    import core.safe_executor as se

    async def _boom(*_a, **_k):
        raise OSError("sandbox exploded")

    monkeypatch.setattr(se.SafeExecutor, "_execute_via_node09", _boom)
    r = _run()
    assert r.success is True, "任务不该因为沙箱抽风而失败"
    assert r.isolation["tier"] == "builtin"
    assert r.isolation["degraded"] is True
    assert "沙箱容器调用失败" in r.isolation["reason"]


def test_d04_container_mode_blocks_execution_end_to_end(monkeypatch):
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "container")
    monkeypatch.setattr(ei, "container_runtime_name", lambda: "")
    r = _run()
    assert r.success is False
    assert "执行被拒绝" in r.error
    assert r.isolation["is_isolated"] is False


def test_d07_no_exception_text_reaches_the_caller(monkeypatch):
    """异常文本只进日志 —— 这个结果会经 HTTP 返回。

    CodeQL 在 PR #1616 上报了同一条(``core/routes/diagnostics.py``:
    "Information exposure through an exception"),而本仓早有既定处置:
    ``core/routes/modality.py`` 写着"异常详情只进服务端日志,不回传给客户端"。
    """
    monkeypatch.setenv("GALAXY_EXECUTION_ISOLATION", "container")

    def _raise(**_kw):
        raise IsolationUnavailable("SECRET-INTERNAL-DETAIL-/etc/shadow")

    monkeypatch.setattr(ei, "resolve_isolation", _raise)
    r = _run()
    assert "SECRET-INTERNAL-DETAIL" not in r.error
    assert "SECRET-INTERNAL-DETAIL" not in r.isolation["reason"]
    assert "execution-isolation" in r.error, "得给一条能自己查下去的路"


def test_d05_isolation_survives_to_dict():
    from core.safe_executor import ExecutionResult

    assert "isolation" in ExecutionResult().to_dict()


def test_d06_the_degrade_shape_has_one_definition():
    """迟早有一条路径漏掉 degraded=True,而那正是"以为自己有边界"的来源。"""
    import inspect

    import core.safe_executor as se

    src = inspect.getsource(se)
    assert src.count("def _degraded_from") == 1
    assert "degraded=True" in inspect.getsource(se._degraded_from)


# ══════════════════════════════════════════════════════════════════════════
# E. 开关登记齐全 —— 没登记 = 功能没接到面板上
# ══════════════════════════════════════════════════════════════════════════


def test_e01_switch_is_registered_backend_and_panel():
    from pathlib import Path

    from core.routes.config import CONFIG_SCHEMA

    assert "GALAXY_EXECUTION_ISOLATION" in CONFIG_SCHEMA
    root = Path(__file__).resolve().parent.parent
    panel = (root / "electron/renderer/panel/src/components/SettingsTab.tsx").read_text(encoding="utf-8")
    assert "'GALAXY_EXECUTION_ISOLATION'" in panel


def test_e02_the_description_says_what_builtin_actually_is():
    """面板上那句话得让人看得懂"内置档"意味着什么,而不是只写个档位名。"""
    from core.routes.config import CONFIG_SCHEMA

    desc = CONFIG_SCHEMA["GALAXY_EXECUTION_ISOLATION"]["description"]
    assert "同一内核" in desc
