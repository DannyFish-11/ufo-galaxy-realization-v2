#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/otel_tracing.py
====================
Feature ③ of the reliability set — OpenTelemetry distributed tracing, wrapped so
it is **safe by default** and **zero-cost when off**.

Why a wrapper (and not raw OpenTelemetry calls)
-----------------------------------------------
Today ``trace_id`` is a bespoke string threaded through envelopes
(node_invocation / canonical_task / aip_v3), correlated only by string match.
It never enters a real span context, so it can't be viewed in an OTel backend
(Jaeger / Tempo / any OTLP collector).

OpenTelemetry is intentionally **not** a hard dependency of Galaxy — adding a
heavy tracing SDK to the default install risks breaking constrained/offline
setups. So this module:

- imports OpenTelemetry **lazily**, inside try/except;
- is a **no-op** (yields ``None`` spans, never raises) when OTel is not
  installed OR ``GALAXY_OTEL_ENABLED`` is off (the default);
- keeps the existing bespoke ``trace_id`` as a first-class span attribute
  (``galaxy.trace_id``) so both correlation schemes line up.

This means callers can wrap the hot path in ``with start_span(...)`` **always**,
with no runtime cost and no import risk when tracing is disabled.

Enable
------
Default: **on**, unconditionally. ``GALAXY_OTEL_ENABLED=0`` opts out.

(History: an earlier revision derived the default from
``galaxy_gateway.cross_device_switch.is_cross_device_enabled()`` on the theory
that cross-device is on by default system-wide. That premise was wrong —
``.env.example`` ships ``GALAXY_CROSS_DEVICE_ENABLED=false`` and
``core/system_mode.py`` (the *canonical* mode resolver) defaults to
``desktop-local`` when unset, so cross-device is actually OFF for every
fresh-clone install. Deriving OTel's default from it meant tracing silently
never activated for the common single-machine case, defeating the point of
"on by default". Decoupled: this flag now stands on its own.)

Requires ``opentelemetry-sdk`` installed (default dependency, auto-installed by
``main.py`` Phase 2 as of this change); still a safe no-op if absent.
Exporter selection:
- ``GALAXY_OTEL_EXPORTER=otlp`` + ``OTEL_EXPORTER_OTLP_ENDPOINT`` → OTLP export.
- ``GALAXY_OTEL_EXPORTER=console`` → console span exporter (debug).
- unset / anything else → provider with no exporter (spans created, not shipped;
  still useful for in-process assertions and future exporters).

Public API
----------
otel_enabled() -> bool
init_tracing() -> bool          # idempotent; True when a real tracer is active
is_active() -> bool
start_span(name, attributes=None) -> contextmanager  # yields span or None
set_attribute(span, key, value) -> None              # no-op if span is None
record_exception(span, exc) -> None                  # no-op if span is None
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.OtelTracing")

OTEL_TRACING_AUTHORITY: str = "OTEL_TRACING::NOOP_SAFE_LAZY_OPENTELEMETRY_V1"

# Process-level tracer state. `_tracer` is the OpenTelemetry Tracer (or a
# test-injected stand-in); `_active` gates all span work.
_state: Dict[str, Any] = {"initialized": False, "active": False, "tracer": None}


def otel_enabled() -> bool:
    """Whether OTel tracing is requested.

    Default **on**, unconditionally — ``GALAXY_OTEL_ENABLED=0`` (or any falsy
    spelling) opts out; ``=1``/unset both mean on.

    这个开关不再挂在跨设备开关上(见模块顶部 History 说明):.env.example 实际
    出厂值是 GALAXY_CROSS_DEVICE_ENABLED=false,core/system_mode.py(权威的模式
    解析器)在未显式设置时也是默认 desktop-local——也就是说对绝大多数"clone 下来
    直接跑"的单机用户,跨设备本来就是关的。挂靠在它上面,等于"默认开"从未在最
    常见的场景里真正生效过(真机复现:本模块上一版正是这样,用户合并后警告依旧
    在)。现在独立成自己的开关,不再借用别的子系统的默认值。
    """
    raw = os.getenv("GALAXY_OTEL_ENABLED")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return True


def _build_exporter():
    """Return a span processor for the configured exporter, or None."""
    choice = str(os.getenv("GALAXY_OTEL_EXPORTER", "")).strip().lower()
    try:
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
    except Exception:
        return None
    if choice == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            return BatchSpanProcessor(OTLPSpanExporter())
        except Exception as exc:  # noqa: BLE001
            logger.warning("OTLP exporter unavailable (%s); spans created but not shipped", exc)
            return None
    if choice == "console":
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            return SimpleSpanProcessor(ConsoleSpanExporter())
        except Exception:  # noqa: BLE001
            return None
    return None


def init_tracing() -> bool:
    """Initialise the tracer provider once. Returns True iff a real tracer is active.

    Idempotent and never raises. When OTel is absent or ``GALAXY_OTEL_ENABLED`` is
    off, leaves the module in no-op mode and returns False.
    """
    if _state["initialized"]:
        return bool(_state["active"])
    _state["initialized"] = True
    if not otel_enabled():
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": os.getenv("GALAXY_OTEL_SERVICE_NAME", "galaxy-v2"),
                    "service.namespace": "galaxy",
                }
            )
        )
        processor = _build_exporter()
        if processor is not None:
            provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        _state["tracer"] = trace.get_tracer("galaxy.v2")
        _state["active"] = True
        logger.info("OpenTelemetry tracing active (exporter=%s)", os.getenv("GALAXY_OTEL_EXPORTER", "none"))
    except Exception as exc:  # noqa: BLE001 — 观测增强绝不影响主流程
        logger.warning("OpenTelemetry unavailable, tracing stays no-op: %s", exc)
        _state["active"] = False
    return bool(_state["active"])


def is_active() -> bool:
    """True when a real tracer is installed and tracing is on."""
    return bool(_state["active"] and _state["tracer"] is not None)


@contextmanager
def start_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Context manager that starts a span, or a zero-cost no-op yielding ``None``.

    Safe to wrap the hot path unconditionally: when tracing is off/absent this is
    a bare ``yield None`` with no allocation of OTel objects.
    """
    # Lazy init on first use so callers don't have to remember to init_tracing().
    if not _state["initialized"]:
        init_tracing()
    tracer = _state["tracer"] if _state["active"] else None
    if tracer is None:
        yield None
        return
    # 只保护【建 span 本身】的失败(OTel 内部异常 → 退化成 no-op),绝不吞掉调用方
    # 主体的异常——主体异常必须原样通过 OTel 自己的 span 上下文传播(OTel 会自动记录
    # 并重抛),否则会破坏 contextmanager"只 yield 一次"的契约、也会掩盖真实错误。
    try:
        cm = tracer.start_as_current_span(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("start_span create suppressed: %s", exc)
        yield None
        return
    with cm as span:
        if attributes:
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:  # noqa: BLE001
                    pass
        yield span


def set_attribute(span: Any, key: str, value: Any) -> None:
    """Set a span attribute; no-op when span is None or setting fails."""
    if span is None:
        return
    try:
        span.set_attribute(key, value)
    except Exception:  # noqa: BLE001
        pass


def record_exception(span: Any, exc: BaseException) -> None:
    """Record an exception on the span; no-op when span is None."""
    if span is None:
        return
    try:
        span.record_exception(exc)
        try:
            from opentelemetry.trace import Status, StatusCode

            span.set_status(Status(StatusCode.ERROR, str(exc)))
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def _reset_for_test() -> None:
    """Test hook: clear tracer state so a test can re-init or inject a fake."""
    _state["initialized"] = False
    _state["active"] = False
    _state["tracer"] = None


def _install_tracer_for_test(tracer: Any) -> None:
    """Test hook: inject a stand-in tracer and mark active (bypasses OTel import)."""
    _state["initialized"] = True
    _state["active"] = True
    _state["tracer"] = tracer


__all__ = [
    "OTEL_TRACING_AUTHORITY",
    "otel_enabled",
    "init_tracing",
    "is_active",
    "start_span",
    "set_attribute",
    "record_exception",
]
