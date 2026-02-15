"""
Node 70 - AutonomousLearning (自主学习节点)
提供系统自主学习、经验积累和知识更新能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 70 - AutonomousLearning", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class LearningType(str, Enum):
    """学习类型"""
    SUPERVISED = "supervised"       # 监督学习
    UNSUPERVISED = "unsupervised"   # 无监督学习
    REINFORCEMENT = "reinforcement" # 强化学习
    TRANSFER = "transfer"           # 迁移学习
    INCREMENTAL = "incremental"     # 增量学习


class ExperienceType(str, Enum):
    """经验类型"""
    SUCCESS = "success"
    FAILURE = "failure"
    OBSERVATION = "observation"
    FEEDBACK = "feedback"


@dataclass
class Experience:
    """经验记录"""
    experience_id: str
    experience_type: ExperienceType
    context: Dict[str, Any]
    action: str
    outcome: Dict[str, Any]
    reward: float  # -1 到 1
    timestamp: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeItem:
    """知识条目"""
    knowledge_id: str
    category: str
    content: str
    confidence: float  # 0 到 1
    source: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    related_experiences: List[str] = field(default_factory=list)


@dataclass
class LearningSession:
    """学习会话"""
    session_id: str
    learning_type: LearningType
    objective: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    experiences_processed: int = 0
    knowledge_gained: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)
    is_active: bool = True


@dataclass
class Pattern:
    """学习到的模式"""
    pattern_id: str
    description: str
    conditions: List[str]
    predicted_outcome: str
    confidence: float
    occurrence_count: int = 1
    last_observed: datetime = field(default_factory=datetime.now)


class AutonomousLearningEngine:
    """自主学习引擎"""
    
    def __init__(self):
        self.experiences: Dict[str, Experience] = {}
        self.knowledge_base: Dict[str, KnowledgeItem] = {}
        self.patterns: Dict[str, Pattern] = {}
        self.sessions: Dict[str, LearningSession] = {}
        self.learning_rate: float = 0.1
        self.exploration_rate: float = 0.2
        self._experience_buffer: List[Experience] = []
        self._buffer_size = 1000
    
    def record_experience(self, experience_type: ExperienceType,
                          context: Dict[str, Any], action: str,
                          outcome: Dict[str, Any], reward: float,
                          tags: List[str] = None) -> str:
        """记录经验"""
        experience = Experience(
            experience_id=str(uuid.uuid4()),
            experience_type=experience_type,
            context=context,
            action=action,
            outcome=outcome,
            reward=max(-1, min(1, reward)),  # 限制在 [-1, 1]
            tags=tags or []
        )
        
        self.experiences[experience.experience_id] = experience
        self._experience_buffer.append(experience)
        
        # 限制缓冲区大小
        if len(self._experience_buffer) > self._buffer_size:
            self._experience_buffer = self._experience_buffer[-self._buffer_size:]
        
        logger.info(f"Recorded experience: {experience.experience_id} ({experience_type.value})")
        
        # 触发增量学习
        asyncio.create_task(self._incremental_learn(experience))
        
        return experience.experience_id
    
    async def _incremental_learn(self, experience: Experience):
        """增量学习"""
        # 提取模式
        pattern = self._extract_pattern(experience)
        if pattern:
            self._update_pattern(pattern)
        
        # 更新知识
        knowledge = self._extract_knowledge(experience)
        if knowledge:
            self._update_knowledge(knowledge)
    
    def _extract_pattern(self, experience: Experience) -> Optional[Pattern]:
        """从经验中提取模式"""
        # 简化的模式提取
        if experience.reward > 0.5:
            conditions = [f"{k}={v}" for k, v in list(experience.context.items())[:3]]
            return Pattern(
                pattern_id=hashlib.md5(str(conditions).encode()).hexdigest()[:12],
                description=f"Pattern from {experience.action}",
                conditions=conditions,
                predicted_outcome=str(experience.outcome.get("result", "success")),
                confidence=experience.reward
            )
        return None
    
    def _update_pattern(self, new_pattern: Pattern):
        """更新模式"""
        if new_pattern.pattern_id in self.patterns:
            existing = self.patterns[new_pattern.pattern_id]
            existing.occurrence_count += 1
            existing.confidence = (existing.confidence + new_pattern.confidence) / 2
            existing.last_observed = datetime.now()
        else:
            self.patterns[new_pattern.pattern_id] = new_pattern
    
    def _extract_knowledge(self, experience: Experience) -> Optional[KnowledgeItem]:
        """从经验中提取知识"""
        if experience.experience_type == ExperienceType.SUCCESS and experience.reward > 0.7:
            return KnowledgeItem(
                knowledge_id=str(uuid.uuid4()),
                category=experience.tags[0] if experience.tags else "general",
                content=f"Action '{experience.action}' leads to positive outcome in context: {list(experience.context.keys())}",
                confidence=experience.reward,
                source=f"experience:{experience.experience_id}",
                related_experiences=[experience.experience_id]
            )
        return None
    
    def _update_knowledge(self, knowledge: KnowledgeItem):
        """更新知识库"""
        # 检查是否有类似知识
        for existing in self.knowledge_base.values():
            if existing.category == knowledge.category and \
               self._similarity(existing.content, knowledge.content) > 0.8:
                # 更新现有知识
                existing.confidence = (existing.confidence + knowledge.confidence) / 2
                existing.updated_at = datetime.now()
                existing.related_experiences.extend(knowledge.related_experiences)
                return
        
        # 添加新知识
        self.knowledge_base[knowledge.knowledge_id] = knowledge
    
    def _similarity(self, text1: str, text2: str) -> float:
        """简单的文本相似度计算"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)
    
    async def start_learning_session(self, learning_type: LearningType,
                                     objective: str) -> str:
        """开始学习会话"""
        session = LearningSession(
            session_id=str(uuid.uuid4()),
            learning_type=learning_type,
            objective=objective
        )
        
        self.sessions[session.session_id] = session
        logger.info(f"Started learning session: {session.session_id}")
        
        # 根据学习类型执行学习
        if learning_type == LearningType.REINFORCEMENT:
            asyncio.create_task(self._reinforcement_learning(session))
        elif learning_type == LearningType.INCREMENTAL:
            asyncio.create_task(self._batch_incremental_learning(session))
        
        return session.session_id
    
    async def _reinforcement_learning(self, session: LearningSession):
        """强化学习"""
        try:
            # 处理经验缓冲区
            for experience in self._experience_buffer[-100:]:
                # 更新 Q 值（简化版）
                self._update_q_values(experience)
                session.experiences_processed += 1
            
            session.metrics["avg_reward"] = self._calculate_avg_reward()
            session.metrics["pattern_count"] = len(self.patterns)
            
        finally:
            session.is_active = False
            session.completed_at = datetime.now()
    
    async def _batch_incremental_learning(self, session: LearningSession):
        """批量增量学习"""
        try:
            for experience in self._experience_buffer:
                pattern = self._extract_pattern(experience)
                if pattern:
                    self._update_pattern(pattern)
                    session.knowledge_gained += 1
                session.experiences_processed += 1
            
            session.metrics["patterns_learned"] = session.knowledge_gained
            
        finally:
            session.is_active = False
            session.completed_at = datetime.now()
    
    def _update_q_values(self, experience: Experience):
        """更新 Q 值"""
        # 简化的 Q-learning 更新
        state_key = hashlib.md5(str(experience.context).encode()).hexdigest()[:8]
        action_key = experience.action
        
        # 这里应该有一个 Q 表，简化处理
        pass
    
    def _calculate_avg_reward(self) -> float:
        """计算平均奖励"""
        if not self._experience_buffer:
            return 0.0
        return sum(e.reward for e in self._experience_buffer) / len(self._experience_buffer)
    
    def query_knowledge(self, category: Optional[str] = None,
                        min_confidence: float = 0.0) -> List[KnowledgeItem]:
        """查询知识"""
        result = []
        for knowledge in self.knowledge_base.values():
            if category and knowledge.category != category:
                continue
            if knowledge.confidence < min_confidence:
                continue
            knowledge.access_count += 1
            result.append(knowledge)
        
        return sorted(result, key=lambda k: k.confidence, reverse=True)
    
    def predict_outcome(self, context: Dict[str, Any], action: str) -> Dict[str, Any]:
        """预测结果"""
        # 查找匹配的模式
        best_pattern = None
        best_match = 0.0
        
        context_str = str(context)
        
        for pattern in self.patterns.values():
            match_score = sum(1 for c in pattern.conditions if c in context_str) / len(pattern.conditions)
            if match_score > best_match:
                best_match = match_score
                best_pattern = pattern
        
        if best_pattern and best_match > 0.5:
            return {
                "predicted_outcome": best_pattern.predicted_outcome,
                "confidence": best_pattern.confidence * best_match,
                "pattern_id": best_pattern.pattern_id
            }
        
        return {
            "predicted_outcome": "unknown",
            "confidence": 0.0,
            "pattern_id": None
        }
    
    def get_learning_recommendations(self) -> List[Dict[str, Any]]:
        """获取学习建议"""
        recommendations = []
        
        # 基于低置信度知识
        low_confidence = [k for k in self.knowledge_base.values() if k.confidence < 0.5]
        if low_confidence:
            recommendations.append({
                "type": "strengthen_knowledge",
                "description": f"有 {len(low_confidence)} 条知识需要加强",
                "priority": "high"
            })
        
        # 基于失败经验
        failures = [e for e in self.experiences.values() if e.experience_type == ExperienceType.FAILURE]
        if len(failures) > 10:
            recommendations.append({
                "type": "analyze_failures",
                "description": f"有 {len(failures)} 条失败经验需要分析",
                "priority": "medium"
            })
        
        # 基于探索率
        if self.exploration_rate < 0.1:
            recommendations.append({
                "type": "increase_exploration",
                "description": "探索率过低，建议增加探索",
                "priority": "low"
            })
        
        return recommendations
    
    def get_status(self) -> Dict[str, Any]:
        """获取学习引擎状态"""
        return {
            "total_experiences": len(self.experiences),
            "knowledge_items": len(self.knowledge_base),
            "patterns_learned": len(self.patterns),
            "active_sessions": sum(1 for s in self.sessions.values() if s.is_active),
            "learning_rate": self.learning_rate,
            "exploration_rate": self.exploration_rate,
            "avg_reward": self._calculate_avg_reward(),
            "buffer_size": len(self._experience_buffer)
        }


# 全局实例
learning_engine = AutonomousLearningEngine()


# API 模型
class RecordExperienceRequest(BaseModel):
    experience_type: str
    context: Dict[str, Any]
    action: str
    outcome: Dict[str, Any]
    reward: float
    tags: List[str] = []

class StartSessionRequest(BaseModel):
    learning_type: str
    objective: str

class PredictRequest(BaseModel):
    context: Dict[str, Any]
    action: str


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_70_AutonomousLearning"}

@app.get("/status")
async def get_status():
    return learning_engine.get_status()

@app.post("/experiences")
async def record_experience(request: RecordExperienceRequest):
    experience_id = learning_engine.record_experience(
        ExperienceType(request.experience_type),
        request.context,
        request.action,
        request.outcome,
        request.reward,
        request.tags
    )
    return {"experience_id": experience_id}

@app.get("/experiences")
async def list_experiences(experience_type: Optional[str] = None, limit: int = 50):
    experiences = list(learning_engine.experiences.values())
    if experience_type:
        experiences = [e for e in experiences if e.experience_type.value == experience_type]
    experiences = sorted(experiences, key=lambda e: e.timestamp, reverse=True)[:limit]
    return [asdict(e) for e in experiences]

@app.post("/sessions")
async def start_session(request: StartSessionRequest):
    session_id = await learning_engine.start_learning_session(
        LearningType(request.learning_type),
        request.objective
    )
    return {"session_id": session_id}

@app.get("/sessions")
async def list_sessions():
    return [asdict(s) for s in learning_engine.sessions.values()]

@app.get("/knowledge")
async def query_knowledge(category: Optional[str] = None, min_confidence: float = 0.0):
    knowledge = learning_engine.query_knowledge(category, min_confidence)
    return [asdict(k) for k in knowledge]

@app.get("/patterns")
async def list_patterns():
    return [asdict(p) for p in learning_engine.patterns.values()]

@app.post("/predict")
async def predict_outcome(request: PredictRequest):
    return learning_engine.predict_outcome(request.context, request.action)

@app.get("/recommendations")
async def get_recommendations():
    return learning_engine.get_learning_recommendations()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8070)
