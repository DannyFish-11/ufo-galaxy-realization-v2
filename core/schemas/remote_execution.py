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


class ExecutorTargetType(str, Enum):
    """Explicit executor target type for canonical dispatch routing.

    Carried in :class:`~core.schemas.task_envelope.TaskEnvelope` as
    ``executor_target_type``.  :meth:`CommandRouter.route_envelope` uses
    this field as the **first-class input** for selecting the dispatch path,
    rather than inferring the target kind from ID patterns, capability
    filters, or ``metadata`` heuristics.

    Values
    ------
    android_device
        Target is an Android device connected via the galaxy gateway
        (WebSocket / AIP protocol).  Routed through
        ``_route_cross_device_envelope()`` → ``DeviceRouter``.
    node_service
        Target is an internal Galaxy node service (e.g. Node_04_Router,
        Node_71_MultiDeviceCoordination).  Routed through
        ``_route_cross_device_envelope()`` → ``DeviceRouter``.
    go_worker
        Target is a Go-based edge worker addressed via NATS/MasterBrain.
        Routed through ``_route_worker_envelope()`` → ``MasterBrain``.
    local
        Task executes on the local runtime (Windows host / source device).
        Routed through ``_execute_command()`` directly.
    """

    android_device = "android_device"
    node_service = "node_service"
    go_worker = "go_worker"
    local = "local"


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
