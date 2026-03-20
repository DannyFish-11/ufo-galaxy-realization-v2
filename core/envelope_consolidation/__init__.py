#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.envelope_consolidation
============================

PR-8 (V3) — Execution Envelope Consolidation

A small, **additive** package that formalises the roles and interoperability
of the four canonical Galaxy envelope types:

+-------------------+---------------------------------------------------------+
| Role              | Canonical class                                         |
+===================+=========================================================+
| ``interaction``   | ``core.schemas.interaction_envelope.InteractionEnvelope``|
+-------------------+---------------------------------------------------------+
| ``task``          | ``core.schemas.task_envelope.TaskEnvelope``             |
+-------------------+---------------------------------------------------------+
| ``command``       | ``core.unified.command_envelope.CommandEnvelope``       |
+-------------------+---------------------------------------------------------+
| ``result``        | ``core.unified.command_envelope.ResultEnvelope``        |
+-------------------+---------------------------------------------------------+

This package does **not** replace any existing canonical model.  It provides:

* :class:`~.envelope_roles.EnvelopeRole` — formal role taxonomy enum
* :data:`~.envelope_roles.ROLE_DESCRIPTIONS` — machine-readable role metadata
* :func:`~.envelope_adapters.extract_trace_fields` — unified trace extraction
* :func:`~.envelope_adapters.propagate_trace` — cross-envelope trace propagation
* :func:`~.envelope_adapters.task_to_command_summary` — task → command summary
* :func:`~.envelope_adapters.result_to_observation` — result → PR-7 observation
* :func:`~.envelope_adapters.interaction_trace_fields` — interaction trace subset
* :class:`~.envelope_summary.EnvelopeSummary` — stable serialisable summary
* :func:`~.envelope_summary.summarise_envelope` — auto-role-inferred summary
* :func:`~.envelope_summary.envelope_role_catalog` — catalog for API/docs
* :func:`~.envelope_summary.summarise_result_for_projection` — projection helper
"""

from .envelope_roles import (
    EnvelopeRole,
    ROLE_DESCRIPTIONS,
    role_for_class,
    layer_for_role,
)
from .envelope_adapters import (
    extract_trace_fields,
    propagate_trace,
    task_to_command_summary,
    result_to_observation,
    interaction_trace_fields,
)
from .envelope_summary import (
    EnvelopeSummary,
    summarise_envelope,
    envelope_role_catalog,
    summarise_result_for_projection,
)

__all__ = [
    # roles
    "EnvelopeRole",
    "ROLE_DESCRIPTIONS",
    "role_for_class",
    "layer_for_role",
    # adapters
    "extract_trace_fields",
    "propagate_trace",
    "task_to_command_summary",
    "result_to_observation",
    "interaction_trace_fields",
    # summary
    "EnvelopeSummary",
    "summarise_envelope",
    "envelope_role_catalog",
    "summarise_result_for_projection",
]
