#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — RemoteExecutionMode
=============================

Canonical enum representing the two remote execution styles available
over the unified cross-device substrate.

Both styles share the same underlying substrate (``CommandRouter`` →
gateway / WebSocket).  This abstraction makes the distinction explicit
so that downstream routing logic, observability tooling, and tests can
reason about the execution style without inspecting command names or
payload shapes.

``agent_runtime``
    Richer targets that can execute remote agent tasks.  The envelope
    carries an ``agent_execute`` (or ``agent_deploy`` + ``agent_execute``)
    payload dispatched via :meth:`CommandRouter.dispatch_agent_remote`.

``command_only``
    Thinner targets that can only accept structured commands / tasks
    dispatched via the gateway command path
    (:meth:`OpenClawd.send_gateway_command` → :meth:`CommandRouter.route_envelope`).
"""

from __future__ import annotations

from enum import Enum


class RemoteExecutionMode(str, Enum):
    """Remote execution style over the cross-device substrate.

    Both values are stable wire-format strings so that serialised envelopes
    remain readable across versions.

    Attributes
    ----------
    agent_runtime:
        Richer targets that can execute remote agent tasks
        (``agent_execute`` / ``agent_deploy`` payloads).
    command_only:
        Thinner targets that can only accept structured
        commands / tasks dispatched via the gateway command path.
    """

    agent_runtime = "agent_runtime"
    command_only = "command_only"
