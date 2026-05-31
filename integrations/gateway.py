"""
SmartHomeGateway — 统一智能家居网关

Galaxy 内部所有智能家居交互的入口。
桥接 Home Assistant 实体和 Galaxy 内部模型。

线程安全：所有公共 API 均为 async，内部状态由 asyncio 单线程调度保护。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from .connector import HAConnector, HAError
from .discovery import EntityDiscovery, GalaxyEntity

logger = logging.getLogger('galaxy.smarthome.gateway')

# Natural language → service mapping
NL_COMMANDS: dict[str, tuple[str, str]] = {
    '开灯': ('light', 'turn_on'),
    '关灯': ('light', 'turn_off'),
    '开': ('homeassistant', 'turn_on'),
    '关': ('homeassistant', 'turn_off'),
    'toggle': ('homeassistant', 'toggle'),
    '播放': ('media_player', 'media_play'),
    '暂停': ('media_player', 'media_pause'),
    '停止': ('media_player', 'media_stop'),
}

# Prevent task garbage collection
_sentinel_tasks: set[asyncio.Task[None]] = set()


def _fire_and_forget(coro: Coroutine[Any, Any, None]) -> None:
    """Schedule a coroutine without awaiting, preventing GC."""
    task = asyncio.create_task(coro)
    _sentinel_tasks.add(task)
    task.add_done_callback(_sentinel_tasks.discard)


class SmartHomeGateway:
    """Central gateway for all smart home operations."""

    def __init__(
        self,
        connector: HAConnector,
        discovery: EntityDiscovery,
        on_state_change: Optional[
            Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
        ] = None,
    ) -> None:
        self._connector = connector
        self._discovery = discovery
        self._on_state_change = on_state_change
        self._sub_id: Optional[int] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connector.connected and self._initialized

    @property
    def initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialize gateway with rollback on partial failure."""
        async with self._init_lock:
            if self._initialized:
                return

            try:
                # Step 1: Establish WebSocket
                await self._connector.connect()

                # Step 2: Wait for authentication
                for _ in range(50):  # 5s timeout for auth
                    if self._connector.auth_ok:
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise HAError("Authentication timeout")

                # Step 3: Full entity discovery
                await self._discovery.refresh_all()

                # Step 4: Subscribe to live state changes
                self._sub_id = await self._connector.subscribe_state_changes(
                    self._on_ha_event
                )

                self._initialized = True
                logger.info("SmartHomeGateway fully initialized")

            except Exception:
                # Rollback: disconnect everything on partial init
                logger.exception("Gateway init failed, rolling back")
                try:
                    await self._connector.disconnect()
                except Exception:
                    pass
                self._initialized = False
                raise

    async def disconnect(self) -> None:
        """Graceful shutdown with idempotency."""
        async with self._init_lock:
            if not self._initialized:
                # Still try to disconnect connector if it was partially started
                try:
                    await self._connector.disconnect()
                except Exception:
                    pass
                return

            self._initialized = False
            await self._connector.disconnect()
            self._sub_id = None
            logger.info("SmartHomeGateway disconnected")

    # ------------------------------------------------------------------
    # Query API (used by Galaxy NLU / agents)
    # ------------------------------------------------------------------

    def list_entities(
        self,
        *,
        area: Optional[str] = None,
        domain: Optional[str] = None,
        controllable_only: bool = False,
    ) -> list[GalaxyEntity]:
        """List entities with optional filters. Safe to call anytime."""
        results = list(self._discovery.entities.values())
        if area:
            results = [e for e in results if e.area == area]
        if domain:
            results = [e for e in results if e.domain == domain]
        if controllable_only:
            results = [e for e in results if e.controllable]
        return results

    def get_entity(self, entity_id: str) -> Optional[GalaxyEntity]:
        if not entity_id or '.' not in entity_id:
            return None
        return self._discovery.entities.get(entity_id)

    def find_by_name(self, name: str) -> list[GalaxyEntity]:
        """Fuzzy match by friendly_name or entity_id."""
        if not name:
            return []
        name_lower = name.lower()
        results: list[GalaxyEntity] = []
        for entity in self._discovery.entities.values():
            if name_lower in entity.friendly_name.lower():
                results.append(entity)
            elif name_lower in entity.entity_id.lower():
                results.append(entity)
        return results

    # ------------------------------------------------------------------
    # Control API
    # ------------------------------------------------------------------

    async def turn_on(self, entity_id: str, **kwargs: Any) -> None:
        if not self._validate_entity_id(entity_id):
            raise ValueError(f"Invalid entity_id: {entity_id}")
        await self._call_service(entity_id, 'turn_on', kwargs or None)

    async def turn_off(self, entity_id: str) -> None:
        if not self._validate_entity_id(entity_id):
            raise ValueError(f"Invalid entity_id: {entity_id}")
        await self._call_service(entity_id, 'turn_off')

    async def toggle(self, entity_id: str) -> None:
        if not self._validate_entity_id(entity_id):
            raise ValueError(f"Invalid entity_id: {entity_id}")
        await self._call_service(entity_id, 'toggle')

    async def set_brightness(self, entity_id: str, brightness_pct: int) -> None:
        """brightness_pct: 0-100"""
        if not self._validate_entity_id(entity_id):
            raise ValueError(f"Invalid entity_id: {entity_id}")
        brightness = max(0, min(100, int(brightness_pct)))
        await self._call_service(
            entity_id, 'turn_on',
            {'brightness_pct': brightness}
        )

    async def set_temperature(self, entity_id: str, temperature: float) -> None:
        """climate entity only"""
        if not self._validate_entity_id(entity_id):
            raise ValueError(f"Invalid entity_id: {entity_id}")
        await self._call_service(
            entity_id, 'set_temperature',
            {'temperature': float(temperature)}
        )

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[dict[str, Any]] = None,
        target: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._connector.call_service(
            domain, service, service_data, target
        )

    # ------------------------------------------------------------------
    # Natural language command handler
    # ------------------------------------------------------------------

    async def handle_command(self, command: str, target_name: str) -> str:
        """Process natural language smart home command.

        Returns human-readable result for TTS. Never raises.
        """
        try:
            # Validate inputs
            if not command or not target_name:
                return '请提供命令和设备名称'

            # Resolve target
            targets = self.find_by_name(target_name)
            if not targets:
                return f'找不到设备「{target_name}」'
            if len(targets) > 1:
                names = '、'.join(t.friendly_name for t in targets[:3])
                return f'找到多个匹配：{names}，请说得更具体些'

            entity = targets[0]
            if not entity.controllable:
                return f'「{entity.friendly_name}」不可控制'

            # Resolve action from command text
            action = self._resolve_action(command, entity.domain)
            domain, service = action

            await self._connector.call_service(
                domain or entity.domain,
                service,
                target={'entity_id': entity.entity_id},
            )

            # Build friendly response
            action_desc = self._action_description(command, service)
            return f'已{action_desc}「{entity.friendly_name}」'

        except HAError as exc:
            logger.warning("HA command failed: %s", exc)
            return f'操作失败：{exc}'
        except Exception as exc:
            logger.exception("Unexpected error in handle_command")
            return f'系统错误：{exc}'

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_entity_id(entity_id: str) -> bool:
        if not entity_id or not isinstance(entity_id, str):
            return False
        return '.' in entity_id and len(entity_id.split('.')) == 2

    async def _call_service(
        self,
        entity_id: str,
        service: str,
        service_data: Optional[dict[str, Any]] = None,
    ) -> None:
        domain = entity_id.split('.', 1)[0]
        await self._connector.call_service(
            domain, service, service_data,
            target={'entity_id': entity_id},
        )

    def _on_ha_event(self, event: dict[str, Any]) -> None:
        entity = self._discovery.update_from_event(event)
        if entity and self._on_state_change:
            _fire_and_forget(self._on_state_change(entity.entity_id, {
                'state': entity.state,
                'attributes': entity.attributes,
            }))

    @staticmethod
    def _resolve_action(command: str, default_domain: str) -> tuple[str, str]:
        """Resolve NL command to (domain, service)."""
        for key, (d, s) in NL_COMMANDS.items():
            if key in command:
                return d, s
        # Default to toggle
        return default_domain, 'toggle'

    @staticmethod
    def _action_description(command: str, service: str) -> str:
        """Convert service to Chinese verb."""
        if 'turn_on' in service or '开' in command:
            return '打开'
        elif 'turn_off' in service or '关' in command:
            return '关闭'
        elif 'toggle' in service:
            return '切换'
        elif 'play' in service:
            return '播放'
        elif 'pause' in service:
            return '暂停'
        elif 'stop' in service:
            return '停止'
        return '操作'
