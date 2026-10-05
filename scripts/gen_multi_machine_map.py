#!/usr/bin/env python3
"""重新生成 ``docs/MULTI_MACHINE_MODE.md`` 里的配置键表（两个标记之间的部分）。

    python scripts/gen_multi_machine_map.py --write   # 把表写回文档
    python scripts/gen_multi_machine_map.py           # 只打印到屏幕

文档里的叙述、模块清单、接口、「查出来的不一致」是 2026-10-05 对着代码查的**快照**，不会自动更新；
只有键表由实时登记表（``CONFIG_SCHEMA`` / ``panel_switch_policy`` / ``config_bundles`` / ``config_restart``）生成。
哪个键归哪一块是这里的 ``PARTS``（盘点时的判断，依据写在文档里）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DOC = REPO / "docs" / "MULTI_MACHINE_MODE.md"
START, END = "<!-- tables:start -->", "<!-- tables:end -->"

PARTS = {
    "第一层 跨设备（通路：能发现、能认识、能传话）": {
        "总闸与运行模式": "GALAXY_CROSS_DEVICE_ENABLED GALAXY_SYSTEM_MODE",
        "发现与接入": (
            "GALAXY_LAN_DISCOVERY GALAXY_LAN_DISCOVERY_TYPES GALAXY_MDNS GALAXY_ONBOARDING_ENABLED GALAXY_ONBOARDING_AUTO "
            "GALAXY_ONBOARDING_SSDP GALAXY_ONBOARDING_BLUETOOTH GALAXY_ONBOARDING_CAN GALAXY_ONBOARDING_SERIAL "
            "GALAXY_ONBOARDING_CAN_LISTEN_S GALAXY_ONBOARDING_SCAN_INTERVAL_S GALAXY_ONBOARDING_STATE_DIR "
            "GALAXY_MESH_DISCOVERY_TIMEOUT GALAXY_MESH_NODE_ID GALAXY_MESH_PORT GALAXY_DEVICE_NAME GALAXY_DEVICE_TYPE"
        ),
        "信任与准入": (
            "GALAXY_REQUIRE_DEVICE_APPROVAL GALAXY_PEER_DEFAULT_TRUST GALAXY_PEER_TRUST_PATH GALAXY_MESH_SECRET "
            "GALAXY_DEVICE_TOKEN_STORE GALAXY_DEVICE_TOKEN_RETENTION_DAYS GALAXY_DEVICE_TOKEN_MAX_RECORDS"
        ),
        "传输通道（不含 NATS）": (
            "GALAXY_TS_FUNNEL GALAXY_TS_ADVERTISE_RELAY GALAXY_TAILSCALE_CHECK_INTERVAL GALAXY_TAILSCALE_ENABLED "
            "GALAXY_TAILSCALE_HOST GALAXY_TAILSCALE_TAG GALAXY_HEADSCALE_URL GALAXY_HEADSCALE_API_KEY GALAXY_HEADSCALE_USER "
            "GALAXY_HEADSCALE_AUTOJOIN GALAXY_TURN_URLS GALAXY_TURN_USERNAME GALAXY_TURN_CREDENTIAL GALAXY_SIGNALING_TIMEOUT_S "
            "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL GALAXY_ENABLE_WEBRTC GALAXY_WEBRTC_TASK_READY_TIMEOUT_S "
            "GALAXY_USE_GATEWAY_FOR_WEBRTC GALAXY_TRANSPORT_ADAPTIVE GALAXY_TRANSPORT_BULK_BYTES GALAXY_TRANSPORT_PRIORITY "
            "GALAXY_ANDROID_WS_ENABLED ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS ANDROID_DEVICE_STATE_STORE_PATH"
        ),
        "别的设备 / 实例 / 家居接入": (
            "GALAXY_REMOTE_DESKTOP GALAXY_VNC_PORT GALAXY_VNC_CMD FEDERATION_ENABLED FEDERATION_PEERS FEDERATION_LOCAL_HOST "
            "FEDERATION_HEARTBEAT_INTERVAL FEDERATION_INSTANCE_ID FEDERATION_MIN_HEARTBEAT_INTERVAL FEDERATION_OFFLINE_THRESHOLD "
            "GALAXY_HA_BRIDGE HOME_ASSISTANT_URL HOME_ASSISTANT_TOKEN"
        ),
    },
    "第二层 多设备并行（设备清单、编队、并行）": {
        "并行与健康": (
            "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT GALAXY_NODE_HEALTH_RETRIES GALAXY_SLO_HEARTBEAT_WINDOW "
            "GALAXY_ENABLE_LEGACY_MULTIDEVICE"
        ),
    },
    "共用底座 NATS 消息总线（第一层的设备 / 在场 / 能力平面，第四层的任务 / worker 平面都走它）": {
        "总线": "GALAXY_NATS_ENABLED GALAXY_NATS_URL GALAXY_FABRIC_STRICT",
    },
    "第三层 任务派发与分配": {
        "派发": (
            "GALAXY_DISPATCH_IDEMPOTENCY GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE GALAXY_NATS_EXECUTOR_FALLBACK "
            "GALAXY_NATS_EXECUTOR_TIMEOUT GALAXY_DURABLE_EXEC"
        ),
    },
    "第四层 NATS Agent（主脑与 worker）": {
        "主脑与 worker": (
            "GALAXY_MASTER_BRAIN_ENABLED GALAXY_MASTER_BRAIN_STATE_PATH GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S "
            "GALAXY_WORKER_ID GALAXY_WORKER_VERSION GALAXY_HEARTBEAT_INTERVAL"
        ),
    },
}

_DISP = {"panel": "留在面板", "builtin": "内置", "ops": "运维", "member": "并进按钮"}


def tables() -> str:
    logging.disable(logging.CRITICAL)
    from core.routes.config_bundles import CONFIG_BUNDLES, member_keys, owned_keys
    from core.routes.config_restart import RESTART_REQUIRED
    from core.routes.config_schema_registry import CONFIG_SCHEMA
    from core.routes.panel_switch_policy import SWITCH_POLICY

    bundle_of = {k: b["name"] for b in CONFIG_BUNDLES for k in owned_keys(b, CONFIG_SCHEMA.keys())}
    member_of = {k: b["name"] for b in CONFIG_BUNDLES for k in member_keys(b)}
    out, total, unreg = [], 0, 0
    for part, groups in PARTS.items():
        out += ["", f"### {part}", ""]
        for group, keys in groups.items():
            out += [f"**{group}**", "", "| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |", "|---|---|---|---|---|---|"]
            for key in keys.split():
                total += 1
                meta = CONFIG_SCHEMA.get(key)
                if meta is None:
                    unreg += 1
                    out.append(f"| `{key}` | — | **未登记**（只能改 .env） | — | — | — |")
                    continue
                pol = SWITCH_POLICY.get(key)
                disp = _DISP.get(pol.disposition, "") if pol else ""
                default = str(meta["default"])
                default = "开" if default == "true" else "关" if default == "false" else (default[:14] or "空")
                bundle = f"{member_of[key]}（成员）" if key in member_of else bundle_of.get(key, "—")
                out.append(
                    f"| `{key}` | {default} | 是 | {disp or '全部设置'} | {bundle} | {'重启' if key in RESTART_REQUIRED else ''} |"
                )
            out.append("")
    out.append(f"共 {total} 个键，其中 **{unreg}** 个未登记。")
    return "\n".join(out).strip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    text = tables()
    if not args.write:
        print(text)
        return 0
    doc = DOC.read_text(encoding="utf-8")
    a, b = doc.index(START) + len(START), doc.index(END)
    DOC.write_text(doc[:a] + "\n" + text + doc[b:], encoding="utf-8")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
