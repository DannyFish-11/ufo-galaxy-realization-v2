"""
core/ha_bridge.py — Home Assistant 桥（Matter 接入·阶段0）
==========================================================

把 Home Assistant 里的智能设备接进本系统的统一设备模型（UDM），并订阅其
实时事件流喂给状态事件总线。两件事：

1) **设备镜像**：启动时拉 HA ``/api/states``，把每个实体注册成
   ``UnifiedDevice``（``device_type=iot``，capabilities 按实体 domain 推导）。
   从此智能设备与手机/手表在同一张设备表里，可被 CommandRouter/面板统一
   看见与调度——这是"智能设备进统一设备模型"的落点。
2) **事件流**：连 HA WebSocket ``/api/websocket``（token 鉴权），订阅
   ``state_changed``；变化实时 upsert 回 UDM 并 emit
   ``StateEventType.DEVICE_UPDATED``（常驻注意力循环/面板据此感知
   "灯开了/门开了"，而不是轮询）。

为什么走 HA：HA 本身就是成熟的 **Matter**/Zigbee/Z-Wave 控制器——配网、
Fabric 凭证、cluster 数据模型那些脏活它都做完了。本桥只与 HA 对话，
Matter 设备扫码进 HA 即自动进入本系统（阶段0 方案；直连
python-matter-server 是阶段2，仅当想甩开 HA 时才值得）。

启用条件：``HOME_ASSISTANT_URL`` + ``HOME_ASSISTANT_TOKEN`` 配置齐，且
``GALAXY_HA_BRIDGE`` != "0"。未配置时完全不启动，对既有行为零影响。
控制通路（下行）已有：nodes/Node_27_SmartHome 的 HA REST；本桥补的是
上行（发现 + 感知）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.HABridge")

# 实体 domain → 能力列表（进 UDM 的 capabilities，供能力路由/面板展示）。
_DOMAIN_CAPABILITIES: Dict[str, List[str]] = {
    "light": ["turn_on", "turn_off", "toggle", "set_brightness"],
    "switch": ["turn_on", "turn_off", "toggle"],
    "climate": ["set_temperature", "turn_on", "turn_off"],
    "cover": ["open_cover", "close_cover"],
    "lock": ["lock", "unlock"],
    "media_player": ["turn_on", "turn_off", "play", "pause", "volume_set"],
    "scene": ["activate"],
    "script": ["run"],
    "vacuum": ["start", "stop", "return_to_base"],
    "fan": ["turn_on", "turn_off", "set_speed"],
    "sensor": ["read_state"],
    "binary_sensor": ["read_state"],
    "camera": ["read_state", "snapshot"],
}
_DEFAULT_CAPABILITIES = ["read_state"]

_UNAVAILABLE_STATES = ("unavailable", "unknown")


def ha_bridge_enabled() -> bool:
    """是否应启动 HA 桥：URL+TOKEN 齐 且未被 GALAXY_HA_BRIDGE=0 显式关闭。"""
    if os.environ.get("GALAXY_HA_BRIDGE", "1").strip() == "0":
        return False
    return bool(
        os.environ.get("HOME_ASSISTANT_URL", "").strip()
        and os.environ.get("HOME_ASSISTANT_TOKEN", "").strip()
    )


class HABridge:
    """Home Assistant → UDM/事件总线 的上行桥。"""

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None) -> None:
        self._url = (url or os.environ.get("HOME_ASSISTANT_URL", "")).rstrip("/")
        self._token = token or os.environ.get("HOME_ASSISTANT_TOKEN", "")
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # 诊断计数（面板/日志可读）
        self.mirrored_count = 0
        self.event_count = 0
        self.last_event_ts = 0.0
        self.connected = False

    # ── 生命周期 ──────────────────────────────────────────────────────

    async def start(self) -> Dict[str, Any]:
        """启动：先做一次全量设备镜像，再拉起事件流后台任务。"""
        mirrored = await self.mirror_devices()
        self._running = True
        self._task = asyncio.create_task(self._event_loop(), name="ha-bridge-events")
        return {"mirrored": mirrored, "event_stream": "started"}

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        self.connected = False

    # ── 1) 设备镜像（HA /api/states → UDM） ───────────────────────────

    async def mirror_devices(self) -> int:
        """拉全量 HA 实体，逐个注册/刷新进 UDM。返回镜像数量;失败返回 0 不抛。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._url}/api/states",
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code != 200:
                logger.warning("HA 桥:/api/states HTTP %s,镜像跳过", resp.status_code)
                return 0
            states = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HA 桥:设备镜像失败(非致命): %s", exc)
            return 0

        count = 0
        for st in states or []:
            if self._mirror_entity(st):
                count += 1
        self.mirrored_count = count
        logger.info("HA 桥:已把 %d 个 HA 实体镜像进统一设备模型", count)
        return count

    def _mirror_entity(self, st: Dict[str, Any]) -> bool:
        """单实体 → UnifiedDevice(device_type=iot)。已存在则走 SSOT upsert。"""
        entity_id = str(st.get("entity_id", "") or "")
        if not entity_id or "." not in entity_id:
            return False
        domain = entity_id.split(".", 1)[0]
        attrs = st.get("attributes") or {}
        value = str(st.get("state", "") or "")
        online = value not in _UNAVAILABLE_STATES
        try:
            from core.unified.device_manager import get_unified_device_manager
            dm = get_unified_device_manager()
            device_id = f"ha_{entity_id}"
            patch = {
                "device_name": attrs.get("friendly_name") or entity_id,
                "status": "online" if online else "offline",
                "capabilities": list(_DOMAIN_CAPABILITIES.get(domain, _DEFAULT_CAPABILITIES)),
                "metadata": {
                    "protocol": "home_assistant",
                    "ha_entity_id": entity_id,
                    "ha_domain": domain,
                    "ha_state": value,
                    "control_via": "Node_27_SmartHome",
                },
                "source": "ha_bridge",
            }
            if dm.get_device(device_id) is None:
                # 注册只立最小身份;register_device_from_dict 会把"多余键"整体
                # 当 metadata(嵌套错位),且其语义为"注册即在线"——完整状态
                # (status/metadata/capabilities)一律走下面的 SSOT upsert。
                dm.register_device_from_dict(device_id, {
                    "device_type": "iot", "device_name": patch["device_name"],
                })
            dm.upsert_device_state(device_id, patch, source="ha_bridge")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("HA 桥:镜像实体 %s 失败: %s", entity_id, exc)
            return False

    # ── 2) 事件流（HA WebSocket state_changed → UDM + 事件总线） ─────

    def _ws_url(self) -> str:
        base = self._url
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + "/api/websocket"
        if base.startswith("http://"):
            return "ws://" + base[len("http://"):] + "/api/websocket"
        return "ws://" + base + "/api/websocket"

    async def _event_loop(self) -> None:
        """常驻:连 HA WS → 鉴权 → 订阅 state_changed → 逐事件回灌。断线指数退避重连。"""
        backoff = 5.0
        while self._running:
            try:
                await self._consume_events()
                backoff = 5.0  # 正常退出(对端关闭)后快速重连
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                self.connected = False
                logger.debug("HA 桥:事件流断开(%s),%.0fs 后重连", exc, backoff)
            if not self._running:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _consume_events(self) -> None:
        import websockets
        async with websockets.connect(self._ws_url(), max_size=4 * 1024 * 1024) as ws:
            # HA WS 协议:auth_required → auth → auth_ok → subscribe_events
            first = json.loads(await ws.recv())
            if first.get("type") == "auth_required":
                await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
                reply = json.loads(await ws.recv())
                if reply.get("type") != "auth_ok":
                    logger.warning("HA 桥:WebSocket 鉴权失败: %s", reply.get("type"))
                    self._running = False  # token 错误,重试无意义
                    return
            await ws.send(json.dumps(
                {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
            ))
            await ws.recv()  # subscribe result
            self.connected = True
            logger.info("HA 桥:事件流已连接(state_changed)")
            async for raw in ws:
                if not self._running:
                    return
                try:
                    self._handle_event(json.loads(raw))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("HA 桥:事件处理失败(忽略该条): %s", exc)

    def _handle_event(self, msg: Dict[str, Any]) -> None:
        if msg.get("type") != "event":
            return
        data = (msg.get("event") or {}).get("data") or {}
        new_state = data.get("new_state") or {}
        entity_id = str(data.get("entity_id", "") or new_state.get("entity_id", "") or "")
        if not entity_id:
            return
        self._mirror_entity(new_state)  # 实时刷新 UDM(状态/在线/能力)
        self.event_count += 1
        self.last_event_ts = time.time()
        old_state = data.get("old_state") or {}
        try:
            from core.state_event_bus import emit, StateEventType
            emit(StateEventType.DEVICE_UPDATED, "ha_bridge", {
                "device_id": f"ha_{entity_id}",
                "ha_entity_id": entity_id,
                "ha_domain": entity_id.split(".", 1)[0],
                "old_state": str(old_state.get("state", "") or ""),
                "new_state": str(new_state.get("state", "") or ""),
                "friendly_name": (new_state.get("attributes") or {}).get("friendly_name", ""),
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("HA 桥:DEVICE_UPDATED 事件发布失败(非致命): %s", exc)

    # ── 诊断 ─────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "connected": self.connected,
            "mirrored_count": self.mirrored_count,
            "event_count": self.event_count,
            "last_event_ts": self.last_event_ts,
        }


# ── 模块级单例 ─────────────────────────────────────────────────────────

_bridge_instance: Optional[HABridge] = None


def get_ha_bridge() -> HABridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = HABridge()
    return _bridge_instance
