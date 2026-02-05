"""
学习优化器 (Learning Optimizer)
负责从执行结果中学习并优化系统性能
"""

import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class OptimizationStrategy(Enum):
    """优化策略"""
    INCREASE_RESOURCES = "increase_resources"
    DECREASE_RESOURCES = "decrease_resources"
    CHANGE_APPROACH = "change_approach"
    ADD_FALLBACK = "add_fallback"
    IMPROVE_TIMING = "improve_timing"
    ENHANCE_SAFETY = "enhance_safety"


@dataclass
class LearningRecord:
    """学习记录"""
    timestamp: float
    goal: str
    success: bool
    duration: float
    actions_count: int
    success_rate: float
    resource_utilization: float = 0.0
    user_satisfaction: float = 0.0
    metadata: Dict = field(default_factory=dict)


@dataclass
class OptimizationInsight:
    """优化洞察"""
    insight_id: str
    category: str
    description: str
    strategy: OptimizationStrategy
    priority: int  # 1-10, 10 最高
    confidence: float  # 0-1
    evidence: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class LearningOptimizer:
    """学习优化器"""
    
    def __init__(self, max_records: int = 1000):
        """
        初始化学习优化器
        
        Args:
            max_records: 最大记录数量
        """
        self.max_records = max_records
        self.learning_records: deque = deque(maxlen=max_records)
        self.optimization_insights: List[OptimizationInsight] = []
        self.applied_optimizations: List[Dict] = []
        
        # 性能指标
        self.performance_metrics = {
            'total_tasks': 0,
            'successful_tasks': 0,
            'failed_tasks': 0,
            'average_duration': 0.0,
            'average_success_rate': 0.0,
            'total_optimizations': 0
        }
        
        logger.info("LearningOptimizer 初始化完成")
    
    def record_execution(self, execution_result: Dict):
        """
        记录执行结果
        
        Args:
            execution_result: 执行结果
        """
        summary = execution_result.get('summary', {})
        
        record = LearningRecord(
            timestamp=time.time(),
            goal=summary.get('goal', 'unknown'),
            success=execution_result.get('success', False),
            duration=summary.get('total_duration', 0),
            actions_count=summary.get('total_actions', 0),
            success_rate=summary.get('success_rate', 0),
            resource_utilization=execution_result.get('resource_utilization', 0.0),
            user_satisfaction=execution_result.get('user_satisfaction', 0.0)
        )
        
        self.learning_records.append(record)
        
        # 更新性能指标
        self.performance_metrics['total_tasks'] += 1
        if record.success:
            self.performance_metrics['successful_tasks'] += 1
        else:
            self.performance_metrics['failed_tasks'] += 1
        
        # 计算平均值
        self._update_average_metrics()
        
        logger.info(f"记录执行结果: {record.goal} - 成功={record.success}")
    
    def _update_average_metrics(self):
        """更新平均指标"""
        if not self.learning_records:
            return
        
        total_duration = sum(r.duration for r in self.learning_records)
        total_success_rate = sum(r.success_rate for r in self.learning_records)
        
        self.performance_metrics['average_duration'] = total_duration / len(self.learning_records)
        self.performance_metrics['average_success_rate'] = total_success_rate / len(self.learning_records)
    
    def analyze_performance(self) -> List[OptimizationInsight]:
        """
        分析性能并生成优化洞察
        
        Returns:
            优化洞察列表
        """
        logger.info("分析性能...")
        
        insights = []
        
        if len(self.learning_records) < 5:
            logger.info("记录数量不足，跳过分析")
            return insights
        
        # 分析成功率
        recent_records = list(self.learning_records)[-10:]
        success_rate = sum(1 for r in recent_records if r.success) / len(recent_records)
        
        if success_rate < 0.5:
            insights.append(OptimizationInsight(
                insight_id=f"insight_{int(time.time())}",
                category="success_rate",
                description=f"成功率过低 ({success_rate:.1%})，需要改进",
                strategy=OptimizationStrategy.ADD_FALLBACK,
                priority=9,
                confidence=0.9,
                evidence=[f"最近 10 次任务成功率仅 {success_rate:.1%}"]
            ))
        
        # 分析执行时间
        avg_duration = sum(r.duration for r in recent_records) / len(recent_records)
        
        if avg_duration > 60.0:
            insights.append(OptimizationInsight(
                insight_id=f"insight_{int(time.time())}_1",
                category="duration",
                description=f"平均执行时间过长 ({avg_duration:.1f}s)，需要优化",
                strategy=OptimizationStrategy.IMPROVE_TIMING,
                priority=7,
                confidence=0.8,
                evidence=[f"最近 10 次任务平均耗时 {avg_duration:.1f}s"]
            ))
        
        # 分析失败模式
        failed_records = [r for r in recent_records if not r.success]
        if len(failed_records) >= 3:
            insights.append(OptimizationInsight(
                insight_id=f"insight_{int(time.time())}_2",
                category="failure_pattern",
                description=f"检测到连续失败模式 ({len(failed_records)} 次失败)",
                strategy=OptimizationStrategy.CHANGE_APPROACH,
                priority=8,
                confidence=0.85,
                evidence=[f"最近 10 次任务中有 {len(failed_records)} 次失败"]
            ))
        
        # 分析资源利用率
        if recent_records and hasattr(recent_records[0], 'resource_utilization'):
            avg_utilization = sum(r.resource_utilization for r in recent_records) / len(recent_records)
            
            if avg_utilization > 0.9:
                insights.append(OptimizationInsight(
                    insight_id=f"insight_{int(time.time())}_3",
                    category="resource_utilization",
                    description=f"资源利用率过高 ({avg_utilization:.1%})，可能需要增加资源",
                    strategy=OptimizationStrategy.INCREASE_RESOURCES,
                    priority=6,
                    confidence=0.75,
                    evidence=[f"平均资源利用率 {avg_utilization:.1%}"]
                ))
            elif avg_utilization < 0.3:
                insights.append(OptimizationInsight(
                    insight_id=f"insight_{int(time.time())}_4",
                    category="resource_utilization",
                    description=f"资源利用率过低 ({avg_utilization:.1%})，可以减少资源",
                    strategy=OptimizationStrategy.DECREASE_RESOURCES,
                    priority=4,
                    confidence=0.7,
                    evidence=[f"平均资源利用率 {avg_utilization:.1%}"]
                ))
        
        # 保存洞察
        self.optimization_insights.extend(insights)
        
        logger.info(f"生成了 {len(insights)} 个优化洞察")
        
        return insights
    
    def generate_optimization_plan(self, insights: List[OptimizationInsight]) -> List[Dict]:
        """
        生成优化计划
        
        Args:
            insights: 优化洞察列表
        
        Returns:
            优化计划列表
        """
        logger.info("生成优化计划...")
        
        # 按优先级排序
        sorted_insights = sorted(insights, key=lambda x: x.priority, reverse=True)
        
        optimization_plan = []
        
        for insight in sorted_insights[:5]:  # 只处理前 5 个最高优先级的洞察
            action = self._create_optimization_action(insight)
            if action:
                optimization_plan.append(action)
        
        logger.info(f"生成了 {len(optimization_plan)} 个优化动作")
        
        return optimization_plan
    
    def _create_optimization_action(self, insight: OptimizationInsight) -> Optional[Dict]:
        """创建优化动作"""
        action = {
            'insight_id': insight.insight_id,
            'strategy': insight.strategy.value,
            'description': insight.description,
            'priority': insight.priority,
            'timestamp': time.time()
        }
        
        # 根据策略添加具体动作
        if insight.strategy == OptimizationStrategy.ADD_FALLBACK:
            action['actions'] = [
                "为关键动作添加后备方案",
                "增加错误处理逻辑",
                "提高重试次数"
            ]
        
        elif insight.strategy == OptimizationStrategy.IMPROVE_TIMING:
            action['actions'] = [
                "优化动作执行顺序",
                "并行执行独立动作",
                "减少不必要的等待时间"
            ]
        
        elif insight.strategy == OptimizationStrategy.CHANGE_APPROACH:
            action['actions'] = [
                "尝试不同的执行策略",
                "调整资源分配",
                "重新评估目标分解"
            ]
        
        elif insight.strategy == OptimizationStrategy.INCREASE_RESOURCES:
            action['actions'] = [
                "增加可用资源",
                "提高资源优先级",
                "优化资源调度"
            ]
        
        elif insight.strategy == OptimizationStrategy.DECREASE_RESOURCES:
            action['actions'] = [
                "减少不必要的资源分配",
                "优化资源使用效率",
                "释放闲置资源"
            ]
        
        elif insight.strategy == OptimizationStrategy.ENHANCE_SAFETY:
            action['actions'] = [
                "增强安全检查",
                "添加更多安全规则",
                "提高安全阈值"
            ]
        
        return action
    
    def apply_optimization(self, optimization_action: Dict) -> bool:
        """
        应用优化
        
        Args:
            optimization_action: 优化动作
        
        Returns:
            是否成功应用
        """
        logger.info(f"应用优化: {optimization_action['description']}")
        
        try:
            # 记录应用的优化
            self.applied_optimizations.append({
                'action': optimization_action,
                'timestamp': time.time(),
                'status': 'applied'
            })
            
            self.performance_metrics['total_optimizations'] += 1
            
            logger.info(f"优化应用成功: {optimization_action['strategy']}")
            return True
        
        except Exception as e:
            logger.error(f"优化应用失败: {e}")
            return False
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        return {
            'total_tasks': self.performance_metrics['total_tasks'],
            'successful_tasks': self.performance_metrics['successful_tasks'],
            'failed_tasks': self.performance_metrics['failed_tasks'],
            'success_rate': (
                self.performance_metrics['successful_tasks'] / self.performance_metrics['total_tasks']
                if self.performance_metrics['total_tasks'] > 0 else 0
            ),
            'average_duration': self.performance_metrics['average_duration'],
            'average_success_rate': self.performance_metrics['average_success_rate'],
            'total_optimizations': self.performance_metrics['total_optimizations'],
            'total_insights': len(self.optimization_insights),
            'recent_records': len(self.learning_records)
        }
    
    def get_learning_curve(self, window_size: int = 10) -> List[Dict]:
        """
        获取学习曲线
        
        Args:
            window_size: 窗口大小
        
        Returns:
            学习曲线数据点列表
        """
        if len(self.learning_records) < window_size:
            return []
        
        curve = []
        records = list(self.learning_records)
        
        for i in range(window_size, len(records) + 1):
            window = records[i - window_size:i]
            success_rate = sum(1 for r in window if r.success) / len(window)
            avg_duration = sum(r.duration for r in window) / len(window)
            
            curve.append({
                'index': i,
                'success_rate': success_rate,
                'average_duration': avg_duration,
                'timestamp': window[-1].timestamp
            })
        
        return curve
    
    def should_optimize(self) -> bool:
        """判断是否应该进行优化"""
        # 至少需要 10 条记录
        if len(self.learning_records) < 10:
            return False
        
        # 检查最近的性能
        recent_records = list(self.learning_records)[-10:]
        success_rate = sum(1 for r in recent_records if r.success) / len(recent_records)
        
        # 如果成功率低于 70%，应该优化
        if success_rate < 0.7:
            return True
        
        # 检查是否有长时间未优化
        if self.applied_optimizations:
            last_optimization_time = self.applied_optimizations[-1]['timestamp']
            if time.time() - last_optimization_time > 3600:  # 1 小时
                return True
        
        return False
