# Cross-Device Runtime & Status Board Readiness Audit

_Audit date: 2026-04-12_

This is a deliberate **truth-over-optimism** audit of runtime completeness for:

- cross-device / multi-device behavior
- dispatch / routing / execution authority
- planner/memory/advisory/runtime shell stack
- end-to-end integration for operator use
- desktop status board readiness as a whole-system interface

## Evidence base used for this audit

- Canonical startup and launcher chain:
  - `main.py`
  - `unified_launcher.py`
- Canonical chat ingress and runtime handoff:
  - `core/routes/chat.py`
  - `core/desktop_presence_runtime.py`
  - `core/openclawd.py`
- Projection / status-surface path:
  - `core/routes/projection.py`
  - `windows_client/status_board_v2/projection_reader.py`
  - `windows_client/status_board_v2/app.py`
  - `windows_client/status_board_v2/config_control.py`
- Dispatch / governance / planner stack:
  - `core/runtime/source_dispatch_orchestrator.py`
  - `core/agent/kernel.py`
  - `core/agent/execution_planner.py`
  - `core/node_invocation_governance.py`
- Baseline runtime checks:
  - `python scripts/validate_runtime.py` (run during this audit)

---

## A) Cross-device / multi-device audit

### What is truly runnable from clone on one host

- Single-host startup path is explicit and wired (`python main.py`).
- API ingress and projection surfaces are runnable on one host.
- Status Board V2 can poll runtime projection from one host.

### What is bounded/local/simulated or environment-gated

- `core/runtime/source_dispatch_orchestrator.py` contains advanced cross-device dispatch logic and staged-mesh semantics, but clone-only operation does not guarantee real remote participants, gateway connectivity, or routable devices.
- Runtime validation currently reports dependency gaps (`pydantic`, `fastapi`, `numpy`) and fails full baseline closure, so clone-and-run cannot be treated as guaranteed product-complete runtime.
- Multi-device participation depends on external conditions (active devices, network reachability, matching runtime config), not repository code presence alone.

### Practical prerequisite truth for credible multi-device operation

1. All required runtime dependencies installed and importable in the target environment.
2. At least one verified remote runtime/device participant with stable registration + routability.
3. Verified dispatch-to-target execution and result return path under real network conditions.
4. Projection surfaces proving live cross-device truth (not only local fallback/degraded snapshots).

---

## B) Dispatch / routing / execution authority audit

### Canonical connected flow (present)

- `/api/v1/chat` in `core/routes/chat.py` delegates to `DesktopPresenceRuntime.handle_request(...)`.
- `DesktopPresenceRuntime` is the runtime shell authority and invokes `OpenClawd` within lifecycle transitions.
- `OpenClawd` contains execution branching semantics (`local` / `cross_device` / `hybrid` / `none`).

### Partial / conditional / compatibility paths

- `core/node_invocation_governance.py` enforces invocation governance but still contains explicit compat/internal bypass (`COMPAT_INTERNAL`) and unregistered-unmanaged allowance for backward compatibility.
- This indicates authority is defined but not fully “hard-closed” in every path.

### Structural or code-first layers not proven as canonical runtime path

- `core/runtime/source_dispatch_orchestrator.py` is heavily specified and tested as canonical source-side dispatch orchestration, but current canonical chat ingress path evidence does not show direct wiring from `chat -> runtime shell -> openclawd` into `orchestrate_source_runtime_dispatch(...)`.
- Practical interpretation: strong architecture and test investment exists, but full canonical path integration for all user-facing flows is not yet unambiguous.

---

## C) Agent/runtime stack audit

### In canonical runtime path now

- Runtime shell lifecycle authority: `DesktopPresenceRuntime`.
- Subject core: `OpenClawd`.
- Embedded cognition/planning layer: `AgentKernel` (`core/agent/kernel.py`).

### Present and wired as advisory/intelligence layers

- Planner and strategy shaping: `ExecutionPlanner`.
- Cognitive activation budget hints (PR-18 sentinel path in kernel/planner).
- Memory bias hints (PR-19 sentinel path in kernel/planner).
- Runtime decision observability explanations (PR-20 sentinel path in kernel/governance/projection alignment).

### Optional / degraded / environment-gated behavior

- Several layers are guarded by lazy imports and graceful degradation.
- Baseline validator in this audit run failed imports for key dependencies (`pydantic`, `fastapi`) and reported deployment baseline not met.
- Therefore “code exists” does not equal “all layers active in canonical runtime” in a fresh environment.

---

## D) End-to-end system completeness assessment

## Conclusion category

**Current best-fit description: _architecture-rich codebase with a partial runtime/demo-operational slice_**.

It is **not** yet evidenced as a fully complete operational system for whole-stack multi-device control.

Rationale:

- Canonical local path is identifiable and testable.
- Many advanced layers are present and instrumented.
- But full closure is blocked by dependency/environment sensitivity and by gaps between module-level canonical claims and clearly demonstrated end-to-end operator flows.

---

## E) Desktop status board as system interface

## Direct readiness conclusion

**Desktop Status Board V2 is currently suitable for bounded/local observability, but not yet suitable as the real operator interface for the full system.**

### Why

- `projection_reader.py` is read-only and polls `/api/v1/projection/runtime`.
- `docs/WINDOWS_STATUS_BOARD.md` correctly states board is not chat/dispatch/execution control.
- `app.py` + `config_control.py` add bounded config writes (`--apply-toggle`, `--apply-routing-policy`) via canonical config service; this is configuration control, not end-to-end task command/control authority.
- No evidence in this audit that the board is the canonical ingress for full dispatch, routing, and cross-device execution authority.

---

## Completeness matrix (truth classification)

| Subsystem | Current state | Classification | Evidence summary |
|---|---|---|---|
| Startup authority (`main.py -> unified_launcher.py`) | Canonical and connected | **Complete (local startup authority)** | Explicit orchestrator/subordinate contract in both files |
| Chat ingress to runtime shell/core | Canonical and connected | **Complete (for chat ingress path)** | `core/routes/chat.py` delegates to `DesktopPresenceRuntime.handle_request` |
| Runtime shell lifecycle (`silent/liminal/manifest`) | Implemented and used in shell path | **Mostly complete (local path)** | `core/desktop_presence_runtime.py` owns lifecycle + session IDs |
| OpenClawd execution branch semantics | Implemented | **Partial (integration breadth unclear)** | Branch semantics documented in `core/openclawd.py` |
| Source-side cross-device dispatch orchestrator | Rich implementation and contracts | **Structural / partially connected** | `core/runtime/source_dispatch_orchestrator.py` exists; direct canonical ingress wiring is not clear from audited path |
| Node invocation governance | Real gate + compat bypasses | **Partial** | `core/node_invocation_governance.py` includes enforce + `COMPAT_INTERNAL`/unmanaged allowances |
| Planner/memory/advisory layers | Wired in kernel/planner as advisory | **Partial (environment-dependent activation)** | PR-18/19/20 sentinels in kernel/planner/governance |
| Projection runtime endpoint | Connected read-only surface | **Complete (observability path)** | `core/routes/projection.py` read-only design |
| Status Board V2 display path | Connected to projection runtime | **Complete (observability path)** | `projection_reader.py` + `app.py` poll/render loop |
| Status Board V2 as full control plane | Not established | **Not ready / misleading if presented as full operator plane** | No canonical task ingress/authority ownership in board path |
| Clone-to-use full multi-device operation | Not guaranteed | **Environment-dependent** | Runtime validation failures and external participant prerequisites |

---

## Future-readiness checklist (must become true first)

- [ ] Full dependency-complete baseline in clean environment (no `pydantic`/`fastapi`/other core import failures).
- [ ] Canonical end-to-end proof: ingress -> routing/dispatch -> execution -> result -> projection for local and cross-device modes.
- [ ] Explicit authority closure for dispatch and invocation (compat/internal bypasses constrained to non-operator paths).
- [ ] Real multi-device acceptance runbook with reproducible prerequisites and pass/fail evidence.
- [ ] Status board command/control contract defined and implemented (if board is to become operator surface), including:
  - [ ] command ingress
  - [ ] dispatch target selection visibility
  - [ ] execution confirmation and error propagation
  - [ ] rollback/fallback transparency
- [ ] Operator-facing docs aligned to runtime truth with no aspirational overstatement.

---

## Final answer to the product question

**No — this repository has not yet demonstrated a sufficiently complete, fully integrated state (across multi-device runtime, dispatch authority, agent stack, and environment closure) for the desktop status board to be honestly presented as the interface for connecting to and operating the full system.**

At present, the honest positioning is:

- **usable local runtime + observability board**
- **partially integrated cross-device/dispatch foundations**
- **not yet full operator control surface for the whole system**
