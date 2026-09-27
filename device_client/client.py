"""device_client/client.py — 连接层:连上主脑、保持连接、把动作交给执行插件、把结果回给主脑。

与系统无关。在本机怎么动手完全交给 ``executor``(``device_client/executors``)。

协议(AIP v3,走规范设备入口 ``/ws/device/{device_id}``):
* 连上先发 ``device_register``(带配对令牌)与 ``capability_report``;
* ``command``(``command_id`` + ``command`` + ``params``)→ 执行 → ``command_result``(带回 ``command_id``);
* ``task_assign`` / ``task_execute`` → 执行 → ``task_result``(带回 ``task_id``);
* ``command=agent_execute`` → 整段任务交给插件(大多数插件如实说不接)。

执行插件在这台机器上不可用(比如 Linux 没装 xdotool)时照样连上 —— 主脑能看到它在线、
看到原因(``executor_status``),但动作清单为空,智能体不会去调注定失败的动作。
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import time
import uuid
from typing import Any, Dict, Optional

from device_client import pairing as _dp
from device_client.executors import DesktopExecutor

logger = logging.getLogger("galaxy-device-client")


class DeviceClient:
    PROTOCOL_VERSION = "3.0"
    HEARTBEAT_INTERVAL = 30  # 秒

    def __init__(
        self,
        executor: DesktopExecutor,
        host: str = "127.0.0.1",
        port: int = 8000,
        device_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        state_file: Optional[str] = None,
    ):
        self.executor = executor
        self.host = host
        self.port = port
        self._state_file = state_file
        #: 配对凭据(令牌、连接地址、设备 id)—— 见 device_client/pairing.py
        self.state: Dict[str, Any] = state if state is not None else _dp.load_state(state_file)
        if device_id:
            self.state["device_id"] = device_id
        self.device_id = _dp.stable_device_id(self.state)
        self.device_type = str(self.state.get("device_type") or "") or _dp.detect_device_type(executor.platform)
        self._ws = None
        self._running = False
        self._on_event_stream = None
        #: 注册被入口拒掉的原因(令牌无效等)。设了就不再重连 —— 换多少次地址都一样被拒。
        self.fatal: Optional[str] = None

    def set_event_stream_callback(self, callback):
        self._on_event_stream = callback

    # ── 动作清单 ──────────────────────────────────────────────────────────────

    def supported_actions(self) -> list:
        ok, _ = self.executor.available()
        return self.executor.supported_actions() if ok else []

    # ── 消息构建 ──────────────────────────────────────────────────────────────

    def _base_message(self, msg_type: str) -> Dict[str, Any]:
        return {
            "type": msg_type,
            "version": self.PROTOCOL_VERSION,
            "device_id": self.device_id,
            "timestamp": time.time(),
            "message_id": uuid.uuid4().hex,
        }

    def _device_register_msg(self) -> Dict[str, Any]:
        msg = self._base_message("device_register")
        actions = self.supported_actions()
        msg.update(
            {
                "device_type": self.device_type,
                "platform": self.executor.platform,
                "name": self.state.get("name") or socket.gethostname(),
                "model": f"{platform.system()} computer",
                "os_version": _dp.os_label(),
                # capabilities 在协议里是整数位图;动作名单走 supported_actions。
                "supported_actions": actions,
                "executor_status": self.executor.describe(),
            }
        )
        token = self.state.get("token")
        if token:
            msg["token"] = token
        return msg

    def _capability_report_msg(self) -> Dict[str, Any]:
        msg = self._base_message("capability_report")
        msg.update(
            {
                "platform": self.executor.platform,
                "device_type": self.device_type,
                "supported_actions": self.supported_actions(),
            }
        )
        return msg

    def _heartbeat_msg(self) -> Dict[str, Any]:
        return self._base_message("heartbeat")

    def _task_result_msg(self, task_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("task_result")
        msg.update({"task_id": task_id, "status": "completed" if result.get("success") else "failed", "result": result})
        return msg

    def _command_result_msg(self, command_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("command_result")
        msg.update({"command_id": command_id, "payload": result})
        return msg

    def _agent_execute_result_msg(
        self, command_id: str, agent_payload: Dict[str, Any], result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """``agent_execute_result``,保留全部关联 id(PR155/PR158)。"""
        msg = self._base_message("agent_execute_result")
        msg.update(
            {
                "command_id": command_id,
                "agent_id": result.get("agent_id") or agent_payload.get("agent_id", ""),
                "task_id": result.get("task_id") or agent_payload.get("task_id", ""),
                "trace_id": result.get("trace_id") or agent_payload.get("trace_id", ""),
                "session_id": result.get("session_id") or agent_payload.get("session_id", ""),
                "status": "completed" if result.get("success", True) else "failed",
                "result": result,
            }
        )
        manifest_id = result.get("manifest_id") or agent_payload.get("context", {}).get("manifest_id", "")
        if manifest_id:
            msg["manifest_id"] = manifest_id
        return msg

    # ── 执行(在线程里跑,不堵住收发) ────────────────────────────────────────

    async def _run_action(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.get_running_loop().run_in_executor(None, self.executor.execute, action, params)

    async def _run_agent_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.get_running_loop().run_in_executor(None, self.executor.execute_agent_task, payload)

    # ── 消息处理 ──────────────────────────────────────────────────────────────

    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type", "")

        if msg_type == "event_stream":
            logger.info(
                "[EventStream] %s from %s: %s",
                data.get("event_type", ""),
                data.get("source", ""),
                json.dumps(data.get("data", {}), ensure_ascii=False)[:200],
            )
            if self._on_event_stream:
                self._on_event_stream(data)
            return

        if msg_type == "device_register_ack" and data.get("success") is False:
            code = data.get("error_code") or ""
            why = data.get("message") or code or "注册被拒"
            if code in ("INGRESS_AUTHENTICATION_FAILED", "INGRESS_IDENTITY_MISMATCH"):
                self.fatal = (
                    f"主脑拒绝了这台电脑:{why}。需要(重新)配对:让主脑给一个配对码,"
                    "然后运行 python -m device_client --pair <配对码>"
                )
                logger.error(self.fatal)
                self._running = False
                if self._ws is not None:
                    await self._ws.close()
            else:
                logger.error("注册失败:%s", why)
            return

        if msg_type in ("device_register_ack", "heartbeat_ack", "capability_report_ack"):
            logger.debug("收到 ACK: %s", msg_type)
            return

        if msg_type in ("task_assign", "task_execute"):
            task_id = data.get("task_id") or data.get("message_id", "")
            result = await self._run_action(data.get("task_type", ""), data.get("payload", {}) or {})
            await self._send(self._task_result_msg(task_id, result))
            return

        if msg_type == "command":
            cmd_id = data.get("command_id", "")
            command = data.get("command", "")
            params = data.get("params", {})
            if command == "agent_execute":
                agent_payload = params if isinstance(params, dict) else {}
                for field in ("agent_id", "task_id", "trace_id", "session_id"):
                    if field not in agent_payload and data.get(field):
                        agent_payload[field] = data[field]
                agent_payload.setdefault("task_id", cmd_id)
                result = await self._run_agent_task(agent_payload)
                await self._send(self._agent_execute_result_msg(cmd_id, agent_payload, result))
                return
            logger.info("收到命令: %s cmd=%s", cmd_id, command)
            result = await self._run_action(command, params if isinstance(params, dict) else {})
            await self._send(self._command_result_msg(cmd_id, result))
            return

        logger.debug("未处理的消息类型: %s", msg_type)

    # ── 网络层 ────────────────────────────────────────────────────────────────

    async def _send(self, message: Dict[str, Any]):
        if self._ws:
            try:
                await self._ws.send(json.dumps(message, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                logger.error("发送消息失败: %s", e)

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            if self._running:
                await self._send(self._heartbeat_msg())
                self._renew_token()

    def _renew_token(self) -> None:
        """令牌快过期就换新并存盘;下次重连时用新的。"""
        try:
            if _dp.renew_if_due(self.state):
                _dp.save_state(self.state, self._state_file)
                logger.info("配对令牌已续期")
        except _dp.PairingError as exc:
            logger.error("%s —— %s", exc, exc.how_to_fix)
        except Exception as exc:  # noqa: BLE001 — 续期失败不打断连接,下次心跳再试
            logger.warning("令牌续期失败,稍后再试: %s", exc)

    async def run(self):
        """连上主脑并保持运行;断了按可达性顺序换地址重连。"""
        try:
            import websockets
        except ImportError:
            logger.error("缺少 websockets 库,请运行: pip install websockets")
            return

        ok, why = self.executor.available()
        if not ok:
            logger.warning("执行插件 %s 在这台机器上不可用:%s(照样连上,但不接动作)", self.executor.name, why)
        self._running = True
        self._renew_token()
        attempt = 0
        while self._running:
            urls = _dp.connect_urls(self.state, self.host, self.port, self.device_id)
            uri = urls[attempt % len(urls)]
            attempt += 1
            logger.info("连接主脑: %s", uri)
            try:
                async with websockets.connect(uri, open_timeout=10) as ws:
                    self._ws = ws
                    attempt -= 1  # 这条通了,断线后先重试它
                    logger.info("已连接,device_id=%s", self.device_id)
                    await self._send(self._device_register_msg())
                    await asyncio.sleep(0.5)
                    await self._send(self._capability_report_msg())
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    try:
                        async for raw in ws:
                            try:
                                await self._handle_message(json.loads(raw))
                            except json.JSONDecodeError:
                                logger.warning("无效 JSON: %s", raw[:100])
                    finally:
                        heartbeat_task.cancel()
                        self._ws = None
            except Exception as e:  # noqa: BLE001
                if not self._running:
                    break
                logger.warning("连接断开: %s,5 秒后重连…", e)
                await asyncio.sleep(5)

    def stop(self):
        self._running = False
