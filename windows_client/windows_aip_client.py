"""
Windows AIP v3.0 客户端
=======================

将 Windows 主机作为设备注册到 Galaxy 服务端，
使其与 Android 端一致可被 ReAct Agent 调度。

功能:
  1. 通过 WebSocket 连接服务端 /ws/device/{device_id}
  2. 发送 device_register（AIP v3.0 握手）
  3. 发送 capability_report（supported_actions 列表）
  4. 维护心跳保活
  5. 接收并执行服务端下发的任务命令（统一通过 WindowsExecutionArbiter）

执行管道
--------
所有入站命令经由统一执行仲裁器路由::

    AIP ingress (this file)
        ↓
    WindowsExecutionArbiter.route_command()      ← 唯一执行入口
        ↓  fallback chain: system_api → UIA → GUI → VLM
    WindowsAutonomyManager  (UIA adapter)

旧版本的多路命令分支（bespoke action_types 字典）已被替换。
遗留路径（windows_mcp_server.py、ui_sidebar.py、client.py、
desktop_automation.py）已被弃用，不再是主执行路径。

启动方式:
    第一次(主脑给了配对码):
        python windows_client/windows_aip_client.py --pair 123456 --gateway http://主脑地址:端口
    之后:
        python windows_client/windows_aip_client.py
    配对、凭据、令牌续期与进自建内网见 windows_client/device_pairing.py。

Author: Galaxy Team
Version: 2.0.0
"""

import asyncio
import json
import logging
import sys
import os
import socket
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("windows-aip-client")


# ============================================================================
# Windows 设备支持的 actions（与 Arbiter fallback chain 对齐）
# ============================================================================

WINDOWS_SUPPORTED_ACTIONS = [
    "get_screen_state",
    "click",
    "type",
    "press_key",
    "press_keys",
    "scroll",
    "find_and_click",
    "find_and_type",
    "screenshot",
]


# ============================================================================
# 懒加载 WindowsExecutionArbiter（统一执行仲裁器）
# ============================================================================

_arbiter = None


def _get_arbiter():
    """Return the singleton :class:`WindowsExecutionArbiter`.

    This is the **only** execution entry point for the AIP client.
    All task_type / command routing goes through ``arbiter.route_command()``.
    """
    global _arbiter
    if _arbiter is None:
        try:
            _client_dir = os.path.dirname(os.path.abspath(__file__))
            _root_dir = os.path.dirname(_client_dir)
            for p in [_client_dir, _root_dir]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from core.windows_execution_arbiter import get_windows_arbiter
            _arbiter = get_windows_arbiter()
            logger.info("WindowsExecutionArbiter 已就绪")
        except Exception as e:
            logger.warning(f"WindowsExecutionArbiter 不可用: {e}")
    return _arbiter


# ============================================================================
# 命令执行 — 统一通过仲裁器路由
# ============================================================================

def _execute_command(task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Route a device command through :class:`WindowsExecutionArbiter`.

    This replaces the previous bespoke per-action branching logic.
    The arbiter applies its strict fallback chain:
    system_api → UIA (via WindowsAutonomyManager) → GUI → VLM.
    """
    arbiter = _get_arbiter()
    if arbiter is None:
        return {"success": False, "error": "execution arbiter unavailable"}

    try:
        result = arbiter.route_command(
            action=task_type,
            params=payload,
            device_id="local",
        )
    except Exception as exc:  # noqa: BLE001
        # 设备端契约(Acceptance Gate A):执行器崩溃绝不外抛——回错误信封,
        # 关联 ID 由上层补齐,消息处理循环保持存活。否则一次执行器故障就会
        # 炸断整个 WS 消息处理。
        logger.error("[%s] 执行仲裁器异常(已兜住): %s", task_type, exc)
        return {"success": False, "error": str(exc)}
    # Normalise to the flat dict shape callers expect
    if isinstance(result, dict) and "result" in result:
        merged = {"success": result.get("success", False)}
        merged.update(result.get("result", {}))
        return merged
    return result


def _execute_agent_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a remote ``agent_execute`` payload on the local Windows device.

    Routes through :class:`WindowsExecutionArbiter` as a generic
    ``agent_task`` action, preserving all correlation IDs for end-to-end
    tracing (PR155/PR158).

    Supports the extended **SwarmAgentManifest** context keys introduced in
    PR158: ``system_prompt``, ``tool_schemas``, ``memory_snapshot``, and
    ``manifest_id`` are extracted from the ``context`` sub-dict and forwarded
    to the arbiter when present.

    Parameters
    ----------
    payload:
        Dict from the ``agent_execute`` message body; expected keys::

            agent_id, agent_template, task, session_id, trace_id, task_id, context

        The ``context`` dict may additionally carry::

            system_prompt, tool_schemas, memory_snapshot, manifest_id, member_name
    """
    agent_id = payload.get("agent_id", "")
    task_id = payload.get("task_id", "")
    trace_id = payload.get("trace_id", "")
    session_id = payload.get("session_id", "")
    task_text = payload.get("task", "")
    agent_template = payload.get("agent_template", "")
    context = payload.get("context", {})

    # PR158: manifest_id is carried inside context and forwarded via context dict
    manifest_id = context.get("manifest_id", "")

    logger.info(
        "[agent_execute] agent_id=%s task_id=%s trace_id=%s template=%s "
        "manifest_id=%s task=%.80s",
        agent_id, task_id, trace_id, agent_template, manifest_id, task_text,
    )

    result = _execute_command(
        "agent_task",
        {
            "task": task_text,
            "agent_template": agent_template,
            "context": context,
        },
    )

    # Ensure result is always a plain dict before setting correlation IDs
    if not isinstance(result, dict):
        result = {"success": True, "output": str(result)}

    # Ensure correlation IDs are preserved in the returned result
    result["agent_id"] = agent_id
    result["task_id"] = task_id
    result["trace_id"] = trace_id
    result["session_id"] = session_id
    if manifest_id:
        result["manifest_id"] = manifest_id
    return result


# ============================================================================
# AIP 客户端
# ============================================================================

class WindowsAIPClient:
    """Windows AIP v3.0 客户端"""

    PROTOCOL_VERSION = "3.0"
    HEARTBEAT_INTERVAL = 30  # 秒

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        device_id: str = None,
        state: Optional[Dict[str, Any]] = None,
        state_file: Optional[str] = None,
    ):
        from windows_client import device_pairing as _dp

        self.host = host
        self.port = port
        self._state_file = state_file
        #: 配对凭据(令牌、连接地址、设备 id)—— 见 windows_client/device_pairing.py
        self.state: Dict[str, Any] = state if state is not None else _dp.load_state(state_file)
        if device_id:
            self.state["device_id"] = device_id
        self.device_id = _dp.stable_device_id(self.state)
        self.device_type = str(self.state.get("device_type") or "") or _dp.detect_device_type()
        self._ws = None
        self._running = False
        self._on_event_stream = None
        #: 注册被入口拒掉的原因(令牌无效等)。设了就不再重连 —— 换多少次地址都一样被拒。
        self.fatal: Optional[str] = None

    def set_event_stream_callback(self, callback):
        """Set callback for event_stream messages from the EventBus."""
        self._on_event_stream = callback

    # ------------------------------------------------------------------
    # 消息构建
    # ------------------------------------------------------------------

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
        msg.update({
            "device_type": self.device_type,
            "platform": "windows",
            "name": self.state.get("name") or socket.gethostname(),
            "model": "Windows PC",
            "os_version": _get_os_version(),
            # capabilities 在协议里是整数位图;动作名单走 supported_actions。
            # 此前这里塞的是名字列表,入口 int(list) 直接抛错,注册一次都没成功过。
            "supported_actions": WINDOWS_SUPPORTED_ACTIONS,
        })
        token = self.state.get("token")
        if token:
            msg["token"] = token
        return msg

    def _capability_report_msg(self) -> Dict[str, Any]:
        msg = self._base_message("capability_report")
        msg.update({
            "platform": "windows",
            "device_type": self.device_type,
            "supported_actions": WINDOWS_SUPPORTED_ACTIONS,
        })
        return msg

    def _heartbeat_msg(self) -> Dict[str, Any]:
        return self._base_message("heartbeat")

    def _task_result_msg(self, task_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("task_result")
        msg.update({
            "task_id": task_id,
            "status": "completed" if result.get("success") else "failed",
            "result": result,
        })
        return msg

    def _command_result_msg(self, command_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("command_result")
        msg.update({
            "command_id": command_id,
            "payload": result,
        })
        return msg

    def _agent_execute_result_msg(
        self,
        command_id: str,
        agent_payload: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build an ``agent_execute_result`` message preserving all correlation IDs (PR155/PR158)."""
        msg = self._base_message("agent_execute_result")
        msg.update({
            "command_id": command_id,
            "agent_id": result.get("agent_id") or agent_payload.get("agent_id", ""),
            "task_id": result.get("task_id") or agent_payload.get("task_id", ""),
            "trace_id": result.get("trace_id") or agent_payload.get("trace_id", ""),
            "session_id": result.get("session_id") or agent_payload.get("session_id", ""),
            "status": "completed" if result.get("success", True) else "failed",
            "result": result,
        })
        # PR158: propagate manifest_id when present
        manifest_id = result.get("manifest_id") or agent_payload.get("context", {}).get("manifest_id", "")
        if manifest_id:
            msg["manifest_id"] = manifest_id
        return msg

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type", "")

        if msg_type == "event_stream":
            # Log events from the unified EventBus
            event_type = data.get("event_type", "")
            source = data.get("source", "")
            event_data = data.get("data", {})
            logger.info(f"[EventStream] {event_type} from {source}: {json.dumps(event_data, ensure_ascii=False)[:200]}")
            # Invoke callback if set
            if self._on_event_stream:
                self._on_event_stream(data)
            return

        if msg_type == "device_register_ack" and data.get("success") is False:
            code = data.get("error_code") or ""
            why = data.get("message") or code or "注册被拒"
            if code in ("INGRESS_AUTHENTICATION_FAILED", "INGRESS_IDENTITY_MISMATCH"):
                self.fatal = (
                    f"主脑拒绝了这台电脑:{why}。需要(重新)配对:让主脑给一个配对码,"
                    "然后运行 python windows_client/windows_aip_client.py --pair <配对码> --gateway <主脑地址>"
                )
                logger.error(self.fatal)
                self._running = False
                if self._ws is not None:
                    await self._ws.close()
            else:
                logger.error("注册失败:%s", why)
            return

        if msg_type in ("device_register_ack", "heartbeat_ack", "capability_report_ack"):
            logger.debug(f"收到 ACK: {msg_type}")
            return

        if msg_type in ("task_assign", "task_execute"):
            task_id = data.get("task_id") or data.get("message_id", "")
            task_type = data.get("task_type", "")
            payload = data.get("payload", {})
            logger.info(f"收到任务: {task_id} type={task_type}")
            result = await asyncio.get_running_loop().run_in_executor(
                None, _execute_command, task_type, payload
            )
            await self._send(self._task_result_msg(task_id, result))
            return

        if msg_type == "command":
            cmd_id = data.get("command_id", "")
            command = data.get("command", "")
            params = data.get("params", {})
            # PR155: agent_execute dispatched via route_command arrives as
            # a "command" envelope with command="agent_execute"
            if command == "agent_execute":
                agent_payload = params if isinstance(params, dict) else {}
                # Merge top-level correlation fields from the envelope
                for field in ("agent_id", "task_id", "trace_id", "session_id"):
                    if field not in agent_payload and data.get(field):
                        agent_payload[field] = data[field]
                agent_payload.setdefault("task_id", cmd_id)
                logger.info(
                    f"收到 agent_execute: agent_id={agent_payload.get('agent_id')} "
                    f"task_id={agent_payload.get('task_id')} "
                    f"trace_id={agent_payload.get('trace_id')}"
                )
                result = await asyncio.get_running_loop().run_in_executor(
                    None, _execute_agent_task, agent_payload
                )
                await self._send(self._agent_execute_result_msg(cmd_id, agent_payload, result))
                return
            logger.info(f"收到命令: {cmd_id} cmd={command}")
            result = await asyncio.get_running_loop().run_in_executor(
                None, _execute_command, command, params
            )
            await self._send(self._command_result_msg(cmd_id, result))
            return

        logger.debug(f"未处理的消息类型: {msg_type}")

    # ------------------------------------------------------------------
    # 网络层
    # ------------------------------------------------------------------

    async def _send(self, message: Dict[str, Any]):
        if self._ws:
            try:
                await self._ws.send(json.dumps(message, ensure_ascii=False))
            except Exception as e:
                logger.error(f"发送消息失败: {e}")

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            if self._running:
                await self._send(self._heartbeat_msg())
                self._renew_token()

    def _renew_token(self) -> None:
        """令牌快过期就换新并存盘;下次重连时用新的。"""
        from windows_client import device_pairing as _dp

        try:
            if _dp.renew_if_due(self.state):
                _dp.save_state(self.state, self._state_file)
                logger.info("配对令牌已续期")
        except _dp.PairingError as exc:
            logger.error("%s —— %s", exc, exc.how_to_fix)
        except Exception as exc:  # noqa: BLE001 — 续期失败不打断连接,下次心跳再试
            logger.warning("令牌续期失败,稍后再试: %s", exc)

    async def run(self):
        """连接服务端并保持运行"""
        try:
            import websockets
        except ImportError:
            logger.error("缺少 websockets 库，请运行: pip install websockets")
            return

        from windows_client import device_pairing as _dp

        self._running = True
        self._renew_token()
        attempt = 0
        while self._running:
            urls = _dp.connect_urls(self.state, self.host, self.port, self.device_id)
            uri = urls[attempt % len(urls)]
            attempt += 1
            logger.info(f"连接主脑: {uri}")
            try:
                async with websockets.connect(uri, open_timeout=10) as ws:
                    self._ws = ws
                    attempt -= 1  # 这条通了,断线后先重试它
                    logger.info(f"WebSocket 已连接，device_id={self.device_id}")

                    # AIP v3.0 握手
                    await self._send(self._device_register_msg())
                    await asyncio.sleep(0.5)
                    await self._send(self._capability_report_msg())

                    # 启动心跳
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    try:
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                                await self._handle_message(data)
                            except json.JSONDecodeError:
                                logger.warning(f"无效 JSON: {raw[:100]}")
                    finally:
                        heartbeat_task.cancel()
                        self._ws = None

            except Exception as e:
                logger.warning(f"连接断开: {e}，5 秒后重连…")
                await asyncio.sleep(5)

    def stop(self):
        self._running = False


# ============================================================================
# 工具函数
# ============================================================================

def _get_os_version() -> str:
    try:
        import platform
        return platform.version()
    except Exception:
        return "unknown"


# ============================================================================
# 入口
# ============================================================================

def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Windows AIP v3.0 Client —— 把这台电脑接到主脑上")
    parser.add_argument("--host", default="127.0.0.1", help="主脑地址(没配对过时的兜底)")
    parser.add_argument("--port", type=int, default=8000, help="主脑端口(没配对过时的兜底)")
    parser.add_argument("--device-id", default=None, help="自定义设备 ID(默认第一次生成后固定)")
    parser.add_argument("--pair", default=None, metavar="CODE", help="主脑给的一次性配对码")
    parser.add_argument("--gateway", default=None, help="主脑地址,如 http://192.168.1.10:8000(配对时用)")
    parser.add_argument("--name", default=None, help="这台电脑在设备列表里叫什么")
    args = parser.parse_args()

    from windows_client import device_pairing as _dp

    state = _dp.load_state()
    if args.device_id:
        state["device_id"] = args.device_id
    if args.pair:
        gateway = args.gateway or f"http://{args.host}:{args.port}"
        try:
            resp = _dp.pair(
                args.pair,
                gateway,
                state,
                name=args.name or "",
                capabilities=WINDOWS_SUPPORTED_ACTIONS,
            )
        except _dp.PairingError as exc:
            print(f"✗ {exc}\n  下一步:{exc.how_to_fix}")
            raise SystemExit(2)
        _dp.save_state(state)
        print(f"✓ 已配对:{state.get('name')}({state['device_id']})")
        net = _dp.join_tailnet(resp.get("tailnet_join"), state["device_id"])
        if net.get("state") == "joined":
            print("✓ 已加入自建内网,带出门也能连回主脑")
        elif net.get("how_to_fix"):
            print(f"! 没能自动加入自建内网:{net.get('detail') or net['state']}\n  {net['how_to_fix']}")

    client = WindowsAIPClient(host=args.host, port=args.port, state=state)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("客户端已停止")
    if client.fatal:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
