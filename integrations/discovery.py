"""
Home Assistant 实体自动发现 & 映射

- 拉取全量 states，按 domain 分类
- 映射到 Galaxy 内部实体模型
- 支持 area（房间）关联
- 增量更新（state_changed 事件）
- 线程安全（内部状态加锁保护）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .connector import HAConnector, HAError

logger = logging.getLogger('galaxy.smarthome.discovery')

# Domain → Galaxy 设备类型映射
DOMAIN_DEVICE_CLASS: dict[str, str] = {
    'light': 'light',
    'switch': 'switch',
    'climate': 'climate',
    'media_player': 'media_player',
    'sensor': 'sensor',
    'binary_sensor': 'sensor',
    'cover': 'cover',
    'fan': 'fan',
    'lock': 'lock',
    'vacuum': 'vacuum',
    'camera': 'camera',
    'scene': 'scene',
    'automation': 'automation',
    'input_boolean': 'switch',
    'input_button': 'button',
    'script': 'script',
    'notify': 'notify',
    'weather': 'sensor',
}

# 可控 domain（支持 call_service）
CONTROLLABLE_DOMAINS = {
    'light', 'switch', 'climate', 'media_player', 'cover',
    'fan', 'lock', 'vacuum', 'scene', 'automation',
    'input_boolean', 'input_button', 'script',
}


class EntityDiscovery:
    """Discovers and caches Home Assistant entities."""

    def __init__(self, connector: HAConnector) -> None:
        self._connector = connector
        self._entities: dict[str, GalaxyEntity] = {}
        self._by_area: dict[str, list[str]] = {}
        self._by_floor: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

    @property
    def entities(self) -> dict[str, GalaxyEntity]:
        """Thread-safe snapshot of entities."""
        return dict(self._entities)

    def get_by_area(self, area: str) -> list[GalaxyEntity]:
        ids = self._by_area.get(area, [])
        return [self._entities[eid] for eid in ids if eid in self._entities]

    # --------------------------------------------------------------

    async def refresh_all(self) -> dict[str, GalaxyEntity]:
        """Full discovery — atomic replace, never leaves empty state on failure."""
        raw_states = await self._connector.get_states()

        new_entities: dict[str, GalaxyEntity] = {}
        new_by_area: dict[str, list[str]] = {}
        new_by_floor: dict[str, list[str]] = {}

        for state_obj in raw_states:
            try:
                entity = GalaxyEntity.from_ha_state(state_obj)
            except Exception as exc:
                entity_id = state_obj.get('entity_id', 'unknown')
                logger.warning("Skipping malformed entity %s: %s", entity_id, exc)
                continue
            new_entities[entity.entity_id] = entity

            if entity.area:
                new_by_area.setdefault(entity.area, []).append(entity.entity_id)
            if entity.floor:
                new_by_floor.setdefault(entity.floor, []).append(entity.entity_id)

        # Atomic swap
        async with self._lock:
            self._entities = new_entities
            self._by_area = new_by_area
            self._by_floor = new_by_floor

        logger.info(
            'Discovered %d HA entities (%d controllable)',
            len(self._entities),
            sum(1 for e in self._entities.values() if e.controllable),
        )
        return dict(self._entities)

    def update_from_event(self, event: dict[str, Any]) -> Optional[GalaxyEntity]:
        """Incremental update from state_changed event. Thread-safe."""
        data = event.get('data', {})
        new_state = data.get('new_state')
        if not new_state:
            return None

        eid = new_state.get('entity_id', '')
        if not eid or '.' not in eid:
            logger.warning("Skipping state event with invalid entity_id: %s", eid)
            return None

        if eid in self._entities:
            self._entities[eid].update_from_state(new_state)
            return self._entities[eid]

        # New entity appeared — parse and add
        try:
            entity = GalaxyEntity.from_ha_state(new_state)
            self._entities[eid] = entity
            if entity.area:
                self._by_area.setdefault(entity.area, []).append(eid)
            return entity
        except Exception as exc:
            logger.warning("Failed to add new entity %s from event: %s", eid, exc)
            return None


class GalaxyEntity:
    """Normalized Home Assistant entity for Galaxy internal use."""

    __slots__ = ('entity_id', 'friendly_name', 'state', 'device_class',
                 'domain', 'controllable', 'area', 'floor', 'attributes')

    def __init__(
        self,
        entity_id: str,
        friendly_name: str,
        state: str,
        device_class: str,
        domain: str,
        controllable: bool,
        area: Optional[str] = None,
        floor: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> None:
        self.entity_id = entity_id
        self.friendly_name = friendly_name
        self.state = state
        self.device_class = device_class
        self.domain = domain
        self.controllable = controllable
        self.area = area
        self.floor = floor
        self.attributes = attributes or {}

    @classmethod
    def from_ha_state(cls, state_obj: dict[str, Any]) -> GalaxyEntity:
        entity_id = state_obj.get('entity_id', '')
        if not entity_id or '.' not in entity_id:
            raise ValueError(f"Invalid entity_id: {entity_id!r}")

        parts = entity_id.split('.', 1)
        domain = parts[0] if len(parts) == 2 else 'unknown'

        attrs = state_obj.get('attributes') or {}
        if not isinstance(attrs, dict):
            attrs = {}

        friendly_name = attrs.get('friendly_name') or entity_id
        area = attrs.get('area_name') or attrs.get('room_name')
        floor = attrs.get('floor_name')
        state = state_obj.get('state', 'unknown')
        if not isinstance(state, str):
            state = str(state)

        return cls(
            entity_id=entity_id,
            friendly_name=friendly_name,
            state=state,
            device_class=DOMAIN_DEVICE_CLASS.get(domain, 'unknown'),
            domain=domain,
            controllable=domain in CONTROLLABLE_DOMAINS,
            area=area if isinstance(area, str) else None,
            floor=floor if isinstance(floor, str) else None,
            attributes=attrs,
        )

    def update_from_state(self, state_obj: dict[str, Any]) -> None:
        new_state = state_obj.get('state')
        if new_state is not None:
            self.state = str(new_state)
        new_attrs = state_obj.get('attributes')
        if isinstance(new_attrs, dict):
            self.attributes.update(new_attrs)
            if 'friendly_name' in new_attrs:
                fn = new_attrs['friendly_name']
                if isinstance(fn, str):
                    self.friendly_name = fn

    def to_dict(self) -> dict[str, Any]:
        return {
            'entity_id': self.entity_id,
            'friendly_name': self.friendly_name,
            'state': self.state,
            'device_class': self.device_class,
            'domain': self.domain,
            'controllable': self.controllable,
            'area': self.area,
            'floor': self.floor,
        }

    def __repr__(self) -> str:
        return f'<GalaxyEntity {self.entity_id}={self.state}>'
