# Unified Subject Architecture

> **Core principle**: `DesktopPresenceRuntime` and `OpenClawd` are **not** two
> parallel subjects.  They are two layers of the *same* subject.

---

## 1. The Unified Subject

```
UFO Galaxy Subject
├─ DesktopPresenceRuntime  ← outer shell / Windows desktop "clothing"
└─ OpenClawd               ← inner cognition / execution core
```

The subject is a single entity.  The runtime shell is the **garment** the
subject wears when running on a Windows desktop; OpenClawd is the **mind**
inside.

### DesktopPresenceRuntime (outer shell)

The Windows desktop runtime shell is responsible for:

| Responsibility | Description |
|---|---|
| Tri-state lifecycle | Owns and drives `silent → liminal → manifest → silent` |
| `runtime_session_id` | Generates the canonical correlation ID propagated to all downstream modules |
| Native multimodal ingress | Owns `MultimodalIngressBus` — continuous host perception (`PerceptionFrame`) |
| Session management | Creates `RuntimeSession` per request |
| Observability | Structured log entries at every state transition |
| Adapter surface intake | Receives requests from chat route / E2E / direct callers and funnels them into the subject lifecycle |

The shell does NOT perform cognition, decision-making, or execution — it
delegates all of that to OpenClawd inside the liminal phase.

### OpenClawd (inner core)

The subject core operates entirely **inside the liminal phase** of the shell's
tri-state lifecycle.  It is responsible for:

| Responsibility | Description |
|---|---|
| Ingest | Fuse request-bound `multimodal_context` via `MultimodalBus.ingest` |
| Continuum / cognition | `ContinuumOrchestrator.run()` → intent, posture, decision gate, `state_continuum` |
| Execution branching | `_determine_execution_path()` → `local` / `cross_device` / `hybrid` / `none` |
| Local manifestation | `DecisionExecutor` → Windows / System API actions |
| Cross-device expansion | `CommandRouter` → gateway substrate → remote devices |

---

## 2. The Canonical Subject Flow

```
                DesktopPresenceRuntime (shell)
                        │
      ┌─────────────────▼─────────────────────────────────┐
      │  SILENT  ──►  LIMINAL  ──►  MANIFEST  ──►  SILENT  │  (tri-state lifecycle)
      └─────────────────┼─────────────────────────────────┘
                        │  invokes OpenClawd inside LIMINAL
                        ▼
                  OpenClawd (core)
                        │
          ┌─────────────┴────────────────────────────────┐
          │  Stage 1: Ingest                              │
          │    PerceptionFrame (from shell ingress bus)   │
          │    multimodal_context fusion (per-request)    │
          │                                               │
          │  Stage 2: Liminal / Continuum                 │
          │    ContinuumOrchestrator → state_continuum    │
          │    tri_state_phase + runtime_domain           │
          │                                               │
          │  Stage 3: Branch                              │
          │    _determine_execution_path()                │
          │    → local / cross_device / hybrid / none     │
          │                                               │
          │  Stage 4: Manifest                            │
          │    local      → DecisionExecutor (Win/API)   │
          │    cross_device → CommandRouter → gateway     │
          │    hybrid     → both loops                    │
          └────────────────────────────────────────────── ┘
                        │
                returns to DesktopPresenceRuntime
                        │
               MANIFEST → SILENT (shell)
```

---

## 3. Three Distinct State Systems

These three systems must never be conflated:

### 3.1 Tri-State Lifecycle (Subject Lifecycle)

**Owner**: `DesktopPresenceRuntime`  
**Values**: `silent` / `liminal` / `manifest`  
**Meaning**: The subject's existential state as a whole.

```python
class TriState(str, Enum):
    SILENT   = "silent"    # subject at rest; host ingress continues
    LIMINAL  = "liminal"   # OpenClawd cognition/execution in progress
    MANIFEST = "manifest"  # subject actively expressing
```

### 3.2 Continuum Posture (Internal State Protocol)

**Owner**: `OpenClawd` / `ContinuumOrchestrator`  
**Fields**: `tri_state_phase` + `runtime_domain`  
**Meaning**: Fine-grained internal state of the subject core.

```python
# tri_state_phase: silent | liminal | manifest (internal resolution)
# runtime_domain:  local | cross_device | transition | null
```

This is an *internal protocol detail* — not the same as the shell's tri-state
lifecycle even though the names are similar.

### 3.3 UI Shell Expansion Modes (Desktop Clothing)

**Owner**: `system_integration/hardware_trigger.py`,
`system_integration/state_machine_ui_integration.py`  
**Values**: `DORMANT` / `ISLAND` / `SIDESHEET` / `FULLAGENT`  
**Meaning**: How the Windows desktop clothing is rendered on screen.

These are **presentation-only**.  They do not drive the tri-state lifecycle
and do not represent the continuum posture.

```python
class SystemState(Enum):
    DORMANT   = "dormant"    # clothing hidden / collapsed
    ISLAND    = "island"     # compact clothing mode
    SIDESHEET = "sidesheet"  # side panel expansion
    FULLAGENT = "fullagent"  # full clothing expansion
```

---

## 4. Two Multimodal Input Paths

### 4.1 Continuous Host Perception (Runtime Shell)

**Owner**: `DesktopPresenceRuntime` via `MultimodalIngressBus`  
**Module**: `core/multimodal/ingest_runtime.py`, `core/multimodal/ingress_bus.py`  
**Output**: `PerceptionFrame` stream  
**Lifetime**: Background loop, independent of individual requests  
**Purpose**: Ambient sensory awareness of the Windows host device

### 4.2 Request-Bound Multimodal Context (Subject Core)

**Owner**: `OpenClawd.process(multimodal_context=...)` → `MultimodalBus.ingest()`  
**Module**: `core/perception/multimodal_bus.py`  
**Output**: `fusion_summary` appended to the LLM prompt  
**Lifetime**: Per-request; scoped to a single `process()` call  
**Purpose**: Caller-attached images / audio clips for a specific request

---

## 5. Liminal Execution Branching

Inside the liminal phase, `OpenClawd._determine_execution_path()` resolves
which execution loop to activate:

| `execution_path` | Description |
|---|---|
| `"local"` | Local Windows / System API manifestation via `DecisionExecutor` |
| `"cross_device"` | Cross-device expansion via `CommandRouter` → `galaxy_gateway` substrate |
| `"hybrid"` | Both local and cross-device loops run concurrently |
| `"none"` | No manifestation; subject responds without acting |

Cross-device routing is **not** a parallel system — it is the subject's
liminal execution expanding beyond the local Windows host.

---

## 6. Adapter Surfaces and Demoted Entrypoints

The following are **adapter surfaces / launchers** — they do NOT have
subject-core authority:

| Surface | Role |
|---|---|
| `core/routes/chat.py` | HTTP adapter → `DesktopPresenceRuntime.handle_request()` |
| `galaxy_gateway/app.py` | WebSocket protocol adapter (internal cross-device substrate) |
| `main.py` | Bootstrap launcher script only |
| `unified_launcher.py` | Bootstrap launcher script only |
| `start_galaxy.py` | Bootstrap launcher script only |
| `start_l4.py` | Bootstrap launcher script (deprecated, delegates to unified_launcher) |
| `start.sh` / `start.bat` / `start_unified.sh` | OS-level bootstrap scripts only |
| `dashboard/` | Internal monitoring / admin UI (not a subject entrypoint) |
| `windows_client/` | Desktop UI client (presentation layer; not a subject entrypoint) |
| `android_client/` | Android companion app (remote device adapter; not a subject entrypoint) |

None of these surfaces drive the subject lifecycle directly.  All user input
funnels through `DesktopPresenceRuntime.handle_request()`.

---

## 7. Gateway Role Clarification

`galaxy_gateway` is the **internal cross-device execution substrate** of the
subject — transport plumbing for the liminal cross-device loop:

```
OpenClawd (liminal branch: cross_device)
    └─ CommandRouter (cross-device expansion arm)
          └─ galaxy_gateway (internal substrate — WebSocket transport)
                └─ remote devices
```

The gateway does NOT initiate subject lifecycle and does NOT have
subject-core authority.  It is a protocol adapter that receives routed
commands from the subject core and forwards them to device endpoints.

---

## 8. Summary Table

| Concept | Owner | Layer |
|---|---|---|
| Tri-state lifecycle | `DesktopPresenceRuntime` | Outer shell |
| `runtime_session_id` | `DesktopPresenceRuntime` | Outer shell |
| Native multimodal ingress | `DesktopPresenceRuntime` → `MultimodalIngressBus` | Outer shell |
| Cognition (continuum) | `OpenClawd` → `ContinuumOrchestrator` | Subject core |
| Execution branching | `OpenClawd._determine_execution_path()` | Subject core |
| Local manifestation | `DecisionExecutor` | Subject core / local loop |
| Cross-device expansion | `CommandRouter` → `galaxy_gateway` | Subject core / cross-device loop |
| UI shell states | `system_integration/` | Desktop clothing |
| Desktop visual transitions | `desktop_projection/` | Desktop clothing |
| Chat / gateway / launchers | Various | Adapter surfaces (demoted) |
