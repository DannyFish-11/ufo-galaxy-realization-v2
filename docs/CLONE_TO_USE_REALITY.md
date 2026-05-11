# Clone-to-Use Runtime Reality (Authoritative Quick Truth)

This document is the shortest truthful answer to:

- what can be run from a fresh clone
- how to start it
- how to interact with it
- what the desktop status board does today
- what cross-device/multi-device means in current runtime terms

---

## 1) Fresh clone → first run

```bash
git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git
cd ufo-galaxy-realization-v2
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional (dev lint/test tooling):

```bash
pip install -r requirements-dev.txt
```

---

## 2) Canonical backend startup path

Primary startup command:

```bash
python main.py --host 127.0.0.1 --port 8299
```

`main.py` is the top-level orchestrator and delegates to `unified_launcher.py`.

---

## 3) Canonical interaction surfaces

After startup, use these surfaces first:

- **Chat/API ingress**: `POST /api/v1/chat`
- **Runtime projection**: `GET /api/v1/projection/runtime`
- **Runtime truth snapshot**: `GET /api/v1/projection/runtime-truth`
- **Status WebSocket (optional observability)**: `GET /ws/status`

Minimal local interaction check:

```bash
curl -sS -X POST "http://127.0.0.1:8299/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","device_id":"local_cli"}'
```

---

## 4) Desktop status board reality

Wake command:

```bash
python -m windows_client.status_board_v2 --host 127.0.0.1 --port 8299
```

Truthful boundary:

- It is **read-only** (projection display / observability).
- It does **not** accept chat input and does **not** dispatch commands.
- Tri-state displayed is `silent / liminal / manifest`, owned by `DesktopPresenceRuntime`.

---

## 5) Cross-device / multi-device reality

Current codebase contains active cross-device runtime layers and projections
(gateway, dispatch orchestration, multi-device projection surfaces).  
However, a fully production-like multi-device setup requires additional
environmental participants (real devices, gateway connectivity, network setup,
and matching runtime configs).

Practical expectation from fresh local clone:

- ✅ You can run single-host backend + status/projection/API surfaces.
- ⚠️ You may run bounded/simulated cross-device workflows locally.
- ⚠️ Full multi-device operation is environment-dependent and not guaranteed by clone alone.

---

## 6) Packaging / deployment truth

Source-run is a supported mode (`python main.py`).

Deployment/packaging options also exist (Docker/Compose and Windows packaging
helpers), but they are optional for first local use:

- development compose: `docker-compose.yml`
- production/full compose: `deploy/compose/*.yml`
- desktop packaging helper: `build_exe.py`

---

## 7) Validation path (recommended)

Use these in order:

```bash
# Structural/runtime consistency checks (no full external infra needed)
python scripts/validate_runtime.py

# Minimal stack smoke path (gateway + stubs)
bash scripts/quick_verify.sh
```

If both pass, you have a confirmed local baseline for supported clone-to-use flow.

---

## 8) Unified registration prerequisites (PR993-aligned)

The machine-checkable registration prerequisite validator confirms that all
canonical modules required by the center-governed distributed intelligent agent
system (PR993) are present before you start the backend:

```python
from core.operational_registration_path import validate_registration_prerequisites
v = validate_registration_prerequisites()
print(v.summary)
# Expected: "Registration prerequisite validation PASSED: all 11 checks passed."
# (or PASSED WITH WARNINGS if optional deps are absent)
if v.failed_checks:
    for c in v.failed_checks:
        print(f"FAIL: {c.name} — {c.message}")
    raise SystemExit(1)
```

Or to see the full operational registration path (all registration kinds,
onboarding steps, and tier map):

```python
from core.operational_registration_path import get_operational_registration_path
path = get_operational_registration_path()
print(path.to_json())
```

### Registration tiers

| Tier | What it covers |
|------|---------------|
| `main_chain` | Device canonical (UDM), capability registry, gateway WebSocket, unified governance, runtime subject shell, session/axis, device router |
| `cross_device` | Android admission, Android state store, Android capability report, Android session participant, Android runtime host, dispatch binding, Android bridge |
| `compat` | Legacy device index (DeviceRegistry) — layered over UDM, preserved for compatibility |

### Key registration kinds and their canonical modules

| Kind | Canonical module |
|------|-----------------|
| `device_canonical` | `core/unified/device_manager.py` (UDM — write SSOT) |
| `device_android_admission` | `galaxy_gateway/android/handlers/registration.py` |
| `device_android_state` | `core/android_device_state_store.py` |
| `capability_registry` | `core/agent/capability_registry.py` |
| `capability_android_report` | `galaxy_gateway/android/handlers/capability_report.py` |
| `session_attached_runtime` | `core/attached_runtime_session_registry.py` (session SSOT) |
| `session_android_participant` | `core/android_participant_session_state.py` |
| `gateway_websocket` | `galaxy_gateway/routes/websocket.py` |
| `gateway_device_router` | `galaxy_gateway/device_router.py` |
| `governance_unified` | `core/unified_execution_governance.py` |
| `runtime_subject` | `core/desktop_presence_runtime.py` |

See `core/operational_registration_path.py` and
`tests/test_operational_registration_path.py` for the machine-checkable
implementation and full test coverage.

---

## 9) 第二阶段收口：统一 registration / acceptance 观察面

PR1114 之后，如果你不只想看“有哪些注册种类”，而是想直接看：

- 当前注册推进到哪一层
- 哪些层是 `ready / degraded / blocked / pending`
- 当前运行落在 `main_chain / cross_device / recovery / compat` 哪条链
- clone-to-use 验收到 prerequisites / API / Android 接入 / capability / task / closure 的哪一步
- Android ↔ V2 的最小接入标准当前是否成立

可直接查询：

```bash
curl -sS http://127.0.0.1:8299/api/v1/projection/operational-readiness
curl -sS http://127.0.0.1:8299/api/v1/projection/clone-to-use-acceptance
```

这里沿用上文 canonical backend startup 示例（见第 2 节）的默认本地端口 `8299`；如果你的
部署改了端口，请把 URL 换成实际监听地址。

这两个只读 surface 建立在现有 canonical 模块之上：

- `core/operational_registration_path.py`
- `core/runtime_readiness_matrix.py`
- `core/device_readiness.py`
- `core/android_device_state_store.py`
- `core/attached_runtime_session_registry.py`
- `core/android_participant_session_state.py`

它们不会创建平行系统，只负责把现有主链 / cross-device / degraded /
recovery 信号聚合成更可操作的状态面，便于维护者判断“现在到底注册到哪、
验收到哪、成功质量是什么”。
