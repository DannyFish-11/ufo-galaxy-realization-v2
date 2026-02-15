"""
MetaCognition Engine - 元认知引擎核心模块

功能：
1. 思维过程追踪与分析
2. 决策质量评估
3. 策略优化建议
4. 认知偏差检测
"""

import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum


class ThoughtType(Enum):
    """思维类型枚举"""
    PERCEPTION = "perception"  # 感知
    ANALYSIS = "analysis"      # 分析
    DECISION = "decision"      # 决策
    ACTION = "action"          # 行动
    REFLECTION = "reflection"  # 反思


class CognitiveBias(Enum):
    """认知偏差类型"""
    CONFIRMATION_BIAS = "confirmation_bias"  # 确认偏差
    ANCHORING_BIAS = "anchoring_bias"        # 锚定偏差
    AVAILABILITY_BIAS = "availability_bias"  # 可得性偏差
    SUNK_COST_FALLACY = "sunk_cost_fallacy"  # 沉没成本谬误
    OVERCONFIDENCE = "overconfidence"        # 过度自信


class ThoughtRecord:
    """思维记录"""
    
    def __init__(
        self,
        thought_id: str,
        thought_type: ThoughtType,
        content: str,
        context: Dict[str, Any],
        timestamp: Optional[float] = None
    ):
        self.thought_id = thought_id
        self.thought_type = thought_type
        self.content = content
        self.context = context
        self.timestamp = timestamp or time.time()
        self.quality_score = None
        self.biases_detected = []
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "thought_id": self.thought_id,
            "thought_type": self.thought_type.value,
            "content": self.content,
            "context": self.context,
            "timestamp": self.timestamp,
            "quality_score": self.quality_score,
            "biases_detected": [b.value for b in self.biases_detected]
        }


class DecisionRecord:
    """决策记录"""
    
    def __init__(
        self,
        decision_id: str,
        decision_content: str,
        alternatives: List[str],
        reasoning: str,
        confidence: float,
        timestamp: Optional[float] = None
    ):
        self.decision_id = decision_id
        self.decision_content = decision_content
        self.alternatives = alternatives
        self.reasoning = reasoning
        self.confidence = confidence
        self.timestamp = timestamp or time.time()
        self.outcome = None
        self.quality_evaluation = None
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "decision_id": self.decision_id,
            "decision_content": self.decision_content,
            "alternatives": self.alternatives,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "quality_evaluation": self.quality_evaluation
        }


class MetaCognitionEngine:
    """元认知引擎"""
    
    def __init__(self, llm_client=None):
        """
        初始化元认知引擎
        
        Args:
            llm_client: LLM 客户端（用于调用 Node_01_OneAPI）
        """
        self.llm_client = llm_client
        self.thought_history: List[ThoughtRecord] = []
        self.decision_history: List[DecisionRecord] = []
        self.cognitive_state = {
            "total_thoughts": 0,
            "total_decisions": 0,
            "average_decision_quality": 0.0,
            "detected_biases": {},
            "last_reflection": None
        }
        
    def track_thought(
        self,
        thought_type: ThoughtType,
        content: str,
        context: Dict[str, Any]
    ) -> ThoughtRecord:
        """
        追踪思维过程
        
        Args:
            thought_type: 思维类型
            content: 思维内容
            context: 上下文信息
            
        Returns:
            ThoughtRecord: 思维记录
        """
        thought_id = f"thought_{int(time.time() * 1000)}"
        thought = ThoughtRecord(
            thought_id=thought_id,
            thought_type=thought_type,
            content=content,
            context=context
        )
        
        # 分析思维质量
        thought.quality_score = self._evaluate_thought_quality(thought)
        
        # 检测认知偏差
        thought.biases_detected = self._detect_biases(thought)
        
        # 记录到历史
        self.thought_history.append(thought)
        self.cognitive_state["total_thoughts"] += 1
        
        # 更新偏差统计
        for bias in thought.biases_detected:
            bias_key = bias.value
            self.cognitive_state["detected_biases"][bias_key] = \
                self.cognitive_state["detected_biases"].get(bias_key, 0) + 1
        
        return thought
    
    def track_decision(
        self,
        decision_content: str,
        alternatives: List[str],
        reasoning: str,
        confidence: float
    ) -> DecisionRecord:
        """
        追踪决策过程
        
        Args:
            decision_content: 决策内容
            alternatives: 备选方案
            reasoning: 推理过程
            confidence: 置信度（0-1）
            
        Returns:
            DecisionRecord: 决策记录
        """
        decision_id = f"decision_{int(time.time() * 1000)}"
        decision = DecisionRecord(
            decision_id=decision_id,
            decision_content=decision_content,
            alternatives=alternatives,
            reasoning=reasoning,
            confidence=confidence
        )
        
        # 记录到历史
        self.decision_history.append(decision)
        self.cognitive_state["total_decisions"] += 1
        
        return decision
    
    def evaluate_decision(
        self,
        decision_id: str,
        outcome: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        评估决策质量
        
        Args:
            decision_id: 决策ID
            outcome: 决策结果
            
        Returns:
            Dict: 评估结果
        """
        # 查找决策记录
        decision = None
        for d in self.decision_history:
            if d.decision_id == decision_id:
                decision = d
                break
        
        if not decision:
            return {"error": f"Decision {decision_id} not found"}
        
        # 记录结果
        decision.outcome = outcome
        
        # 评估质量
        evaluation = self._evaluate_decision_quality(decision)
        decision.quality_evaluation = evaluation
        
        # 更新平均质量
        self._update_average_quality()
        
        return evaluation
    
    def reflect(self, time_window: Optional[int] = None) -> Dict[str, Any]:
        """
        反思最近的思维和决策过程
        
        Args:
            time_window: 时间窗口（秒），None 表示所有历史
            
        Returns:
            Dict: 反思结果
        """
        current_time = time.time()
        
        # 筛选时间窗口内的记录
        if time_window:
            recent_thoughts = [
                t for t in self.thought_history
                if current_time - t.timestamp <= time_window
            ]
            recent_decisions = [
                d for d in self.decision_history
                if current_time - d.timestamp <= time_window
            ]
        else:
            recent_thoughts = self.thought_history
            recent_decisions = self.decision_history
        
        # 分析思维模式
        thought_patterns = self._analyze_thought_patterns(recent_thoughts)
        
        # 分析决策模式
        decision_patterns = self._analyze_decision_patterns(recent_decisions)
        
        # 识别改进机会
        improvement_opportunities = self._identify_improvements(
            thought_patterns, decision_patterns
        )
        
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "time_window": time_window,
            "thought_patterns": thought_patterns,
            "decision_patterns": decision_patterns,
            "improvement_opportunities": improvement_opportunities,
            "cognitive_state": self.cognitive_state.copy()
        }
        
        self.cognitive_state["last_reflection"] = reflection
        
        return reflection
    
    def optimize_strategy(
        self,
        task_description: str,
        current_strategy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        优化策略
        
        Args:
            task_description: 任务描述
            current_strategy: 当前策略
            
        Returns:
            Dict: 优化建议
        """
        # 基于历史经验分析当前策略
        strategy_analysis = self._analyze_strategy(
            task_description, current_strategy
        )
        
        # 生成优化建议
        optimization = {
            "original_strategy": current_strategy,
            "analysis": strategy_analysis,
            "recommended_changes": [],
            "expected_improvements": []
        }
        
        # 基于认知偏差检测结果
        if self.cognitive_state["detected_biases"]:
            optimization["recommended_changes"].append({
                "type": "bias_mitigation",
                "description": "引入偏差缓解机制",
                "details": self._generate_bias_mitigation_suggestions()
            })
        
        # 基于决策质量
        avg_quality = self.cognitive_state["average_decision_quality"]
        if avg_quality < 0.7:
            optimization["recommended_changes"].append({
                "type": "decision_process",
                "description": "改进决策流程",
                "details": self._generate_decision_improvement_suggestions()
            })
        
        return optimization
    
    def get_cognitive_state(self) -> Dict[str, Any]:
        """获取当前认知状态"""
        return self.cognitive_state.copy()
    
    # ========== 私有方法 ==========
    
    def _evaluate_thought_quality(self, thought: ThoughtRecord) -> float:
        """评估思维质量（0-1）"""
        # 简化实现：基于内容长度和上下文丰富度
        content_score = min(len(thought.content) / 200, 1.0)
        context_score = min(len(thought.context) / 5, 1.0)
        return (content_score + context_score) / 2
    
    def _detect_biases(self, thought: ThoughtRecord) -> List[CognitiveBias]:
        """检测认知偏差"""
        detected = []
        
        content_lower = thought.content.lower()
        
        # 确认偏差：寻找支持性证据的倾向
        if any(word in content_lower for word in ["证实", "验证", "支持"]):
            detected.append(CognitiveBias.CONFIRMATION_BIAS)
        
        # 锚定偏差：过度依赖初始信息
        if "第一" in content_lower or "初始" in content_lower:
            detected.append(CognitiveBias.ANCHORING_BIAS)
        
        # 过度自信
        if any(word in content_lower for word in ["肯定", "必然", "一定", "绝对"]):
            detected.append(CognitiveBias.OVERCONFIDENCE)
        
        return detected
    
    def _evaluate_decision_quality(self, decision: DecisionRecord) -> Dict[str, Any]:
        """评估决策质量"""
        outcome = decision.outcome or {}
        
        # 简化评估：基于结果成功度和置信度匹配度
        success_score = outcome.get("success_score", 0.5)
        confidence_match = 1.0 - abs(success_score - decision.confidence)
        
        overall_quality = (success_score + confidence_match) / 2
        
        return {
            "overall_quality": overall_quality,
            "success_score": success_score,
            "confidence_match": confidence_match,
            "reasoning_quality": self._evaluate_reasoning(decision.reasoning)
        }
    
    def _evaluate_reasoning(self, reasoning: str) -> float:
        """评估推理质量"""
        # 简化实现：基于推理的详细程度
        return min(len(reasoning) / 300, 1.0)
    
    def _update_average_quality(self):
        """更新平均决策质量"""
        evaluated_decisions = [
            d for d in self.decision_history
            if d.quality_evaluation is not None
        ]
        
        if evaluated_decisions:
            total_quality = sum(
                d.quality_evaluation["overall_quality"]
                for d in evaluated_decisions
            )
            self.cognitive_state["average_decision_quality"] = \
                total_quality / len(evaluated_decisions)
    
    def _analyze_thought_patterns(
        self, thoughts: List[ThoughtRecord]
    ) -> Dict[str, Any]:
        """分析思维模式"""
        if not thoughts:
            return {"message": "No thoughts to analyze"}
        
        # 统计思维类型分布
        type_distribution = {}
        for thought in thoughts:
            type_key = thought.thought_type.value
            type_distribution[type_key] = type_distribution.get(type_key, 0) + 1
        
        # 平均质量
        avg_quality = sum(t.quality_score for t in thoughts) / len(thoughts)
        
        return {
            "total_thoughts": len(thoughts),
            "type_distribution": type_distribution,
            "average_quality": avg_quality
        }
    
    def _analyze_decision_patterns(
        self, decisions: List[DecisionRecord]
    ) -> Dict[str, Any]:
        """分析决策模式"""
        if not decisions:
            return {"message": "No decisions to analyze"}
        
        # 平均置信度
        avg_confidence = sum(d.confidence for d in decisions) / len(decisions)
        
        # 平均备选方案数
        avg_alternatives = sum(
            len(d.alternatives) for d in decisions
        ) / len(decisions)
        
        return {
            "total_decisions": len(decisions),
            "average_confidence": avg_confidence,
            "average_alternatives": avg_alternatives
        }
    
    def _identify_improvements(
        self,
        thought_patterns: Dict[str, Any],
        decision_patterns: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """识别改进机会"""
        improvements = []
        
        # 检查思维质量
        if thought_patterns.get("average_quality", 1.0) < 0.6:
            improvements.append({
                "area": "thought_quality",
                "suggestion": "提高思维过程的深度和上下文丰富度"
            })
        
        # 检查决策置信度
        if decision_patterns.get("average_confidence", 1.0) > 0.9:
            improvements.append({
                "area": "overconfidence",
                "suggestion": "警惕过度自信，增加对不确定性的考虑"
            })
        
        # 检查备选方案
        if decision_patterns.get("average_alternatives", 3) < 2:
            improvements.append({
                "area": "alternatives",
                "suggestion": "在决策前考虑更多备选方案"
            })
        
        return improvements
    
    def _analyze_strategy(
        self,
        task_description: str,
        current_strategy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """分析策略"""
        return {
            "task": task_description,
            "strategy_complexity": len(current_strategy),
            "historical_performance": self.cognitive_state["average_decision_quality"]
        }
    
    def _generate_bias_mitigation_suggestions(self) -> List[str]:
        """生成偏差缓解建议"""
        suggestions = []
        
        for bias, count in self.cognitive_state["detected_biases"].items():
            if bias == "confirmation_bias":
                suggestions.append("主动寻找反驳性证据")
            elif bias == "anchoring_bias":
                suggestions.append("考虑多个不同的起始点")
            elif bias == "overconfidence":
                suggestions.append("量化不确定性，使用概率思维")
        
        return suggestions
    
    def _generate_decision_improvement_suggestions(self) -> List[str]:
        """生成决策改进建议"""
        return [
            "增加决策前的信息收集时间",
            "使用结构化决策框架（如决策树）",
            "引入外部视角或第二意见",
            "记录决策假设并定期验证"
        ]
