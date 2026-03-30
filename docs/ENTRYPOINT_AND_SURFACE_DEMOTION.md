# Entrypoint and Surface Demotion

> This document defines which surfaces in the UFO Galaxy codebase are
> **demoted from subject-core authority** and clarifies their correct roles.

See also: [UNIFIED_SUBJECT_ARCHITECTURE.md](UNIFIED_SUBJECT_ARCHITECTURE.md)

---

## 1. The Subject Authority Chain

Only two components have subject-core authority:

```
DesktopPresenceRuntime  (outer shell — tri-state lifecycle owner)
    └─ OpenClawd        (inner core — cognition + execution)
```

Everything else is an **adapter surface**, a **launcher**, a **protocol
substrate**, or a **presentation/clothing layer**.

---

## 2. Demoted Surfaces

### 2.1 Chat Route — `core/routes/chat.py`

**Previous implied role**: Primary API entrypoint  
**Correct role**: HTTP protocol adapter  
**What it should do**: Package HTTP request → call `DesktopPresenceRuntime.handle_request(source="chat")` → return response

```
POST /api/v1/chat
    → core/routes/chat.py  (adapter — no subject-core authority)
        → DesktopPresenceRuntime.handle_request()
            → OpenClawd.process()  (subject core)
```

### 2.2 Galaxy Gateway — `galaxy_gateway/app.py`, `device_router.py`, `cross_device_coordinator.py`, `cross_device_switch.py`

**Previous implied role**: Parallel entrypoint / primary system  
**Correct role**: Internal cross-device execution substrate  
**What it should do**: Receive routed commands from `CommandRouter` and forward to remote devices via WebSocket

```
OpenClawd (liminal cross-device branch)
    → CommandRouter
        → galaxy_gateway  (internal substrate — no subject-core authority)
            → remote devices
```

The gateway does NOT initiate subject lifecycle.  The only exception is
device registration (WebSocket lifecycle management), which is infrastructure,
not subject lifecycle.

### 2.3 Launcher Scripts

**Active authoritative scripts**: `main.py`, `unified_launcher.py`, `start.sh`, `start.bat`, `start_unified.sh`  
**Removed (post-PR-10 cleanup)**: `start_galaxy.py`, `start_l4.py` — fully deleted; they were compatibility wrappers that delegated to `unified_launcher.py`.  
**Correct role**: OS-level / process bootstrap scripts  
**What they should do**: Set up the process environment, initialise supporting
services, start the HTTP server.  They do NOT drive subject lifecycle.

Launcher scripts may call `get_desktop_presence_runtime()` to initialise the
singleton, but they do not call `handle_request()` — that is the caller's
(adapter surface's) job.

### 2.4 Dashboard — `dashboard/`

**Previous implied role**: System control plane / monitoring  
**Correct role**: Internal monitoring and admin UI  
**Status**: Removed from mainline subject architecture narrative.

The dashboard is an internal observability tool.  It may read state from the
runtime shell and subject core via APIs, but it does NOT drive subject
lifecycle and is NOT a subject entrypoint.

In deployments that do not require the dashboard, it can be omitted without
affecting the subject (DesktopPresenceRuntime + OpenClawd).

### 2.5 Windows Client — `windows_client/`

**Previous implied role**: Subject UI  
**Correct role**: Desktop UI client (clothing / presentation layer)  
**Status**: Removed from mainline subject architecture narrative.

The Windows client is a *presentation* client — it renders the subject's
state on the Windows desktop.  It is part of the desktop clothing, not the
subject core.  Functionally equivalent to `desktop_projection/` in the
presentation hierarchy.

### 2.6 Android Client — `android_client/`

**Previous implied role**: Mobile subject entrypoint  
**Correct role**: Remote device adapter / companion app  
**Status**: Removed from mainline subject architecture narrative.

The Android client is a remote device adapter.  It connects to the subject
via the gateway's WebSocket transport.  It is NOT a subject entrypoint; the
subject (DesktopPresenceRuntime + OpenClawd) runs on the Windows host.

---

## 3. Correct Startup / Request Flow

```
OS bootstrap (start.sh / start.bat)
    └─ main.py / unified_launcher.py  (launcher — bootstrap only)
          └─ FastAPI / HTTP server starts
                └─ GET/POST /api/v1/chat  ← HTTP request arrives
                      └─ core/routes/chat.py  (adapter)
                            └─ DesktopPresenceRuntime.handle_request()  ← SUBJECT ENTRY
                                  └─ SILENT → LIMINAL
                                        └─ OpenClawd.process()  ← CORE
                                              └─ ingest → continuum → branch → manifest
                                                    ├─ local: DecisionExecutor
                                                    └─ cross-device: CommandRouter → gateway
                                  └─ MANIFEST → SILENT
                                  └─ return {runtime_session_id, tristate, ...}
```

---

## 4. What "Demotion" Means

Demotion means:

1. **No subject-core authority**: The surface cannot drive the tri-state
   lifecycle on its own.  All requests must flow through
   `DesktopPresenceRuntime.handle_request()`.

2. **No bypassing the shell**: Calling `OpenClawd.process()` directly (without
   going through the runtime shell) loses session correlation and tri-state
   observability.  The shell should always be the outer wrapper.

3. **No parallel subject narrative**: Documentation, code comments, and startup
   paths must not describe these surfaces as "the system" or "the entrypoint".
   They are adapters, substrates, launchers, or presentation layers.

4. **Still functional**: Demotion is an architectural clarity change.
   Demoted surfaces continue to operate; they just do so in their correct role.

---

## 5. Cross-Device Policy Modules — `core/cross_device_policy/`

**Correct role**: Liminal domain policy — part of the subject's execution
branching logic inside OpenClawd.  These modules are consulted during
`_determine_execution_path()` to decide whether a cross-device branch is
appropriate.

Cross-device policy is NOT a parallel system.  It is a policy input to the
subject's liminal execution branching.
