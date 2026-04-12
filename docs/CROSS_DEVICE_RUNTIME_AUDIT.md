# Cross-Device Runtime & Desktop Operator Readiness Audit

Last updated: 2026-04-12

---

## Audit question

**Has this repository reached a complete enough and integrated enough state that the desktop status board can be the operator-facing interface for the full system?**

Short answer: **not yet**.

---

## Evidence base (code + docs + runtime checks)

- Canonical ingress/authority path declarations:
  - `main.py`
  - `core/routes/chat.py`
  - `core/desktop_presence_runtime.py`
  - `core/openclawd.py`
- Projection/runtime truth surfaces:
  - `core/routes/projection.py`
- Desktop surface implementation:
  - `windows_client/status_board_v2/app.py`
  - `windows_client/status_board_v2/projection_reader.py`
  - `windows_client/status_board_v2/config_control.py`
  - `windows_client/status_board_v2/ACTIVE_SURFACE.md`
- Clone/runtime expectation docs:
  - `docs/CLONE_TO_USE_REALITY.md`
  - `docs/WINDOWS_STATUS_BOARD.md`
- Baseline validation run from fresh agent environment:
  - `python scripts/validate_runtime.py` (failed checks include missing `pydantic` / `fastapi` imports and unmet deployment baseline)

---

## A) Cross-device / multi-device runtime reality

### What is credibly runnable from clone

- Single-host startup and local API/projection surfaces are clearly defined (`python main.py`, projection/chat endpoints).
- Runtime projection endpoints include multi-device-oriented surfaces (for example `GET /api/v1/projection/runtime/multi-device`).

### What is environment-dependent

- Full cross-device/multi-device operation is not guaranteed by clone-only flow and requires external participants and connectivity assumptions (`docs/CLONE_TO_USE_REALITY.md` already states this).
- Baseline runtime validation in this environment shows dependency gaps (`pydantic`, `fastapi`) that block parts of the runtime import chain.

### What is structural/code-rich but not proven as canonical live path

- `core/runtime/source_dispatch_orchestrator.py` is extensive and heavily sentinel/policy coded, but `core/openclawd.py` does not call `orchestrate_source_runtime_dispatch(...)` in its canonical `process()` execution path.
- This indicates strong architecture/test scaffolding for source-side orchestration, but not a proven default production path through the main runtime ingress.

### Real prerequisites for credible multi-device operation

1. Runtime environment with required dependencies installed and validated (`fastapi`, `pydantic`, and related stack).
2. Live registered devices/hosts and routable transport connectivity.
3. Verified target-side execution adoption and source/target session truth consistency in non-simulated runs.
4. Operational observability confirming real remote dispatch outcomes (not only projection fallback/default payloads).

---

## B) Dispatch / routing / execution authority audit

## Canonical flow that is clearly connected

`/api/v1/chat` (compat adapter)  
→ `DesktopPresenceRuntime.handle_request(...)` (tri-state/lifecycle shell)  
→ `OpenClawd.process(...)` (subject-core execution authority)  
→ embedded `AgentKernel` cognition + execution handling in OpenClawd path.

This chain is explicitly documented in code-level module docs and implemented in the call path.

## Dispatch/routing observations

- OpenClawd carries extensive internal routing, fallback, and execution metadata surfaces.
- `AgentKernel` routing/delegation outputs are explicitly advisory; OpenClawd retains final authority.
- There is significant graceful-degradation logic (`try/except` fallbacks) that preserves response continuity but also means many layers can be unavailable without hard-stop.

## Authority classification

- **Canonical and connected:** chat ingress → runtime shell → OpenClawd core path.
- **Partially connected:** projection and runtime-truth surfaces expose many dispatch/routing diagnostics, but those are read-side snapshots and may include degraded/fallback states.
- **Code-rich/structural:** source dispatch orchestrator package (`core/runtime/source_dispatch_orchestrator.py`) is present and tested but not the observed default call path from canonical chat ingress.

---

## C) Agent/runtime stack audit (planner, memory, cognitive/advisory, shell)

- `DesktopPresenceRuntime` is in the canonical ingress path and owns tri-state lifecycle + runtime session correlation.
- `OpenClawd` is in the canonical path and owns subject-core processing.
- `AgentKernel` is embedded in OpenClawd path and is used for cognition/planning.
- PR-labeled advisory layers (activation budget, memory bias, runtime decision observability) are wired in the kernel and propagated as diagnostics/advisory signals.
- Many cognitive/advisory layers are best-effort and non-blocking by design; they can degrade silently.

**Interpretation:** the stack is architecture-rich and partially integrated in canonical runtime, but with a large advisory/degradation footprint and environment-sensitive completeness.

---

## D) End-to-end completeness assessment

Best-fit classification today:

- **Architecture-rich codebase** ✅
- **Partial runtime/demo slice with real canonical path** ✅
- **Mostly integrated local system** ⚠️ (only when dependencies/environment align)
- **Truly complete operational system** ❌ (not evidenced)

Reasoning:

- Canonical local path exists and is explicit.
- Cross-device/runtime-orchestration breadth is substantial in code/contracts/tests.
- Operational completeness remains gated by dependency/environment readiness and by gaps between “implemented module surface” vs “default canonical call-path usage”.

---

## E) Desktop status board as operator interface

## Direct readiness conclusion

Current status board is **not yet suitable as the real interface for operating the full system**.

Current truthful positioning:

- **Suitable for bounded/local operations only**:
  - runtime observability/projection display,
  - bounded config toggles/routing-policy writes through config authority (`ConfigControlSurface`).
- **Not suitable yet for full-system operator control**:
  - no canonical chat/task-command ingress in this board,
  - no proven end-to-end cross-device control-plane operation from board interaction to remote execution authority with operator-grade guarantees.

## Important documentation tension to be aware of

- Some repository docs describe the board as read-only (`docs/WINDOWS_STATUS_BOARD.md`, `docs/CLONE_TO_USE_REALITY.md`),
- while `status_board_v2` code and `ACTIVE_SURFACE.md` include bounded config write controls (provider toggle / routing policy).

So the truthful current state is: **read-only for task execution/dispatch, but not strictly read-only overall due to bounded configuration control actions.**

---

## Completeness matrix

| Subsystem | Current state | Classification | Evidence anchor |
|---|---|---|---|
| Canonical startup (`main.py` → launcher) | Explicit and runnable path declared | Partially connected (env-dependent) | `main.py`, validator output |
| Chat ingress adapter | Delegates to runtime shell/core; authority boundary explicit | Canonical and connected | `core/routes/chat.py` |
| Runtime shell lifecycle | Tri-state/session authority clearly implemented | Canonical and connected | `core/desktop_presence_runtime.py` |
| OpenClawd subject core | Main processing path and embedded kernel integration | Canonical and connected | `core/openclawd.py` |
| Planner/memory/advisory layers | Wired as advisory/diagnostics, with non-blocking degradation | Partially connected | `core/agent/kernel.py` |
| Projection runtime surface | Rich read-only projection endpoints | Canonical read-surface, not control plane | `core/routes/projection.py` |
| Runtime truth endpoint | Canonical compiled truth endpoint exists | Canonical read-surface, not control plane | `core/routes/projection.py` (`/runtime-truth`) |
| Source dispatch orchestrator package | Extensive contracts/sentinels/tests | Represented in code; not proven in default ingress call path | `core/runtime/source_dispatch_orchestrator.py`, no call in `core/openclawd.py` |
| Multi-device projection endpoint | Unified projection endpoint exists with graceful fallback assembly | Partial / environment-dependent | `core/routes/projection.py` (`/runtime/multi-device`) |
| Desktop status board | Strong observability + bounded config control; no full execution authority | Bounded/local only | `windows_client/status_board_v2/*`, `docs/WINDOWS_STATUS_BOARD.md` |

---

## Future-readiness checklist (must be true before full operator-surface claim)

- [ ] Dependencies/install profile is reproducibly complete for canonical runtime path (no missing `fastapi`/`pydantic` class of failures in baseline checks).
- [ ] End-to-end board-driven operator actions are defined for command/task ingress (not only projection + config toggles).
- [ ] Board actions map to explicit execution authority chain with auditable success/failure feedback.
- [ ] Cross-device dispatch path used in production flow is explicitly canonical (not only module-level availability/tests).
- [ ] Remote execution, fallback, and session-truth invariants are validated in live multi-device runs (not only simulated/degraded local contexts).
- [ ] Documentation is fully aligned on board capability boundaries (read-only vs bounded-control vs full control-plane).
- [ ] Operator safety controls (permissions/confirmations/rollback semantics) are enforced for board-initiated actions.

---

## Final product-facing statement

At present, this repository should be presented as a **rich architecture + partial integrated runtime with bounded desktop observability/control**, **not** as a fully complete multi-device operator product where the desktop status board is the full-system control interface.
