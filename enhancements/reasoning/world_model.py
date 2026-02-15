"""
三位一体世界模型 (Trinity World Model)
=======================================

三大支柱完整实现：
1. 本体论 (Ontology) - 世界中有什么：实体、关系、类型层级
2. 认知论 (Epistemology) - 如何认知世界：置信度、知识验证、信念管理
3. 信息论 (Information) - 信息如何流动：事件流、因果链、状态转移

三者协同工作：
- 本体论定义"世界是什么"
- 认知论管理"我们知道多少，有多确定"
- 信息论追踪"发生了什么，为什么发生"
"""

import logging
import time
import json
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 第一支柱：本体论 (Ontology)
# ═══════════════════════════════════════════════════

class EntityType(Enum):
    """实体类型"""
    DEVICE = "device"
    NODE = "node"
    SERVICE = "service"
    USER = "user"
    TASK = "task"
    GOAL = "goal"
    AGENT = "agent"
    CONCEPT = "concept"


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
    parent_type: Optional[str] = None  # 类型继承
    tags: List[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


@dataclass
class Relationship:
    """关系"""
    from_entity_id: str
    to_entity_id: str
    relation_type: str  # 'controls', 'depends_on', 'communicates_with', etc.
    properties: Dict
    strength: float = 1.0  # 关系强度 0-1
    created_at: float = field(default_factory=time.time)


class Ontology:
    """
    本体论模块

    管理世界中的实体和关系，提供：
    - 实体注册和类型层级
    - 语义关系网络
    - 图查询（路径、邻居、子图）
    - 约束验证
    """

    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self._type_hierarchy: Dict[str, List[str]] = {}  # type → subtypes
        self._relation_index: Dict[str, List[int]] = defaultdict(list)  # entity_id → rel indices
        self._constraints: List[Dict] = []

    def register_entity(self, entity: Entity):
        """注册实体"""
        self.entities[entity.id] = entity
        logger.debug(f"注册实体: {entity.id} ({entity.type.value})")

    def remove_entity(self, entity_id: str):
        """移除实体及相关关系"""
        if entity_id in self.entities:
            del self.entities[entity_id]
            self.relationships = [
                r for r in self.relationships
                if r.from_entity_id != entity_id and r.to_entity_id != entity_id
            ]
            self._rebuild_relation_index()

    def add_relationship(self, relationship: Relationship):
        """添加关系"""
        idx = len(self.relationships)
        self.relationships.append(relationship)
        self._relation_index[relationship.from_entity_id].append(idx)
        self._relation_index[relationship.to_entity_id].append(idx)

    def define_type_hierarchy(self, parent_type: str, child_types: List[str]):
        """定义类型层级"""
        self._type_hierarchy[parent_type] = child_types

    def add_constraint(self, constraint: Dict):
        """
        添加本体约束

        例如: {"type": "cardinality", "entity_type": "drone",
               "relation": "controlled_by", "max": 1}
        """
        self._constraints.append(constraint)

    def validate_constraints(self) -> List[str]:
        """验证所有约束，返回违规列表"""
        violations = []
        for constraint in self._constraints:
            if constraint["type"] == "cardinality":
                entity_type = constraint.get("entity_type")
                relation = constraint.get("relation")
                max_count = constraint.get("max", float("inf"))

                for entity in self.entities.values():
                    if entity.type.value == entity_type:
                        count = sum(
                            1 for r in self.relationships
                            if (r.from_entity_id == entity.id or r.to_entity_id == entity.id)
                            and r.relation_type == relation
                        )
                        if count > max_count:
                            violations.append(
                                f"实体 {entity.id} 的 '{relation}' 关系数 ({count}) "
                                f"超过最大限制 ({max_count})"
                            )
        return violations

    # ─── 图查询 ───

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    def get_entities_by_type(self, entity_type: EntityType) -> List[Entity]:
        return [e for e in self.entities.values() if e.type == entity_type]

    def get_entities_by_state(self, state: EntityState) -> List[Entity]:
        return [e for e in self.entities.values() if e.state == state]

    def get_entities_by_tag(self, tag: str) -> List[Entity]:
        return [e for e in self.entities.values() if tag in e.tags]

    def get_neighbors(self, entity_id: str,
                      relation_type: Optional[str] = None,
                      direction: str = "both") -> List[Tuple[Entity, str]]:
        """
        获取邻居实体

        Returns: [(entity, relation_type), ...]
        """
        neighbors = []
        for rel in self.relationships:
            if direction in ("both", "out") and rel.from_entity_id == entity_id:
                if relation_type is None or rel.relation_type == relation_type:
                    if rel.to_entity_id in self.entities:
                        neighbors.append((self.entities[rel.to_entity_id], rel.relation_type))
            if direction in ("both", "in") and rel.to_entity_id == entity_id:
                if relation_type is None or rel.relation_type == relation_type:
                    if rel.from_entity_id in self.entities:
                        neighbors.append((self.entities[rel.from_entity_id], rel.relation_type))
        return neighbors

    def find_path(self, from_id: str, to_id: str,
                  max_depth: int = 5) -> Optional[List[str]]:
        """BFS 查找两个实体之间的最短路径"""
        if from_id == to_id:
            return [from_id]

        visited = {from_id}
        queue = deque([(from_id, [from_id])])

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue

            for neighbor, _ in self.get_neighbors(current):
                if neighbor.id == to_id:
                    return path + [to_id]
                if neighbor.id not in visited:
                    visited.add(neighbor.id)
                    queue.append((neighbor.id, path + [neighbor.id]))

        return None

    def get_subgraph(self, center_id: str, depth: int = 2) -> Dict:
        """获取以某实体为中心的子图"""
        nodes = set()
        edges = []

        def traverse(entity_id: str, current_depth: int):
            if current_depth > depth or entity_id in nodes:
                return
            nodes.add(entity_id)
            for neighbor, rel_type in self.get_neighbors(entity_id):
                edges.append({
                    "from": entity_id, "to": neighbor.id,
                    "type": rel_type,
                })
                traverse(neighbor.id, current_depth + 1)

        traverse(center_id, 0)
        return {
            "center": center_id,
            "nodes": [self.entities[n].id for n in nodes if n in self.entities],
            "edges": edges,
        }

    def _rebuild_relation_index(self):
        self._relation_index.clear()
        for i, rel in enumerate(self.relationships):
            self._relation_index[rel.from_entity_id].append(i)
            self._relation_index[rel.to_entity_id].append(i)


# ═══════════════════════════════════════════════════
# 第二支柱：认知论 (Epistemology)
# ═══════════════════════════════════════════════════

class ConfidenceLevel(Enum):
    """置信度等级"""
    CERTAIN = "certain"          # > 0.95
    HIGH = "high"                # 0.8 - 0.95
    MODERATE = "moderate"        # 0.5 - 0.8
    LOW = "low"                  # 0.2 - 0.5
    SPECULATIVE = "speculative"  # < 0.2


@dataclass
class Belief:
    """信念 - 对某个事实的认知"""
    id: str
    subject: str        # 关于什么实体
    predicate: str      # 关于什么属性/关系
    value: Any          # 信念内容
    confidence: float   # 置信度 0-1
    evidence: List[str] = field(default_factory=list)  # 支撑证据
    source: str = "observation"   # 来源: observation, inference, report, default
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    decay_rate: float = 0.01  # 置信度衰减速率 (每秒)

    @property
    def level(self) -> ConfidenceLevel:
        if self.confidence > 0.95:
            return ConfidenceLevel.CERTAIN
        elif self.confidence > 0.8:
            return ConfidenceLevel.HIGH
        elif self.confidence > 0.5:
            return ConfidenceLevel.MODERATE
        elif self.confidence > 0.2:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.SPECULATIVE

    def current_confidence(self) -> float:
        """考虑时间衰减后的当前置信度"""
        elapsed = time.time() - self.updated_at
        decayed = self.confidence * math.exp(-self.decay_rate * elapsed)
        return max(0.01, decayed)


class Epistemology:
    """
    认知论模块

    管理系统对世界的认知，提供：
    - 信念管理（CRUD）
    - 置信度跟踪和衰减
    - 证据融合（多源信息的贝叶斯更新）
    - 矛盾检测
    - 知识缺口识别
    """

    def __init__(self):
        self.beliefs: Dict[str, Belief] = {}
        self._belief_index: Dict[str, List[str]] = defaultdict(list)  # subject → [belief_ids]
        self._contradiction_log: List[Dict] = []

    def assert_belief(self, subject: str, predicate: str, value: Any,
                      confidence: float = 0.8, source: str = "observation",
                      evidence: Optional[List[str]] = None) -> Belief:
        """
        声明一个信念

        如果已存在相同 subject+predicate 的信念：
        - 值相同 → 增强置信度
        - 值不同 → 记录矛盾，保留置信度更高的
        """
        belief_key = f"{subject}:{predicate}"
        existing = self.beliefs.get(belief_key)

        if existing:
            if existing.value == value:
                # 一致证据 → 贝叶斯更新增强置信度
                existing.confidence = self._bayesian_update(
                    existing.confidence, confidence
                )
                existing.updated_at = time.time()
                if evidence:
                    existing.evidence.extend(evidence)
                return existing
            else:
                # 矛盾 → 记录并决定保留哪个
                self._contradiction_log.append({
                    "subject": subject,
                    "predicate": predicate,
                    "old_value": existing.value,
                    "old_confidence": existing.confidence,
                    "new_value": value,
                    "new_confidence": confidence,
                    "timestamp": time.time(),
                })
                if confidence > existing.current_confidence():
                    # 新信念更强 → 替换
                    existing.value = value
                    existing.confidence = confidence
                    existing.source = source
                    existing.updated_at = time.time()
                    existing.evidence = evidence or []
                return existing

        # 新信念
        belief = Belief(
            id=belief_key, subject=subject, predicate=predicate,
            value=value, confidence=confidence, source=source,
            evidence=evidence or [],
        )
        self.beliefs[belief_key] = belief
        self._belief_index[subject].append(belief_key)
        return belief

    def query_belief(self, subject: str,
                     predicate: Optional[str] = None,
                     min_confidence: float = 0.0) -> List[Belief]:
        """查询信念"""
        belief_keys = self._belief_index.get(subject, [])
        results = []
        for key in belief_keys:
            belief = self.beliefs.get(key)
            if not belief:
                continue
            if predicate and belief.predicate != predicate:
                continue
            if belief.current_confidence() < min_confidence:
                continue
            results.append(belief)
        return results

    def get_confidence(self, subject: str, predicate: str) -> float:
        """获取特定信念的当前置信度"""
        belief = self.beliefs.get(f"{subject}:{predicate}")
        if belief:
            return belief.current_confidence()
        return 0.0

    def retract_belief(self, subject: str, predicate: str):
        """撤回信念"""
        key = f"{subject}:{predicate}"
        if key in self.beliefs:
            del self.beliefs[key]
            if key in self._belief_index.get(subject, []):
                self._belief_index[subject].remove(key)

    def identify_knowledge_gaps(self, entity_ids: List[str],
                                required_predicates: List[str]) -> List[Dict]:
        """
        识别知识缺口

        对给定实体检查是否缺少关键信念
        """
        gaps = []
        for entity_id in entity_ids:
            for pred in required_predicates:
                beliefs = self.query_belief(entity_id, pred)
                if not beliefs:
                    gaps.append({
                        "entity": entity_id,
                        "missing_predicate": pred,
                        "severity": "high",
                    })
                elif all(b.current_confidence() < 0.5 for b in beliefs):
                    gaps.append({
                        "entity": entity_id,
                        "missing_predicate": pred,
                        "severity": "medium",
                        "current_confidence": max(b.current_confidence() for b in beliefs),
                    })
        return gaps

    def get_contradictions(self, recent: int = 20) -> List[Dict]:
        """获取最近的矛盾记录"""
        return self._contradiction_log[-recent:]

    @staticmethod
    def _bayesian_update(prior: float, likelihood: float) -> float:
        """贝叶斯置信度更新"""
        # 简化的贝叶斯更新
        # P(H|E) = P(E|H) * P(H) / P(E)
        # 这里用简化公式：两个独立证据的联合置信度
        combined = 1 - (1 - prior) * (1 - likelihood)
        return min(0.99, combined)

    def get_summary(self) -> Dict:
        by_level = defaultdict(int)
        for b in self.beliefs.values():
            by_level[b.level.value] += 1
        return {
            "total_beliefs": len(self.beliefs),
            "by_confidence_level": dict(by_level),
            "contradictions": len(self._contradiction_log),
        }


# ═══════════════════════════════════════════════════
# 第三支柱：信息论 (Information)
# ═══════════════════════════════════════════════════

@dataclass
class Event:
    """事件"""
    id: str
    type: str
    entity_id: Optional[str]
    timestamp: float
    data: Dict
    cause_event_id: Optional[str] = None  # 因果链
    processed: bool = False


@dataclass
class CausalLink:
    """因果链接"""
    cause_event_id: str
    effect_event_id: str
    confidence: float = 0.8
    mechanism: str = ""  # 因果机制描述


class InformationModel:
    """
    信息论模块

    管理信息的流动和因果关系，提供：
    - 事件流管理
    - 因果链追踪
    - 状态转移记录
    - 信息熵计算（系统可预测性）
    - 异常检测
    """

    def __init__(self, max_events: int = 2000):
        self.events: deque = deque(maxlen=max_events)
        self.causal_links: List[CausalLink] = []
        self._event_index: Dict[str, int] = {}
        self._entity_events: Dict[str, List[str]] = defaultdict(list)
        self._state_transitions: Dict[str, List[Dict]] = defaultdict(list)  # entity → transitions
        self._event_type_counts: Dict[str, int] = defaultdict(int)
        self._subscribers: Dict[str, List] = defaultdict(list)

    def record_event(self, event: Event):
        """记录事件"""
        self.events.append(event)
        self._event_index[event.id] = len(self.events) - 1
        self._event_type_counts[event.type] += 1
        if event.entity_id:
            self._entity_events[event.entity_id].append(event.id)

        # 因果链
        if event.cause_event_id:
            self.causal_links.append(CausalLink(
                cause_event_id=event.cause_event_id,
                effect_event_id=event.id,
            ))

        # 通知订阅者
        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"事件订阅回调异常: {e}")

    def subscribe(self, event_type: str, callback):
        """订阅事件类型"""
        self._subscribers[event_type].append(callback)

    def record_state_transition(self, entity_id: str,
                                old_state: str, new_state: str,
                                trigger: str = ""):
        """记录状态转移"""
        transition = {
            "from": old_state,
            "to": new_state,
            "trigger": trigger,
            "timestamp": time.time(),
        }
        self._state_transitions[entity_id].append(transition)

        # 同时记录为事件
        self.record_event(Event(
            id=f"evt_{int(time.time() * 1000)}",
            type="state_transition",
            entity_id=entity_id,
            timestamp=time.time(),
            data=transition,
        ))

    def get_causal_chain(self, event_id: str, depth: int = 5) -> List[str]:
        """追踪因果链"""
        chain = [event_id]
        current = event_id

        for _ in range(depth):
            # 找到触发当前事件的原因
            cause_links = [l for l in self.causal_links if l.effect_event_id == current]
            if not cause_links:
                break
            current = cause_links[0].cause_event_id
            chain.insert(0, current)

        return chain

    def get_effects(self, event_id: str) -> List[str]:
        """获取一个事件引发的所有后续事件"""
        return [l.effect_event_id for l in self.causal_links
                if l.cause_event_id == event_id]

    def compute_entropy(self, entity_id: Optional[str] = None,
                        window: int = 100) -> float:
        """
        计算信息熵（系统不确定性/混乱度）

        熵越高 → 系统越不可预测
        熵越低 → 系统越稳定
        """
        if entity_id:
            event_ids = self._entity_events.get(entity_id, [])
            relevant_events = []
            for eid in event_ids[-window:]:
                idx = self._event_index.get(eid)
                if idx is not None and idx < len(self.events):
                    relevant_events.append(self.events[idx])
        else:
            relevant_events = list(self.events)[-window:]

        if not relevant_events:
            return 0.0

        # 按事件类型计算分布
        type_counts: Dict[str, int] = defaultdict(int)
        for e in relevant_events:
            type_counts[e.type] += 1

        total = len(relevant_events)
        entropy = 0.0
        for count in type_counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        return entropy

    def detect_anomalies(self, window: int = 50,
                         threshold: float = 2.0) -> List[Dict]:
        """
        异常检测

        检测事件频率异常和状态异常
        """
        anomalies = []
        recent = list(self.events)[-window:]
        if not recent:
            return anomalies

        # 计算事件类型频率
        type_counts: Dict[str, int] = defaultdict(int)
        for e in recent:
            type_counts[e.type] += 1

        avg_freq = len(recent) / max(len(type_counts), 1)
        for etype, count in type_counts.items():
            if count > avg_freq * threshold:
                anomalies.append({
                    "type": "frequency_spike",
                    "event_type": etype,
                    "count": count,
                    "expected": avg_freq,
                    "ratio": count / avg_freq,
                })

        # 检测状态快速翻转
        for entity_id, transitions in self._state_transitions.items():
            recent_trans = [t for t in transitions if time.time() - t["timestamp"] < 60]
            if len(recent_trans) > 5:
                anomalies.append({
                    "type": "state_flapping",
                    "entity_id": entity_id,
                    "transition_count": len(recent_trans),
                    "window_seconds": 60,
                })

        return anomalies

    def get_entity_timeline(self, entity_id: str,
                            limit: int = 20) -> List[Dict]:
        """获取实体的事件时间线"""
        event_ids = self._entity_events.get(entity_id, [])[-limit:]
        timeline = []
        for eid in event_ids:
            idx = self._event_index.get(eid)
            if idx is not None and idx < len(self.events):
                e = self.events[idx]
                timeline.append({
                    "id": e.id, "type": e.type,
                    "timestamp": e.timestamp, "data": e.data,
                })
        return timeline

    def get_summary(self) -> Dict:
        return {
            "total_events": len(self.events),
            "event_types": dict(self._event_type_counts),
            "causal_links": len(self.causal_links),
            "tracked_entities": len(self._entity_events),
            "entropy": round(self.compute_entropy(), 3),
        }


# ═══════════════════════════════════════════════════
# 三位一体世界模型（整合层）
# ═══════════════════════════════════════════════════

class WorldModel:
    """
    三位一体世界模型

    整合本体论 + 认知论 + 信息论，提供统一接口。
    """

    def __init__(self):
        self.ontology = Ontology()
        self.epistemology = Epistemology()
        self.information = InformationModel()
        logger.info("三位一体世界模型已初始化 (Ontology + Epistemology + Information)")

    # ─────── 兼容旧接口 ─────────

    @property
    def entities(self) -> Dict[str, Entity]:
        return self.ontology.entities

    @property
    def relationships(self) -> List[Relationship]:
        return self.ontology.relationships

    @property
    def events(self) -> deque:
        return self.information.events

    def register_entity(self, entity: Entity):
        """注册实体（同时更新三个模块）"""
        # 本体论：注册实体
        self.ontology.register_entity(entity)

        # 认知论：声明信念
        self.epistemology.assert_belief(
            subject=entity.id,
            predicate="exists",
            value=True,
            confidence=1.0,
            source="registration",
        )
        self.epistemology.assert_belief(
            subject=entity.id,
            predicate="state",
            value=entity.state.value,
            confidence=1.0,
            source="registration",
        )
        for key, val in entity.properties.items():
            self.epistemology.assert_belief(
                subject=entity.id,
                predicate=key,
                value=val,
                confidence=0.9,
                source="registration",
            )

        # 信息论：记录事件
        self.information.record_event(Event(
            id=f"evt_{int(time.time() * 1000)}_{entity.id}",
            type="entity_registered",
            entity_id=entity.id,
            timestamp=time.time(),
            data={"entity_type": entity.type.value, "name": entity.name},
        ))

    def update_entity_state(self, entity_id: str, new_state: EntityState,
                            trigger: str = ""):
        """更新实体状态（三模块协同）"""
        entity = self.ontology.get_entity(entity_id)
        if not entity:
            return

        old_state = entity.state
        entity.state = new_state
        entity.last_updated = time.time()

        # 认知论：更新信念
        self.epistemology.assert_belief(
            subject=entity_id,
            predicate="state",
            value=new_state.value,
            confidence=1.0,
            source="observation",
        )

        # 信息论：记录状态转移
        self.information.record_state_transition(
            entity_id, old_state.value, new_state.value, trigger
        )

        logger.info(f"实体状态更新: {entity_id} {old_state.value} → {new_state.value}")

    def add_relationship(self, relationship: Relationship):
        """添加关系"""
        self.ontology.add_relationship(relationship)
        self.information.record_event(Event(
            id=f"evt_{int(time.time() * 1000)}_rel",
            type="relationship_added",
            entity_id=None,
            timestamp=time.time(),
            data={
                "from": relationship.from_entity_id,
                "to": relationship.to_entity_id,
                "type": relationship.relation_type,
            },
        ))

    # ─────── 兼容旧查询接口 ─────────

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.ontology.get_entity(entity_id)

    def get_entities_by_type(self, entity_type: EntityType) -> List[Entity]:
        return self.ontology.get_entities_by_type(entity_type)

    def get_entities_by_state(self, state: EntityState) -> List[Entity]:
        return self.ontology.get_entities_by_state(state)

    def get_related_entities(self, entity_id: str,
                             relation_type: Optional[str] = None) -> List[Entity]:
        neighbors = self.ontology.get_neighbors(entity_id, relation_type)
        return [entity for entity, _ in neighbors]

    def get_available_resources(self) -> List[Entity]:
        return [
            e for e in self.ontology.entities.values()
            if e.type in [EntityType.NODE, EntityType.DEVICE, EntityType.SERVICE]
            and e.state in [EntityState.ACTIVE, EntityState.INACTIVE]
        ]

    # ─────── 三位一体高级查询 ─────────

    def query_state(self, query: str) -> Dict:
        """查询世界状态（整合三个模块）"""
        return {
            "ontology": {
                "total_entities": len(self.ontology.entities),
                "entities_by_type": self._count_by_type(),
                "entities_by_state": self._count_by_state(),
                "relationships": len(self.ontology.relationships),
            },
            "epistemology": self.epistemology.get_summary(),
            "information": self.information.get_summary(),
        }

    def predict_outcome(self, action: str, context: Dict) -> Dict:
        """
        预测动作结果（三模块协同推理）
        """
        # 1. 本体论：检查相关实体和资源
        available = self.get_available_resources()
        has_resources = len(available) > 0

        # 2. 认知论：查询相关信念的置信度
        related_confidence = 1.0
        entity_id = context.get("entity_id")
        if entity_id:
            beliefs = self.epistemology.query_belief(entity_id)
            if beliefs:
                related_confidence = sum(
                    b.current_confidence() for b in beliefs
                ) / len(beliefs)

        # 3. 信息论：基于历史事件统计
        similar_events = [
            e for e in self.information.events if e.type == action
        ]
        historical_success = 0.8
        if similar_events:
            success_count = sum(
                1 for e in similar_events if e.data.get("success", False)
            )
            historical_success = success_count / len(similar_events)

        # 综合预测
        base_prob = historical_success
        if not has_resources:
            base_prob *= 0.3
        adjusted_prob = base_prob * related_confidence

        # 信息熵影响
        entropy = self.information.compute_entropy(entity_id)
        if entropy > 3.0:
            adjusted_prob *= 0.8  # 高熵 = 高不确定性

        return {
            "success_probability": round(adjusted_prob, 3),
            "confidence": round(related_confidence, 3),
            "system_entropy": round(entropy, 3),
            "has_resources": has_resources,
            "historical_samples": len(similar_events),
            "anomalies": self.information.detect_anomalies(),
        }

    def simulate_action(self, action: str, parameters: Dict) -> Dict:
        """模拟动作执行"""
        available = self.get_available_resources()
        prediction = self.predict_outcome(action, parameters)

        feasible = prediction["success_probability"] > 0.3 and prediction["has_resources"]
        knowledge_gaps = self.epistemology.identify_knowledge_gaps(
            [e.id for e in available[:5]],
            ["state", "capabilities"],
        )

        return {
            "feasible": feasible,
            "prediction": prediction,
            "knowledge_gaps": knowledge_gaps,
            "constraint_violations": self.ontology.validate_constraints(),
            "recommendations": self._generate_recommendations(prediction, knowledge_gaps),
        }

    def _generate_recommendations(self, prediction: Dict,
                                  knowledge_gaps: List[Dict]) -> List[str]:
        recs = []
        if prediction["success_probability"] < 0.5:
            recs.append("成功概率较低，建议先收集更多信息")
        if knowledge_gaps:
            recs.append(f"存在 {len(knowledge_gaps)} 个知识缺口，建议先补充")
        if prediction["system_entropy"] > 3.0:
            recs.append("系统熵较高，建议等待系统稳定后再执行")
        return recs

    def _count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.ontology.entities.values():
            counts[e.type.value] = counts.get(e.type.value, 0) + 1
        return counts

    def _count_by_state(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.ontology.entities.values():
            counts[e.state.value] = counts.get(e.state.value, 0) + 1
        return counts

    def _record_event(self, event: Event):
        """兼容旧接口"""
        self.information.record_event(event)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    world = WorldModel()

    # 注册实体
    world.register_entity(Entity(
        id="device_android_001", type=EntityType.DEVICE,
        name="Android Phone", state=EntityState.ACTIVE,
        properties={"battery": 85, "connected": True},
    ))
    world.register_entity(Entity(
        id="node_43", type=EntityType.NODE,
        name="MAVLink Drone Controller", state=EntityState.ACTIVE,
        properties={"capabilities": ["drone_control", "telemetry"]},
    ))
    world.register_entity(Entity(
        id="node_49", type=EntityType.NODE,
        name="OctoPrint 3D Printer", state=EntityState.INACTIVE,
        properties={"capabilities": ["3d_printing"]},
    ))

    # 添加关系
    world.add_relationship(Relationship(
        from_entity_id="device_android_001",
        to_entity_id="node_43",
        relation_type="controls", properties={},
    ))

    # 更新状态
    world.update_entity_state("node_49", EntityState.BUSY)

    # 三位一体查询
    state = world.query_state("")
    print(f"\n世界状态:")
    print(json.dumps(state, indent=2, ensure_ascii=False, default=str))

    # 认知查询
    beliefs = world.epistemology.query_belief("device_android_001")
    print(f"\n关于 Android 手机的信念:")
    for b in beliefs:
        print(f"  {b.predicate} = {b.value} (置信度: {b.current_confidence():.2f})")

    # 预测
    prediction = world.predict_outcome("drone_takeoff", {"entity_id": "node_43"})
    print(f"\n预测结果: {json.dumps(prediction, indent=2, ensure_ascii=False, default=str)}")

    # 信息熵
    entropy = world.information.compute_entropy()
    print(f"\n系统信息熵: {entropy:.3f}")
