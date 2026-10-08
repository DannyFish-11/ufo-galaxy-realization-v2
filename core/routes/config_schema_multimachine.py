"""多机模式那一批配置键的登记 —— 代码里早就在读、``POST /api/config`` 却不认的那些。

``docs/MULTI_MACHINE_MODE.md`` 说的四层（跨设备 · 多设备并行 · 任务派发与分配 · NATS Agent）底下，有
二十来个环境变量一直是**只读不登记**：联邦、TURN / STUN、Tailscale、WebRTC、传输优先级、mesh、worker。
后果不是「面板上少一行」：没登记 = ``POST /api/config`` 按未知键整批 400、``.env`` 的落盘与密钥分流够不着它
（TURN 的凭据就这样没有被当成密钥）、检查「登记默认与代码默认是否一致」的守卫也看不见它们。

这里每个键的 ``default`` 都**抄代码里实际用的默认**（读取处见各条注释），不是想当然的值。留空的是
「没写就由代码按情况定」的那类 —— 登记成非空，「保存设置」就会替人把它钉死。

哪些列给面板、哪些只登记不列：用户真要为「连不上」去填的（TURN 账号、STUN 地址、Tailscale 主机/标签、
传输优先级）列；内部调参（心跳阈值、mesh 端口、并发上限、worker 标识……）与逃生口式的布尔开关一律不列
（见 ``config.PANEL_HIDDEN_KEYS`` 与 ``panel_switch_policy``）—— 登记了、能存能读，只是不占面板的行。
"""

from __future__ import annotations

from typing import Any, Dict

MULTI_MACHINE_SCHEMA: Dict[str, Dict[str, Any]] = {
    # ── 联邦（core/galaxy_federation.py）──
    "FEDERATION_INSTANCE_ID": {
        "default": "",  # 留空 = 每次启动随机生成 12 位
        "type": "string",
        "category": "devices",
        "description": "联邦里这台实例的标识（留空=每次启动随机生成）",
    },
    "FEDERATION_MIN_HEARTBEAT_INTERVAL": {
        "default": "5",
        "type": "number",
        "category": "devices",
        "description": "联邦心跳的最小间隔（秒 · 默认 5）",
    },
    "FEDERATION_OFFLINE_THRESHOLD": {
        "default": "3",
        "type": "number",
        "category": "devices",
        "description": "联邦里连续几次没收到心跳就判对方离线（默认 3）",
    },
    # ── NAT 穿透：TURN / STUN（galaxy_gateway/api/config.py、webrtc_proxy.py）──
    "GALAXY_STUN_URLS": {
        "default": "",  # 留空 = 内置的公共 STUN
        "type": "string",
        "category": "network",
        "description": "STUN 服务器地址，逗号隔开（留空=用内置的公共 STUN）",
    },
    "GALAXY_TURN_USERNAME": {
        "default": "",
        "type": "string",
        "category": "network",
        "description": "TURN 中继的用户名（配了 GALAXY_TURN_URLS 才用得上）",
    },
    "GALAXY_TURN_CREDENTIAL": {
        "default": "",
        "type": "password",
        "category": "network",
        "description": "TURN 中继的凭据（密钥 · 存在本机密钥库，不写进 .env）",
    },
    # ── Tailscale（core/system_mode.py、smart_transport_router.py、webrtc_proxy.py）──
    "GALAXY_TAILSCALE_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "network",
        "description": "走 Tailscale 通道（默认关；跨设备模式下传输顺序里本来就把它排第一）",
    },
    "GALAXY_TAILSCALE_HOST": {
        "default": "",
        "type": "string",
        "category": "network",
        "description": "本机在 Tailscale 里的主机名或域名（留空=自动探测）",
    },
    "GALAXY_TAILSCALE_TAG": {
        "default": "",
        "type": "string",
        "category": "network",
        "description": "Tailscale 的 ACL 标签（留空=不带标签）",
    },
    "GALAXY_TRANSPORT_PRIORITY": {
        "default": "",  # 留空 = 按运行模式:本地 lan,internet / 跨设备 tailscale,lan,internet
        "type": "string",
        "category": "network",
        "description": "传输通道的先后顺序，逗号隔开（留空=按运行模式：本地 lan→internet；跨设备 tailscale→lan→internet）",
    },
    # ── WebRTC 与可选传输通道（galaxy_gateway/smart_transport_router.py、webrtc_proxy.py、api/config.py）──
    "GALAXY_ENABLE_WEBRTC": {
        "default": "false",
        "type": "boolean",
        "category": "network",
        "description": "把 WebRTC 直连当作可选传输通道（默认关）",
    },
    "GALAXY_ENABLE_SCRCPY": {
        "default": "false",
        "type": "boolean",
        "category": "network",
        "description": "把 scrcpy 投屏当作可选传输通道（默认关）",
    },
    "GALAXY_ENABLE_MQTT": {
        "default": "false",
        "type": "boolean",
        "category": "network",
        "description": "把 MQTT 当作可选传输通道（默认关）",
    },
    "GALAXY_USE_GATEWAY_FOR_WEBRTC": {
        "default": "true",
        "type": "boolean",
        "category": "network",
        "description": "WebRTC 信令走网关（默认开；关掉则客户端自己找信令地址）",
    },
    "GALAXY_WEBRTC_TASK_READY_TIMEOUT_S": {
        "default": "15",
        "type": "number",
        "category": "network",
        "description": "WebRTC 任务通道等「对端就绪」的秒数（默认 15）",
    },
    "GALAXY_HOLE_PUNCH_TIMEOUT_S": {
        "default": "10",
        "type": "number",
        "category": "network",
        "description": "WebRTC 打洞等待的秒数（默认 10）",
    },
    # ── mesh 与并行派发（galaxy_gateway/bootstrap/lifecycle.py、device_router.py）──
    "GALAXY_MESH_NODE_ID": {
        "default": "gateway",
        "type": "string",
        "category": "devices",
        "description": "网关在 mesh 里的节点标识（默认 gateway）",
    },
    "GALAXY_MESH_PORT": {
        "default": "19422",
        "type": "number",
        "category": "devices",
        "description": "mesh 协调的本地端口（默认 19422）",
    },
    "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT": {
        "default": "8",
        "type": "number",
        "category": "devices",
        "description": "多设备并行派发时同时在飞的设备数上限（默认 8）",
    },
    # ── worker（core/worker_runtime.py、nats_heartbeat.py）──
    "GALAXY_WORKER_ID": {
        "default": "",  # 留空 = worker-<随机 8 位>
        "type": "string",
        "category": "devices",
        "description": "NATS worker 的标识（留空=启动时随机生成）",
    },
    "GALAXY_WORKER_VERSION": {
        "default": "1.0.0",
        "type": "string",
        "category": "devices",
        "description": "NATS worker 心跳里报的版本号（默认 1.0.0）",
    },
    # ── 旧版多设备兼容层（enhancements/multidevice）──
    "GALAXY_ENABLE_LEGACY_MULTIDEVICE": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "加载旧版多设备兼容层（默认关；规范实现在 galaxy_gateway，不需要它）",
    },
}
