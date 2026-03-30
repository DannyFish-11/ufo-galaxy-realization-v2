# Galaxy — Test Migration Map

This file tracks the migration of `test_prXX_*` tests from the legacy flat
layout into the new capability-domain directory structure.

Tests listed here have been **moved** (the old file no longer exists).
Update bookmarks, CI references, and editor shortcuts accordingly.

---

## Migrated tests

| Old path (removed) | New canonical path | Domain |
|---|---|---|
| `tests/test_pr2_gateway_slimming.py` | `tests/unit/gateway/test_gateway_slimming.py` | Gateway app slimming & service wiring |
| `tests/test_pr2_chat_adapter_surface.py` | `tests/integration/chat/test_chat_adapter_surface.py` | Chat adapter surface (`/api/v1/chat`) |
| `tests/test_pr3_android_bridge_modularization.py` | `tests/integration/android_bridge/test_android_bridge_modularization.py` | AndroidBridge modularization |
| `tests/test_pr3_device_pool_routing.py` | `tests/unit/routing/test_device_pool_routing.py` | DevicePoolManager routing |
| `tests/test_pr3_device_router_session_adapter.py` | `tests/unit/routing/test_device_router_session_adapter.py` | DeviceRouter session adapter |
| `tests/test_pr3_unified_local_config.py` | `tests/unit/config/test_unified_local_config.py` | Unified local config (ConfigStore / ConfigSchema) |
| `tests/test_pr4_device_routing_dispatch_separation.py` | `tests/unit/routing/test_device_routing_dispatch_separation.py` | Device routing / dispatch separation |
| `tests/test_aip_v3_ws_contracts.py` | `tests/integration/websocket/test_aip_v3_ws_contracts.py` | AIP v3 WebSocket contracts |
| `tests/test_pr3_openclawd_subject_core.py` | `tests/unit/runtime/test_openclawd_subject_core.py` | OpenClawd subject-core authority |

---

## Removed legacy stubs

The following files in source packages were stubs that only raised
`ImportError` redirecting users to `tests/integration/`.  They have been
deleted as the canonical tests already exist under `tests/`.

| Removed stub | Canonical location |
|---|---|
| `galaxy_gateway/test_gateway_v3.py` | `tests/integration/test_gateway_v3.py` |
| `galaxy_gateway/test_nlu_v2.py` | `tests/integration/test_nlu_v2.py` |

---

## Remaining flat tests

All other `tests/test_*.py` files remain in the flat top-level directory.
They are still discovered by pytest (`testpaths = tests` in `pytest.ini`).
Future PRs should continue migrating them into the appropriate domain
subdirectory as they are modified or extended.

### Priority migration candidates (not yet moved)

| File | Suggested new location |
|---|---|
| `tests/test_pr1_openclawd_authority_chain.py` | `tests/unit/runtime/` |
| `tests/test_pr1_orchestration_delegation.py` | `tests/unit/runtime/` |
| `tests/test_pr4_config_driven_inventory.py` | `tests/unit/config/` |
| `tests/test_pr2_task_envelope_pipeline.py` | `tests/unit/protocol/` |
| `tests/test_pr4_device_registry_udm_alignment.py` | `tests/unit/routing/` |
| `tests/test_android_bridge_udm_flow.py` | `tests/integration/android_bridge/` |
| `tests/test_heartbeat_ack.py` | `tests/integration/android_bridge/` |
| `tests/test_webrtc_gateway.py` | `tests/integration/` |
| `tests/test_webrtc_signaling_turn.py` | `tests/integration/websocket/` |
