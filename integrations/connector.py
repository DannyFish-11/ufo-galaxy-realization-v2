"""
Home Assistant WebSocket 长连接管理器

- 自动重连（指数退避，带 jitter）
- 状态订阅推送
- 服务调用 RPC（带超时和取消清理）
- 连接断开时自动清理 pending futures
- 兼容 HA Core 2023.1+
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Callable, Optional

import aiohttp

logger = logging.getLogger('galaxy.smarthome.connector')

# HA WebSocket API message types
WS_TYPE_AUTH = 'auth'
WS_TYPE_AUTH_REQUIRED = 'auth_required'
WS_TYPE_AUTH_OK = 'auth_ok'
WS_TYPE_AUTH_INVALID = 'auth_invalid'
WS_TYPE_SUBSCRIBE_EVENTS = 'subscribe_events'
WS_TYPE_SUBSCRIBE_TRIGGER = 'subscribe_trigger'
WS_TYPE_UNSUBSCRIBE_EVENTS = 'unsubscribe_events'
WS_TYPE_CALL_SERVICE = 'call_service'
WS_TYPE_RESULT = 'result'
WS_TYPE_EVENT = 'event'
WS_TYPE_PING = 'ping'
WS_TYPE_PONG = 'pong'


class HAConnector:
    """WebSocket client for Home Assistant."""

    def __init__(self, url: str, token: str) -> None:
        # Normalize URL to WebSocket endpoint
        base = url.rstrip('/')
        if base.startswith('https://'):
            self._ws_url = base.replace('https://', 'wss://', 1) + '/api/websocket'
        elif base.startswith('http://'):
            self._ws_url = base.replace('http://', 'ws://', 1) + '/api/websocket'
        else:
            self._ws_url = f'ws://{base}/api/websocket'

        self._http_url = base
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_task: Optional[asyncio.Task[None]] = None
        self._id_counter = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._event_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._running = False
        self._auth_ok = False
        self._connect_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()

    @property
    def connected(self) -> bool:
        return (
            self._session is not None
            and self._ws is not None
            and not self._ws.closed
            and self._auth_ok
        )

    @property
    def auth_ok(self) -> bool:
        return self._auth_ok

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        async with self._connect_lock:
            if self._running:
                logger.debug("HAConnector already running")
                return
            self._running = True
            self._shutdown_event.clear()
            try:
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30, connect=10)
                )
            except Exception as exc:
                self._running = False
                raise HAError(f"Failed to create HTTP session: {exc}") from exc
            self._ws_task = asyncio.create_task(
                self._ws_loop(), name='ha-websocket-loop'
            )

    async def disconnect(self) -> None:
        async with self._connect_lock:
            if not self._running:
                return
            self._running = False
            self._shutdown_event.set()

            # Cancel pending futures to prevent memory leaks
            pending_items = list(self._pending.items())
            self._pending.clear()
            for msg_id, fut in pending_items:
                if not fut.done():
                    fut.cancel()

            if self._ws_task and not self._ws_task.done():
                self._ws_task.cancel()
                try:
                    await asyncio.wait_for(self._ws_task, timeout=5)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            if self._ws and not self._ws.closed:
                try:
                    await self._ws.close()
                except Exception:
                    pass
            self._ws = None

            if self._session:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None

            self._auth_ok = False
            self._event_callbacks.clear()
            logger.debug("HAConnector disconnected cleanly")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe_state_changes(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> int:
        """Subscribe to state_changed events. Returns subscription id."""
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)
        try:
            sub_id = await self._send_subscribe('state_changed')
            return sub_id
        except Exception:
            # Rollback on failure
            if callback in self._event_callbacks:
                self._event_callbacks.remove(callback)
            raise

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[dict[str, Any]] = None,
        target: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Call a Home Assistant service with timeout and cleanup."""
        if not self.connected:
            raise HAError("Not connected to Home Assistant")

        self._id_counter += 1
        msg_id = self._id_counter

        payload: dict[str, Any] = {
            'id': msg_id,
            'type': WS_TYPE_CALL_SERVICE,
            'domain': domain,
            'service': service,
        }
        if service_data:
            payload['service_data'] = service_data
        if target:
            payload['target'] = target

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[msg_id] = fut

        try:
            await self._ws_send(payload)
            result = await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise HAError(f"Service call timeout: {domain}.{service}")
        except asyncio.CancelledError:
            self._pending.pop(msg_id, None)
            raise
        finally:
            self._pending.pop(msg_id, None)

        if not result.get('success'):
            error = result.get('error', {})
            raise HAError(error.get('message', f'Unknown HA error in {domain}.{service}'))
        return result.get('result', {})

    async def get_states(self) -> list[dict[str, Any]]:
        """Fetch full state snapshot via REST with retry."""
        if not self._session:
            raise HAError('Not connected')

        headers = {
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
        }
        url = f'{self._http_url}/api/states'

        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if not isinstance(data, list):
                        raise HAError(f"Unexpected response type: {type(data)}")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                wait = 2 ** attempt + random.uniform(0, 1)
                logger.warning("get_states attempt %d failed: %s, retrying in %.1fs", attempt + 1, exc, wait)
                await asyncio.sleep(wait)

        raise HAError(f"Failed to fetch states after 3 attempts: {last_exc}")

    # ------------------------------------------------------------------
    # Internal WebSocket loop
    # ------------------------------------------------------------------

    async def _ws_loop(self) -> None:
        while self._running:
            try:
                await self._connect_once()
                self._reconnect_delay = 1.0  # Reset on success
            except asyncio.CancelledError:
                logger.debug("WebSocket loop cancelled")
                break
            except Exception as exc:
                if not self._running:
                    break
                # Jitter to prevent thundering herd on HA restart
                jitter = random.uniform(0, 1)
                delay = min(self._reconnect_delay + jitter, self._max_reconnect_delay)
                logger.warning(
                    'HA WebSocket error: %s. Reconnecting in %.1fs...',
                    exc, delay,
                )
                await asyncio.sleep(delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def _connect_once(self) -> None:
        if not self._session:
            raise HAError("Session not initialized")

        logger.info('Connecting to HA WebSocket: %s', self._ws_url)

        try:
            self._ws = await self._session.ws_connect(
                self._ws_url,
                heartbeat=30.0,
                autoclose=True,
                autoping=True,
            )
        except Exception as exc:
            raise HAError(f"WebSocket connection failed: {exc}") from exc

        # Step 1: Wait for auth_required
        msg = await self._ws.receive()
        if msg.type == aiohttp.WSMsgType.CLOSED:
            raise HAError("Connection closed before auth_required")
        if msg.type == aiohttp.WSMsgType.ERROR:
            raise HAError("WebSocket error before auth")
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise HAError(f"Unexpected message type: {msg.type}")

        data = json.loads(msg.data)
        if data.get('type') != WS_TYPE_AUTH_REQUIRED:
            raise HAError(f'Expected auth_required, got {data.get("type")}')

        # Step 2: Send auth
        await self._ws_send({
            'type': WS_TYPE_AUTH,
            'access_token': self._token,
        })

        # Step 3: Wait for auth_ok
        msg = await self._ws.receive()
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise HAError(f"Unexpected auth response type: {msg.type}")

        data = json.loads(msg.data)
        if data.get('type') == WS_TYPE_AUTH_INVALID:
            raise HAError(f'Authentication failed: {data.get("message")}')
        if data.get('type') != WS_TYPE_AUTH_OK:
            raise HAError(f'Unexpected auth response: {data.get("type")}')

        self._auth_ok = True
        logger.info('Home Assistant WebSocket authenticated')

        # Step 4: Message loop
        try:
            async for msg in self._ws:
                if not self._running:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self._handle_message(json.loads(msg.data))
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON from HA")
                elif msg.type == aiohttp.WSMsgType.PING:
                    await self._ws.pong()
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    break
        finally:
            self._auth_ok = False
            logger.info('HA WebSocket connection ended')

    async def _handle_message(self, data: dict[str, Any]) -> None:
        msg_type = data.get('type')
        msg_id = data.get('id')

        if msg_type == WS_TYPE_RESULT and msg_id in self._pending:
            fut = self._pending.pop(msg_id)
            if not fut.done():
                fut.set_result(data)

        elif msg_type == WS_TYPE_EVENT:
            event = data.get('event', {})
            for cb in list(self._event_callbacks):
                try:
                    cb(event)
                except Exception:
                    logger.exception('Event callback error, removing callback')
                    if cb in self._event_callbacks:
                        self._event_callbacks.remove(cb)

        elif msg_type == WS_TYPE_PING:
            await self._ws_send({'id': msg_id, 'type': WS_TYPE_PONG})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _send_subscribe(self, event_type: str) -> int:
        self._id_counter += 1
        sub_id = self._id_counter
        await self._ws_send({
            'id': sub_id,
            'type': WS_TYPE_SUBSCRIBE_EVENTS,
            'event_type': event_type,
        })
        return sub_id

    async def _ws_send(self, payload: dict[str, Any]) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send_json(payload)
            except Exception as exc:
                logger.warning("Failed to send WebSocket message: %s", exc)
                raise HAError(f"WebSocket send failed: {exc}") from exc
        else:
            raise HAError("WebSocket not connected")


class HAError(Exception):
    """Home Assistant API error."""
