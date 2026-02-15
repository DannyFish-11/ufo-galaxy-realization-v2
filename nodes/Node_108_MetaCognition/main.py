"""
Node 108 - MetaCognition (元认知节点)
提供系统级的自我认知、反思和优化能力
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 108 - MetaCognition", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class CognitionLevel(str, Enum):
    """认知层级"""
    PERCEPTION = "perception"      # 感知层
    COMPREHENSION = "comprehension"  # 理解层
    PROJECTION = "projection"      # 预测层
    REFLECTION = "reflection"      # 反思层
    ADAPTATION = "adaptation"      # 适应层


class PerformanceMetric(str, Enum):
    """性能指标"""
    SUCCESS_RATE = "success_rate"
    RESPONSE_TIME = "response_time"
    RESOURCE_USAGE = "resource_usage"
    ERROR_RATE = "error_rate"
    LEARNING_PROGRESS = "learning_progress"


@dataclass
class CognitiveState:
    """认知状态"""
    level: CognitionLevel
    confidence: float
    attention_focus: List[str]
    working_memory: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SelfAssessment:
    """自我评估"""
    task_id: str
    performance_score: float
    strengths: List[str]
    weaknesses: List[str]
    improvement_suggestions: List[str]
    metrics: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ReflectionRecord:
    """反思记录"""
    reflection_id: str
    trigger: str
    observations: List[str]
    insights: List[str]
    action_items: List[str]
    outcome: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class MetaCognitionEngine:
    """元认知引擎"""
    
    def __init__(self):
        self.cognitive_state = CognitiveState(
            level=CognitionLevel.PERCEPTION,
            confidence=0.5,
            attention_focus=[],
            working_memory={}
        )
        self.assessments: List[SelfAssessment] = []
        self.reflections: List[ReflectionRecord] = []
        self.performance_history: Dict[str, List[float]] = {}
        self.learning_goals: List[Dict[str, Any]] = []
        self.meta_knowledge: Dict[str, Any] = {}
        
    async def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """感知层 - 收集和处理输入信息"""
        perception = {
            "raw_input": input_data,
            "input_type": self._classify_input(input_data),
            "relevance_score": self._assess_relevance(input_data),
            "attention_required": self._determine_attention(input_data),
            "timestamp": datetime.now().isoformat()
        }
        
        # 更新工作记忆
        self.cognitive_state.working_memory["last_perception"] = perception
        self.cognitive_state.level = CognitionLevel.PERCEPTION
        
        return perception
    
    async def comprehend(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """理解层 - 分析和理解感知到的信息"""
        comprehension = {
            "perception_id": perception.get("timestamp"),
            "meaning": self._extract_meaning(perception),
            "context": self._build_context(perception),
            "relationships": self._identify_relationships(perception),
            "confidence": self._calculate_confidence(perception)
        }
        
        self.cognitive_state.level = CognitionLevel.COMPREHENSION
        self.cognitive_state.confidence = comprehension["confidence"]
        
        return comprehension
    
    async def project(self, comprehension: Dict[str, Any]) -> Dict[str, Any]:
        """预测层 - 基于理解进行预测"""
        projection = {
            "comprehension_id": comprehension.get("perception_id"),
            "predictions": self._generate_predictions(comprehension),
            "scenarios": self._create_scenarios(comprehension),
            "risks": self._assess_risks(comprehension),
            "opportunities": self._identify_opportunities(comprehension)
        }
        
        self.cognitive_state.level = CognitionLevel.PROJECTION
        
        return projection
    
    async def reflect(self, task_id: str, outcome: Dict[str, Any]) -> ReflectionRecord:
        """反思层 - 对执行结果进行反思"""
        observations = self._gather_observations(outcome)
        insights = self._derive_insights(observations)
        action_items = self._generate_action_items(insights)
        
        reflection = ReflectionRecord(
            reflection_id=f"ref_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            trigger=task_id,
            observations=observations,
            insights=insights,
            action_items=action_items,
            outcome=json.dumps(outcome) if outcome else None
        )
        
        self.reflections.append(reflection)
        self.cognitive_state.level = CognitionLevel.REFLECTION
        
        # 更新元知识
        self._update_meta_knowledge(reflection)
        
        return reflection
    
    async def adapt(self, reflection: ReflectionRecord) -> Dict[str, Any]:
        """适应层 - 基于反思进行自我调整"""
        adaptations = {
            "reflection_id": reflection.reflection_id,
            "strategy_adjustments": self._adjust_strategies(reflection),
            "parameter_updates": self._update_parameters(reflection),
            "new_capabilities": self._identify_new_capabilities(reflection),
            "deprecated_approaches": self._identify_deprecated(reflection)
        }
        
        self.cognitive_state.level = CognitionLevel.ADAPTATION
        
        # 应用适应
        await self._apply_adaptations(adaptations)
        
        return adaptations
    
    async def self_assess(self, task_id: str, metrics: Dict[str, float]) -> SelfAssessment:
        """自我评估"""
        # 计算综合性能分数
        performance_score = self._calculate_performance_score(metrics)
        
        # 分析优势和劣势
        strengths = self._identify_strengths(metrics)
        weaknesses = self._identify_weaknesses(metrics)
        
        # 生成改进建议
        suggestions = self._generate_improvement_suggestions(weaknesses)
        
        assessment = SelfAssessment(
            task_id=task_id,
            performance_score=performance_score,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_suggestions=suggestions,
            metrics=metrics
        )
        
        self.assessments.append(assessment)
        
        # 更新性能历史
        for metric_name, value in metrics.items():
            if metric_name not in self.performance_history:
                self.performance_history[metric_name] = []
            self.performance_history[metric_name].append(value)
        
        return assessment
    
    def get_cognitive_state(self) -> Dict[str, Any]:
        """获取当前认知状态"""
        return {
            "level": self.cognitive_state.level.value,
            "confidence": self.cognitive_state.confidence,
            "attention_focus": self.cognitive_state.attention_focus,
            "working_memory_size": len(self.cognitive_state.working_memory),
            "timestamp": self.cognitive_state.timestamp.isoformat()
        }
    
    def get_performance_trend(self, metric: str, window: int = 10) -> Dict[str, Any]:
        """获取性能趋势"""
        if metric not in self.performance_history:
            return {"metric": metric, "trend": "unknown", "data": []}
        
        history = self.performance_history[metric][-window:]
        if len(history) < 2:
            return {"metric": metric, "trend": "insufficient_data", "data": history}
        
        # 计算趋势
        avg_first_half = sum(history[:len(history)//2]) / (len(history)//2)
        avg_second_half = sum(history[len(history)//2:]) / (len(history) - len(history)//2)
        
        if avg_second_half > avg_first_half * 1.05:
            trend = "improving"
        elif avg_second_half < avg_first_half * 0.95:
            trend = "declining"
        else:
            trend = "stable"
        
        return {
            "metric": metric,
            "trend": trend,
            "current_value": history[-1] if history else 0,
            "average": sum(history) / len(history),
            "data": history
        }
    
    # 私有辅助方法
    def _classify_input(self, data: Dict) -> str:
        if "error" in str(data).lower():
            return "error_signal"
        elif "task" in data:
            return "task_input"
        elif "feedback" in data:
            return "feedback"
        return "general"
    
    def _assess_relevance(self, data: Dict) -> float:
        # 简化的相关性评估
        keywords = ["urgent", "important", "critical", "error", "success"]
        text = str(data).lower()
        score = sum(1 for k in keywords if k in text) / len(keywords)
        return min(1.0, score + 0.3)
    
    def _determine_attention(self, data: Dict) -> bool:
        relevance = self._assess_relevance(data)
        return relevance > 0.5
    
    def _extract_meaning(self, perception: Dict) -> str:
        input_type = perception.get("input_type", "unknown")
        return f"Processed {input_type} input with relevance {perception.get('relevance_score', 0):.2f}"
    
    def _build_context(self, perception: Dict) -> Dict:
        return {
            "previous_state": self.cognitive_state.level.value,
            "working_memory_keys": list(self.cognitive_state.working_memory.keys()),
            "attention_focus": self.cognitive_state.attention_focus
        }
    
    def _identify_relationships(self, perception: Dict) -> List[str]:
        return ["input_to_state", "state_to_action"]
    
    def _calculate_confidence(self, perception: Dict) -> float:
        base_confidence = perception.get("relevance_score", 0.5)
        history_factor = min(1.0, len(self.assessments) / 10)
        return (base_confidence + history_factor) / 2
    
    def _generate_predictions(self, comprehension: Dict) -> List[Dict]:
        return [
            {"prediction": "task_success", "probability": comprehension.get("confidence", 0.5)},
            {"prediction": "resource_sufficient", "probability": 0.8}
        ]
    
    def _create_scenarios(self, comprehension: Dict) -> List[Dict]:
        return [
            {"scenario": "optimal", "likelihood": 0.3},
            {"scenario": "nominal", "likelihood": 0.5},
            {"scenario": "degraded", "likelihood": 0.2}
        ]
    
    def _assess_risks(self, comprehension: Dict) -> List[str]:
        risks = []
        if comprehension.get("confidence", 1.0) < 0.5:
            risks.append("low_confidence_decision")
        return risks
    
    def _identify_opportunities(self, comprehension: Dict) -> List[str]:
        return ["learning_opportunity", "optimization_potential"]
    
    def _gather_observations(self, outcome: Dict) -> List[str]:
        observations = []
        if outcome.get("success"):
            observations.append("Task completed successfully")
        else:
            observations.append("Task encountered issues")
        if outcome.get("duration"):
            observations.append(f"Execution took {outcome['duration']}s")
        return observations
    
    def _derive_insights(self, observations: List[str]) -> List[str]:
        insights = []
        for obs in observations:
            if "successfully" in obs:
                insights.append("Current approach is effective")
            elif "issues" in obs:
                insights.append("Need to investigate failure patterns")
        return insights
    
    def _generate_action_items(self, insights: List[str]) -> List[str]:
        actions = []
        for insight in insights:
            if "effective" in insight:
                actions.append("Document successful pattern")
            elif "investigate" in insight:
                actions.append("Analyze error logs")
        return actions
    
    def _update_meta_knowledge(self, reflection: ReflectionRecord):
        self.meta_knowledge["last_reflection"] = reflection.reflection_id
        self.meta_knowledge["total_reflections"] = len(self.reflections)
        self.meta_knowledge["insights_count"] = sum(len(r.insights) for r in self.reflections)
    
    def _adjust_strategies(self, reflection: ReflectionRecord) -> List[str]:
        adjustments = []
        for insight in reflection.insights:
            if "effective" in insight:
                adjustments.append("reinforce_current_strategy")
            elif "investigate" in insight:
                adjustments.append("explore_alternatives")
        return adjustments
    
    def _update_parameters(self, reflection: ReflectionRecord) -> Dict[str, Any]:
        return {
            "confidence_threshold": 0.6,
            "attention_decay": 0.9
        }
    
    def _identify_new_capabilities(self, reflection: ReflectionRecord) -> List[str]:
        return []
    
    def _identify_deprecated(self, reflection: ReflectionRecord) -> List[str]:
        return []
    
    async def _apply_adaptations(self, adaptations: Dict):
        # 应用参数更新
        params = adaptations.get("parameter_updates", {})
        if "confidence_threshold" in params:
            self.cognitive_state.confidence = max(
                self.cognitive_state.confidence,
                params["confidence_threshold"]
            )
    
    def _calculate_performance_score(self, metrics: Dict[str, float]) -> float:
        if not metrics:
            return 0.5
        weights = {
            "success_rate": 0.4,
            "response_time": 0.2,
            "resource_usage": 0.2,
            "error_rate": 0.2
        }
        score = 0.0
        total_weight = 0.0
        for metric, value in metrics.items():
            weight = weights.get(metric, 0.1)
            if metric == "error_rate":
                score += weight * (1 - value)
            elif metric == "response_time":
                score += weight * max(0, 1 - value / 10)
            else:
                score += weight * value
            total_weight += weight
        return score / total_weight if total_weight > 0 else 0.5
    
    def _identify_strengths(self, metrics: Dict[str, float]) -> List[str]:
        strengths = []
        if metrics.get("success_rate", 0) > 0.8:
            strengths.append("High task success rate")
        if metrics.get("response_time", 10) < 2:
            strengths.append("Fast response time")
        return strengths if strengths else ["Consistent performance"]
    
    def _identify_weaknesses(self, metrics: Dict[str, float]) -> List[str]:
        weaknesses = []
        if metrics.get("success_rate", 1) < 0.6:
            weaknesses.append("Low task success rate")
        if metrics.get("error_rate", 0) > 0.2:
            weaknesses.append("High error rate")
        return weaknesses if weaknesses else ["No significant weaknesses identified"]
    
    def _generate_improvement_suggestions(self, weaknesses: List[str]) -> List[str]:
        suggestions = []
        for weakness in weaknesses:
            if "success rate" in weakness.lower():
                suggestions.append("Review and optimize task execution strategies")
            elif "error rate" in weakness.lower():
                suggestions.append("Implement better error handling and recovery")
        return suggestions if suggestions else ["Continue monitoring performance"]


# 全局实例
metacognition_engine = MetaCognitionEngine()


# API 模型
class PerceiveRequest(BaseModel):
    input_data: Dict[str, Any]

class AssessRequest(BaseModel):
    task_id: str
    metrics: Dict[str, float]

class ReflectRequest(BaseModel):
    task_id: str
    outcome: Dict[str, Any]


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_108_MetaCognition"}

@app.get("/state")
async def get_state():
    return metacognition_engine.get_cognitive_state()

@app.post("/perceive")
async def perceive(request: PerceiveRequest):
    result = await metacognition_engine.perceive(request.input_data)
    return result

@app.post("/assess")
async def assess(request: AssessRequest):
    assessment = await metacognition_engine.self_assess(request.task_id, request.metrics)
    return asdict(assessment)

@app.post("/reflect")
async def reflect(request: ReflectRequest):
    reflection = await metacognition_engine.reflect(request.task_id, request.outcome)
    return asdict(reflection)

@app.get("/trend/{metric}")
async def get_trend(metric: str, window: int = 10):
    return metacognition_engine.get_performance_trend(metric, window)

@app.get("/assessments")
async def get_assessments(limit: int = 10):
    assessments = metacognition_engine.assessments[-limit:]
    return [asdict(a) for a in assessments]

@app.get("/reflections")
async def get_reflections(limit: int = 10):
    reflections = metacognition_engine.reflections[-limit:]
    return [asdict(r) for r in reflections]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8108)
