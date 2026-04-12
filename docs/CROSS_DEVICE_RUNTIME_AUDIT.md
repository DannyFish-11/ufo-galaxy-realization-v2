# Cross-Device Runtime and Operator-Surface Audit

Date: 2026-04-12  
Scope: repository code/document audit + local clone baseline checks

## Audit question

Can this repository currently support the desktop status board as the real operator interface for the full system (multi-device runtime + dispatch + agent stack + runtime integration)?

## Evidence used

- Canonical startup/orchestration: `main.py`, `unified_launcher.py`
- Canonical ingress/runtime shell/core chain: `core/routes/chat.py`, `core/desktop_presence_runtime.py`, `core/openclawd.py`
- Projection/status surfaces: `core/routes/projection.py`, `windows_client/status_board_v2/projection_reader.py`, `windows_client/status_board_v2/app.py`
- Cross-device orchestration and acceptance tests: `core/runtime/source_dispatch_orchestrator.py`, `tests/test_pr34_post533_cross_device_runtime_acceptance.py`
- Existing runtime truth docs: `docs/CLONE_TO_USE_REALITY.md`, `docs/WINDOWS_STATUS_BOARD.md`
- Local checks in this clone:
  - `python -m pytest tests/test_clone_to_use_runtime_truth.py -q` ✅
  - `flake8 core/ --max-line-length=120` ❌ (large pre-existing lint backlog)

---

## Completeness matrix (truthful classification)

| Subsystem | Classification | Evidence | Reality |
|---|---|---|---|
| Canonical startup path (`main.py` → `unified_launcher.py`) | **Complete (local entry authority)** | `main.py` declares canonical orchestrator and staged preflight | Canonical launch path is explicit and runnable for local stack bring-up. |
| `/api/v1/chat` ingress to runtime shell/core | **Partially connected** | `core/routes/chat.py` explicitly marks adapter role and delegates to `DesktopPresenceRuntime.handle_request()` | Path is connected, but as compatibility adapter surface; not itself an operator control plane. |
| Presence lifecycle/runtime shell | **Complete (for canonical shell lifecycle ownership)** | `DesktopPresenceRuntime.handle_request()` documents SILENT→LIMINAL→MANIFEST→SILENT flow | Lifecycle authority is clear and centralized in shell/core chain. |
| Planner/memory/advisory/cognitive hints in kernel stack | **Partially connected** | PR-17/18/19/20 sentinels and fields in `core/agent/kernel.py` and `core/agent/execution_planner.py` | Layers are wired as advisory/diagnostic signals; not all are hard execution gates. |
| Source dispatch/routing/fallback governance | **Partially connected** | `core/runtime/source_dispatch_orchestrator.py` has extensive policy/sentinel coverage and fallback contracts | Strong structure and tests exist, but module still documents deferred pieces (e.g., full mesh coordinator future PR). |
| Multi-device/cross-device runtime in clone-and-run conditions | **Environment-dependent** | `docs/CLONE_TO_USE_REALITY.md` states full multi-device requires real devices/network/config; PR34 tests have many optional imports/skip guards | Cross-device capabilities are present, but full operational completeness is not guaranteed by clone alone. |
| Status board projection rendering | **Complete (read path)** | `projection_reader.py` is read-only and polls `/api/v1/projection/runtime`; `projection.py` endpoint is read-only | Status projection/observability path is connected and usable locally. |
| Status board as full operator control surface | **Not yet suitable; bounded only** | `docs/WINDOWS_STATUS_BOARD.md` says no command dispatch/execution control; `app.py` + `config_control.py` only add bounded config writes | Board can observe runtime and apply narrow config toggles; it is not full command/dispatch authority for whole system. |
| Board-role messaging consistency across docs/modules | **Partially misleading / mixed** | `docs/WINDOWS_STATUS_BOARD.md` says read-only; `status_board_v2/config_control.py` says upgraded to control surface | Current repo messaging is mixed; practical reality is bounded config control + broad read-only observability, not full operator plane. |

---

## A) Cross-device / multi-device audit

### What is truly runnable now

- Local single-host stack with canonical startup and projection/status surfaces.
- Bounded cross-device flows can be exercised when required modules/dependencies are available.

### What is environment-dependent

- Production-like multi-device operation requires real participants (devices, network routes, gateway/session conditions, matching runtime config).
- PR34 acceptance tests explicitly guard many paths behind optional imports/dependency availability.

### Prerequisites for credible multi-device operation

1. Real device inventory + routable network path + gateway connectivity.
2. Stable dependency/install profile across required modules (not just optional local subset).
3. Repeatable cross-device E2E runbook with expected failure semantics and recovery behavior.

---

## B) Dispatch / routing / execution authority audit

- Canonical authority chain is explicit: ingress adapter → runtime shell → core execution (`chat.py`, `desktop_presence_runtime.py`, `openclawd.py`).
- Dispatch selection/fallback semantics are deeply formalized in `source_dispatch_orchestrator.py` with policy sentinels.
- Reality: this is a strong architecture-and-contract layer, but overall end-to-end operational completeness remains partial because multi-device execution still depends on environment readiness and optional components.

---

## C) Agent/runtime stack audit

- Planner/memory/advisory layers are present and threaded into kernel/planner outputs (task hint, activation budget hint, memory bias hint, runtime decision explanation).
- These layers are mostly advisory/diagnostic enrichments around execution decisioning, not universal hard gates.
- Runtime shell + presence lifecycle are in canonical path; auxiliary cognitive/observability layers are integrated but not equivalent to full production hardening proof.

---

## D) End-to-end completeness assessment

Best-fit classification:

- **Architecture-rich codebase** ✅
- **Mostly integrated local system** ✅
- **Partial runtime/demo slice for cross-device in clone-only conditions** ✅
- **Truly complete operational system** ❌ (not yet evidenced)

Reason: canonical local chain is clear and functional, but full multi-device operational guarantees are environment-gated and not proven by clone-only baseline.

---

## E) Desktop status board readiness as operator-facing interface

Direct assessment:

- **Suitable for bounded/local operations only** (runtime observability + narrow config operations).
- **Not suitable yet as the real interface to operate the full system.**

Why not yet:

1. No evidence that board is canonical command-dispatch and execution-authority surface across full runtime paths.
2. Cross-device operation remains environment-dependent and not guaranteed from clone baseline.
3. Repo messaging is mixed (read-only truth doc vs “upgraded control surface” wording) and needs convergence before product-facing positioning.

---

## Future-readiness checklist (must be true before full operator-surface claim)

- [ ] Board exposes canonical, authenticated command ingress for task dispatch (not only projection + config toggles).
- [ ] End-to-end execution feedback loop (submit → route → execute → result/error) is visible and reliable in board UX.
- [ ] Multi-device target selection, authority, confirmation, and rollback semantics are productized and tested with real devices.
- [ ] Cross-device E2E acceptance is reproducible without broad optional-skip dependency gaps.
- [ ] Runtime truth/projection parity is continuously tested so board state cannot overstate backend reality.
- [ ] Documentation is unified so board positioning is unambiguous (bounded observability/control vs full operator plane).

---

## Final answer to the core product question

**No — the repository is not yet at a level where the desktop status board can honestly be presented as the full-system operator interface.**  
Current truth is: strong architecture and local integration, with bounded board operations, but cross-device/full-operator completeness remains partial and environment-dependent.
