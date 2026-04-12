# Product Readiness Audit — Desktop Status Board & Runtime Foundations

This document is a dedicated, evidence-based readiness audit for one question:

> Is the system complete enough (backend/runtime/cross-device) that the desktop
> status board can be honestly presented as a usable operator/control surface?

---

## Audit conclusion (short answer)

Current repository state is best described as:

- **architecture-rich codebase**
- **partially demoable local runtime slice**
- **not yet a fully presentable operator-control product surface**

The desktop status board today is **observability-first with bounded config
controls**, not a complete operations console.

---

## 1) Desktop status board readiness

### What it is today

- Canonical board implementation is `windows_client/status_board_v2/`.
- It reads projection state from `GET /api/v1/projection/runtime`
  (`ProjectionReader`, `PROJECTION_ENDPOINT`).
- It can perform **bounded config writes** via `--apply-toggle` and
  `--apply-routing-policy`, delegated to `ConfigControlSurface` →
  `ConfigService` → runtime config.

### What it is not yet

- Not a full command/control authority surface.
- Not chat ingress (`POST /api/v1/chat` remains adapter ingress).
- Not dispatch authority for arbitrary task execution.

### Classification

- **Partial operations surface** (observability + limited config controls),
  **not** a fully presentable operator console yet.

---

## 2) Backend/runtime completeness (truthful status)

### Canonical and connected

- Runtime shell and lifecycle ownership are explicit in
  `core/desktop_presence_runtime.py` (`silent → liminal → manifest → silent`).
- Chat ingress delegates through canonical runtime shell
  (`core/routes/chat.py` → `DesktopPresenceRuntime.handle_request(...)`).
- Projection and runtime-truth endpoints exist in `core/routes/projection.py`.

### Partially connected / environment-gated

- Many runtime surfaces are present behind optional imports and graceful
  degradation behavior.
- In clean environments, broad validation can fail without full dependencies
  (for example `fastapi`, `pydantic`) and therefore clone-only is not sufficient
  to claim full runtime completeness.

### Stale/misleading risk addressed by this audit

- Some historical docs can read as more complete than current runtime reality.
- This audit is the product-truth reference to prevent “runnable” from being
  interpreted as “product-ready control plane”.

---

## 3) Cross-device / multi-device status

### Real capability present

- Canonical cross-device orchestration code exists
  (`core/runtime/source_dispatch_orchestrator.py`) with local/remote/fallback
  and staged-mesh paths.

### Practical readiness limits

- Full multi-device operation depends on real participants (target runtimes,
  gateway connectivity, network conditions, runtime configs).
- Fresh clone primarily guarantees local single-host operation, not guaranteed
  production-like multi-device operations.

### Classification

- **Structural + bounded practical capability**, not universally deployable
  multi-device product readiness by clone alone.

---

## 4) Presentability and product truth

Truthful positioning today:

- ✅ Presentable as an engineering/runtime foundation with observability surfaces.
- ⚠️ Presentable as partial internal demo/runtime slice.
- ❌ Not yet honest to present as finished desktop operations interface for
  end-user-grade control workflows.

---

## 5) Conditions required before treating the board as a presentable operations interface

All conditions below should be true at the same time:

1. **Runtime baseline green in representative environments**  
   Canonical validation/testing path passes without dependency holes.

2. **Operations authority boundaries are explicit and enforced**  
   Clear distinction between:
   - observability
   - bounded config control
   - task/dispatch execution authority

3. **Cross-device runtime proven beyond structural code presence**  
   Repeatable, real multi-device orchestration demos and failure behavior
   validation under realistic connectivity.

4. **State continuity and diagnostics are operator-trustworthy**  
   Session continuity, lifecycle transitions, fallback behavior, and diagnostics
   stay coherent across local and cross-device paths.

5. **Documentation consistency (no contradictory readiness claims)**  
   Top-level and board docs consistently describe current limits and non-goals.

---

## Future-readiness checklist

- [ ] Validation baseline is dependency-complete and green for canonical run path.
- [ ] Desktop board control capabilities are intentionally expanded (or explicitly
      kept bounded) with corresponding security/governance guardrails.
- [ ] Multi-device orchestration is verified in reproducible real-device scenarios.
- [ ] Runtime-truth endpoints and operator-facing docs stay aligned release to release.
- [ ] Product messaging no longer relies on “structure exists” when runtime closure
      is still environment-conditional.
