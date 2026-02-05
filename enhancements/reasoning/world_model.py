"""
世界模型 (World Model)
维护对环境、资源和状态的理解
"""

import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """实体类型"""
    DEVICE = "device"
    NODE = "node"
    SERVICE = "service"
    USER = "user"
    TASK = "task"
    GOAL = "goal"


class EntityState(Enum):
    """实体状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BUSY = "busy"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class Entity:
    """实体"""
    id: str
    type: EntityType
    name: str
    state: EntityState
    properties: Dict
    last_updated: float = field(default_factory=time.time)


@dataclass
class Relationship:
    """关系"""
    from_entity_id: str
    to_entity_id: str
    relation_type: str  # 'controls', 'depends_on', 'communicates_with', etc.
    properties: Dict
    created_at: float = field(default_factory=time.time)


@dataclass
class Event:
    """事件"""
    id: str
    type: str
    entity_id: Optional[str]
    timestamp: float
    data: Dict


class WorldModel:
    """世界模型"""
    
    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.events: List[Event] = []
        self.event_history_limit = 1000
        logger.info("WorldModel initialized")
    
    def register_entity(self, entity: Entity):
        """注册实体"""
        self.entities[entity.id] = entity
        logger.info(f"注册实体: {entity.id} ({entity.type.value})")
        
        # 记录事件
        self._record_event(Event(
            id=f"event_{int(time.time() * 1000)}",
            type="entity_registered",
            entity_id=entity.id,
            timestamp=time.time(),
            data={"entity_type": entity.type.value}
        ))
    
    def update_entity_state(self, entity_id: str, new_state: EntityState):
        """更新实体状态"""
        if entity_id in self.entities:
            old_state = self.entities[entity_id].state
            self.entities[entity_id].state = new_state
            self.entities[entity_id].last_updated = time.time()
            logger.info(f"更新实体状态: {entity_id} {old_state.value} -> {new_state.value}")
            
            # 记录事件
            self._record_event(Event(
                id=f"event_{int(time.time() * 1000)}",
                type="entity_state_changed",
                entity_id=entity_id,
                timestamp=time.time(),
                data={"old_state": old_state.value, "new_state": new_state.value}
            ))
    
    def add_relationship(self, relationship: Relationship):
        """添加关系"""
        self.relationships.append(relationship)
        logger.info(f"添加关系: {relationship.from_entity_id} --{relationship.relation_type}--> {relationship.to_entity_id}")
        
        # 记录事件
        self._record_event(Event(
            id=f"event_{int(time.time() * 1000)}",
            type="relationship_added",
            entity_id=None,
            timestamp=time.time(),
            data={
                "from": relationship.from_entity_id,
                "to": relationship.to_entity_id,
                "type": relationship.relation_type
            }
        ))
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """获取实体"""
        return self.entities.get(entity_id)
    
    def get_entities_by_type(self, entity_type: EntityType) -> List[Entity]:
        """按类型获取实体"""
        return [e for e in self.entities.values() if e.type == entity_type]
    
    def get_entities_by_state(self, state: EntityState) -> List[Entity]:
        """按状态获取实体"""
        return [e for e in self.entities.values() if e.state == state]
    
    def get_related_entities(self, entity_id: str, relation_type: Optional[str] = None) -> List[Entity]:
        """获取相关实体"""
        related_ids = set()
        
        for rel in self.relationships:
            if rel.from_entity_id == entity_id:
                if relation_type is None or rel.relation_type == relation_type:
                    related_ids.add(rel.to_entity_id)
            elif rel.to_entity_id == entity_id:
                if relation_type is None or rel.relation_type == relation_type:
                    related_ids.add(rel.from_entity_id)
        
        return [self.entities[eid] for eid in related_ids if eid in self.entities]
    
    def query_state(self, query: str) -> Dict:
        """查询世界状态"""
        # 简单的查询实现
        result = {
            "total_entities": len(self.entities),
            "entities_by_type": {},
            "entities_by_state": {},
            "recent_events": self.events[-10:] if self.events else []
        }
        
        # 统计实体类型
        for entity in self.entities.values():
            type_name = entity.type.value
            if type_name not in result["entities_by_type"]:
                result["entities_by_type"][type_name] = 0
            result["entities_by_type"][type_name] += 1
        
        # 统计实体状态
        for entity in self.entities.values():
            state_name = entity.state.value
            if state_name not in result["entities_by_state"]:
                result["entities_by_state"][state_name] = 0
            result["entities_by_state"][state_name] += 1
        
        return result
    
    def predict_outcome(self, action: str, context: Dict) -> Dict:
        """预测动作结果"""
        # 简单的预测实现
        prediction = {
            "success_probability": 0.8,
            "expected_duration": 60,
            "potential_side_effects": [],
            "required_resources": []
        }
        
        # 基于历史事件进行预测
        similar_events = [e for e in self.events if e.type == action]
        if similar_events:
            # 计算成功率
            success_count = sum(1 for e in similar_events if e.data.get('success', False))
            prediction["success_probability"] = success_count / len(similar_events)
        
        return prediction
    
    def _record_event(self, event: Event):
        """记录事件"""
        self.events.append(event)
        
        # 限制事件历史长度
        if len(self.events) > self.event_history_limit:
            self.events = self.events[-self.event_history_limit:]
    
    def get_available_resources(self) -> List[Entity]:
        """获取可用资源"""
        return [
            e for e in self.entities.values()
            if e.type in [EntityType.NODE, EntityType.DEVICE, EntityType.SERVICE]
            and e.state in [EntityState.ACTIVE, EntityState.INACTIVE]
        ]
    
    def simulate_action(self, action: str, parameters: Dict) -> Dict:
        """模拟动作执行"""
        # 简单的模拟实现
        simulation_result = {
            "feasible": True,
            "estimated_duration": 30,
            "required_resources": [],
            "potential_conflicts": [],
            "recommendations": []
        }
        
        # 检查资源可用性
        available_resources = self.get_available_resources()
        if not available_resources:
            simulation_result["feasible"] = False
            simulation_result["recommendations"].append("没有可用资源")
        
        return simulation_result


if __name__ == '__main__':
    # 测试世界模型
    logging.basicConfig(level=logging.INFO)
    
    world = WorldModel()
    
    # 注册一些实体
    world.register_entity(Entity(
        id="device_android_001",
        type=EntityType.DEVICE,
        name="Android Phone",
        state=EntityState.ACTIVE,
        properties={"battery": 85, "connected": True}
    ))
    
    world.register_entity(Entity(
        id="node_43",
        type=EntityType.NODE,
        name="MAVLink Drone Controller",
        state=EntityState.ACTIVE,
        properties={"capabilities": ["drone_control", "telemetry"]}
    ))
    
    world.register_entity(Entity(
        id="node_49",
        type=EntityType.NODE,
        name="OctoPrint 3D Printer",
        state=EntityState.INACTIVE,
        properties={"capabilities": ["3d_printing"]}
    ))
    
    # 添加关系
    world.add_relationship(Relationship(
        from_entity_id="device_android_001",
        to_entity_id="node_43",
        relation_type="controls",
        properties={}
    ))
    
    # 更新状态
    world.update_entity_state("node_49", EntityState.BUSY)
    
    # 查询状态
    state = world.query_state("")
    print(f"\n世界状态:")
    print(f"  总实体数: {state['total_entities']}")
    print(f"  按类型: {state['entities_by_type']}")
    print(f"  按状态: {state['entities_by_state']}")
    print(f"  最近事件: {len(state['recent_events'])} 个")
    
    # 获取可用资源
    resources = world.get_available_resources()
    print(f"\n可用资源: {len(resources)} 个")
    for res in resources:
        print(f"  - {res.name} ({res.state.value})")
    
    # 预测结果
    prediction = world.predict_outcome("drone_takeoff", {})
    print(f"\n预测结果:")
    print(f"  成功概率: {prediction['success_probability']}")
    print(f"  预计时长: {prediction['expected_duration']} 秒")
