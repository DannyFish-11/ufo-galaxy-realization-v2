"""
Cross-Device Switch — "has this computer joined the device network?"
=====================================================================

The panel's 「跨设备」 button.  It says one thing: whether **this computer** joins
the device network as a device (the desktop registers itself as a member that
other devices and the agent may use; the computer's own requests may be handed
to other devices — see :func:`core.unified.entrypoint_router.resolve_entry_mode`).

It is **not** a gate on the central agent.  Every device decides for itself
whether it joins — its own switch (phone, other computers) or pairing (watch) —
and the agent coordinates every device that joined, whatever mode the computer
it runs on is in.  Dispatch to another device is decided by membership (the
registry, the connection, the permission gate), never by this switch.  (It used
to be a routing gate that refused every dispatch in local mode; that conflated
"the computer joins" with "the agent may coordinate".)

What "ON" means is decided in exactly one place:
:func:`core.system_mode.cross_device_requested` — ``GALAXY_CROSS_DEVICE_ENABLED``
true *or* ``GALAXY_SYSTEM_MODE=desktop-cross-device``.  This module does not
derive it again.
"""


def is_cross_device_enabled() -> bool:
    """Return ``True`` when this computer has joined the device network as a device.

    Reads the environment at call-time so the switch can be toggled without
    restarting the process (useful for tests).  Default: **off** (local mode).
    The answer comes from :func:`core.system_mode.cross_device_requested` — the
    same one the startup orchestrator, the desktop presence runtime and the
    health check use.
    """
    from core.system_mode import cross_device_requested

    return cross_device_requested()


__all__ = ["is_cross_device_enabled"]
