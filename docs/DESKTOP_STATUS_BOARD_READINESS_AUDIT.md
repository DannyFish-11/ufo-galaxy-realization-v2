# Desktop Status Board Readiness Audit (Truthfulness Pass)

This audit answers one product question:

> **Can the current desktop status board be honestly presented as an operator control surface now?**

Short answer: **not yet**.

Current classification: **partially connected operator surface**  
(read-mostly observability + bounded config controls), **not** a fully
presentable control plane.

---

## 1) Verdict and presentability level

| Level | Meaning |
|---|---|
| Architecturally interesting codebase | Many runtime layers and contracts exist |
| Locally runnable technical demo | Single-host runtime + projection surfaces can run |
| Partial internal tooling surface | Desktop board can observe runtime and apply limited config toggles |
| Presentable operator surface | End-to-end operator authority, stable readiness, clear failure handling |
| Complete user-facing product slice | Full multi-device reliability + deployability + strong UX guarantees |

**Current repository placement:** between **“locally runnable technical demo”** and
**“partial internal tooling surface.”**

The desktop status board is **not** yet a complete operator-facing control page.

---

## 2) Desktop status board audit result

### What is real today

- Canonical runtime polling path exists:  
  `windows_client/status_board_v2/projection_reader.py` → `GET /api/v1/projection/runtime`
- Runtime truth/projection endpoints are available and read-only:
  - `GET /api/v1/projection/runtime`
  - `GET /api/v1/projection/runtime-truth`
  - `GET /api/v1/projection/desktop-status-board`
- Board renders tri-state/runtime projection as an observability surface.

### What is only partial

- The board has **bounded config write controls** (`--apply-toggle`,
  `--apply-routing-policy`) via `ConfigControlSurface`, but this is not the same
  as full operator execution authority.
- No first-class desktop command/dispatch workflow is provided in the board
  itself; request ingress remains API/adapter-driven (`POST /api/v1/chat`).
- The desktop board should not be marketed as a complete control plane yet.

### Classification for now

**Partial operator surface** (read-mostly observability + bounded config control),
not a finished operator product surface.

---

## 3) Backend/runtime foundation readiness (evidence-based)

| Area | Evidence | Audit result |
|---|---|---|
| Request ingress | `core/routes/chat.py` delegates to `DesktopPresenceRuntime.handle_request(...)` | Canonical path exists |
| OpenClawd canonical runtime path | `DesktopPresenceRuntime → OpenClawd` chain documented in code/docs | Connected for primary flow |
| Routing / dispatch authority | `CommandRouter` remains canonical dispatch authority in runtime design | Architecturally established |
| Projection/runtime truth surfaces | `core/routes/projection.py` runtime + runtime-truth endpoints | Connected read surfaces exist |
| Memory/planner/cognitive advisory layers | PR-17/18/19/20 layers integrated as advisory diagnostics | Present, mostly advisory |
| Readiness / activation gating | `OpenClawd._check_readiness(...)` + fallback trace wiring | Present in runtime path |
| Error/fallback behavior | fallback trace + execution trace wiring in `openclawd.py` | Present for observability |
| State continuity / presence lifecycle | `DesktopPresenceRuntime` tri-state session lifecycle | Canonical shell exists |

### Known gaps and caveats before “presentable control surface”

- Runtime closure gap inventory still lists deferred/known gaps in
  `core/runtime_closure_audit.py` (`GAP-512-*` catalog).
- `scripts/validate_runtime.py` currently reports baseline failures in this
  environment (for example missing `pydantic`/`fastapi` imports and deployment
  baseline checks), so “clone and instantly production-ready” is not a truthful claim.
- `core/architecture_completion.py` still reports partial dimensions
  (`capability_integration_completeness`, `installability_ecosystem_readiness`).

---

## 4) Cross-device / multi-device readiness

### What is real today

- Cross-device architecture, dispatch contracts, and acceptance-oriented test
  layers are extensive (for example `docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md`,
  `core/runtime/source_dispatch_orchestrator.py`, related tests).

### Why presentation is still bounded

- Full multi-device operation remains environment-dependent (real participants,
  gateway/network conditions, runtime configuration).
- Fresh clone supports meaningful single-host runtime and bounded/simulated
  cross-device scenarios, but should not be described as guaranteed full
  production multi-device operation by default.

---

## 5) Truthful statement for maintainers

Use this wording when presenting current status:

> The desktop status board is currently a **partial operator surface**: reliable
> runtime observability plus bounded configuration controls. It is **not yet** a
> full operator control plane for end-to-end task dispatch/execution management.

---

## 6) Readiness checklist before upgrading presentation claims

- [ ] Desktop surface provides explicit operator actions beyond bounded config
      toggles (with authoritative end-to-end execution semantics).
- [ ] Deferred runtime closure gaps required for operator presentation are closed
      or explicitly accepted with rationale.
- [ ] Cross-device workflows are verified against a reproducible non-local
      environment profile (not only local/simulated conditions).
- [ ] Runtime validation and dependency baseline pass in the intended target
      environment for presentation.
- [ ] Top-level docs consistently avoid framing status-board observability as
      equivalent to full control-plane readiness.

Until this checklist is satisfied, treat the board as an internal/technical
surface rather than a productized operator console.
