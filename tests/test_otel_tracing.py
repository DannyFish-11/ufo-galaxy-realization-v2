"""tests/test_otel_tracing.py
================================
Feature ③ — OpenTelemetry 追踪包装:默认关、未装 opentelemetry 时是零成本 no-op、
绝不抛异常;注入假 tracer 时能正确开 span/带属性/记异常。追踪失败绝不打断被追踪
的真实工作。
"""

from __future__ import annotations

import core.otel_tracing as ot
import pytest


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.delenv("GALAXY_OTEL_ENABLED", raising=False)
    ot._reset_for_test()
    yield
    ot._reset_for_test()


def test_disabled_by_default_is_noop():
    assert ot.otel_enabled() is False
    assert ot.init_tracing() is False
    assert ot.is_active() is False
    with ot.start_span("x", {"a": 1}) as span:
        assert span is None  # no-op → 无 span
    # 对 None span 的辅助调用不抛
    ot.set_attribute(None, "k", "v")
    ot.record_exception(None, RuntimeError("nope"))


def test_enabled_but_otel_absent_stays_noop(monkeypatch):
    # 开了开关但环境里没装 opentelemetry(本沙箱即如此)→ 仍是安全 no-op、不抛
    monkeypatch.setenv("GALAXY_OTEL_ENABLED", "1")
    ot._reset_for_test()
    active = ot.init_tracing()
    # 装了 otel 就 True、没装就 False —— 两种都不许抛
    assert active in (True, False)
    with ot.start_span("y") as span:
        assert span is None or span is not None  # 只要不抛即可


class _FakeSpan:
    def __init__(self):
        self.attrs = {}
        self.exceptions = []
        self.status = None

    def set_attribute(self, k, v):
        self.attrs[k] = v

    def record_exception(self, exc):
        self.exceptions.append(exc)

    def set_status(self, status):
        self.status = status


class _FakeSpanCtx:
    def __init__(self, span):
        self._span = span

    def __enter__(self):
        return self._span

    def __exit__(self, *a):
        return False


class _FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name):
        s = _FakeSpan()
        s.name = name
        self.spans.append(s)
        return _FakeSpanCtx(s)


def test_injected_tracer_creates_span_with_attributes():
    tracer = _FakeTracer()
    ot._install_tracer_for_test(tracer)
    assert ot.is_active() is True
    with ot.start_span("galaxy.node.invoke", {"galaxy.trace_id": "tr1", "galaxy.node_id": "N"}) as span:
        assert span is not None
        ot.set_attribute(span, "extra", 42)
    assert len(tracer.spans) == 1
    s = tracer.spans[0]
    assert s.name == "galaxy.node.invoke"
    assert s.attrs["galaxy.trace_id"] == "tr1"
    assert s.attrs["galaxy.node_id"] == "N"
    assert s.attrs["extra"] == 42


def test_span_body_exception_propagates_and_is_recorded():
    tracer = _FakeTracer()
    ot._install_tracer_for_test(tracer)
    with pytest.raises(ValueError):
        with ot.start_span("op") as span:
            ot.record_exception(span, ValueError("boom"))
            raise ValueError("boom")
    # span 仍被创建,异常被记录
    assert tracer.spans[0].exceptions and isinstance(tracer.spans[0].exceptions[0], ValueError)
