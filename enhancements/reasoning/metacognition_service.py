"""
元认知服务 (MetaCognition Service)
系统的自我反思和自我改进能力
"""

import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class PerformanceLevel(Enum):
    """性能等级"""
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    POOR = "poor"
    FAILING = "failing"


@dataclass
class PerformanceMetrics:
    """性能指标"""
    success_rate: float  # 0-1
    average_duration: float  # 秒
    resource_utilization: float  # 0-1
    user_satisfaction: float  # 0-1
    error_rate: float  # 0-1


@dataclass
class SelfAssessment:
    """自我评估"""
    timestamp: float
    overall_performance: PerformanceLevel
    metrics: PerformanceMetrics
    strengths: List[str]
    weaknesses: List[str]
    improvement_suggestions: List[str]


@dataclass
class LearningInsight:
    """学习洞察"""
    insight_type: str  # 'pattern', 'optimization', 'failure_analysis'
    description: str
    confidence: float  # 0-1
    actionable_steps: List[str]
    timestamp: float


class MetaCognitionService:
    """元认知服务"""
    
    def __init__(self):
        self.assessments: List[SelfAssessment] = []
        self.insights: List[LearningInsight] = []
        self.performance_history: List[Dict] = []
        logger.info("MetaCognitionService initialized")
    
    def assess_performance(self, recent_tasks: List[Dict]) -> SelfAssessment:
        """评估性能"""
        logger.info(f"评估最近 {len(recent_tasks)} 个任务的性能")
        
        # 计算性能指标
        metrics = self._calculate_metrics(recent_tasks)
        
        # 确定性能等级
        overall_performance = self._determine_performance_level(metrics)
        
        # 识别优势和劣势
        strengths = self._identify_strengths(metrics, recent_tasks)
        weaknesses = self._identify_weaknesses(metrics, recent_tasks)
        
        # 生成改进建议
        suggestions = self._generate_improvement_suggestions(weaknesses, metrics)
        
        assessment = SelfAssessment(
            timestamp=time.time(),
            overall_performance=overall_performance,
            metrics=metrics,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_suggestions=suggestions
        )
        
        self.assessments.append(assessment)
        logger.info(f"性能评估完成: {overall_performance.value}")
        
        return assessment
    
    def _calculate_metrics(self, tasks: List[Dict]) -> PerformanceMetrics:
        """计算性能指标"""
        if not tasks:
            return PerformanceMetrics(
                success_rate=0.0,
                average_duration=0.0,
                resource_utilization=0.0,
                user_satisfaction=0.0,
                error_rate=1.0
            )
        
        # 成功率
        success_count = sum(1 for t in tasks if t.get('success', False))
        success_rate = success_count / len(tasks)
        
        # 平均时长
        durations = [t.get('duration', 0) for t in tasks]
        average_duration = sum(durations) / len(durations) if durations else 0
        
        # 资源利用率
        resource_usage = [t.get('resource_utilization', 0.5) for t in tasks]
        resource_utilization = sum(resource_usage) / len(resource_usage)
        
        # 用户满意度
        satisfaction_scores = [t.get('user_satisfaction', 0.7) for t in tasks]
        user_satisfaction = sum(satisfaction_scores) / len(satisfaction_scores)
        
        # 错误率
        error_rate = 1.0 - success_rate
        
        return PerformanceMetrics(
            success_rate=success_rate,
            average_duration=average_duration,
            resource_utilization=resource_utilization,
            user_satisfaction=user_satisfaction,
            error_rate=error_rate
        )
    
    def _determine_performance_level(self, metrics: PerformanceMetrics) -> PerformanceLevel:
        """确定性能等级"""
        # 综合评分
        score = (
            metrics.success_rate * 0.4 +
            (1.0 - min(metrics.error_rate, 1.0)) * 0.3 +
            metrics.user_satisfaction * 0.2 +
            metrics.resource_utilization * 0.1
        )
        
        if score >= 0.9:
            return PerformanceLevel.EXCELLENT
        elif score >= 0.75:
            return PerformanceLevel.GOOD
        elif score >= 0.6:
            return PerformanceLevel.AVERAGE
        elif score >= 0.4:
            return PerformanceLevel.POOR
        else:
            return PerformanceLevel.FAILING
    
    def _identify_strengths(self, metrics: PerformanceMetrics, tasks: List[Dict]) -> List[str]:
        """识别优势"""
        strengths = []
        
        if metrics.success_rate >= 0.9:
            strengths.append("高成功率")
        
        if metrics.user_satisfaction >= 0.8:
            strengths.append("用户满意度高")
        
        if metrics.resource_utilization >= 0.7 and metrics.resource_utilization <= 0.9:
            strengths.append("资源利用率优秀")
        
        if metrics.error_rate <= 0.05:
            strengths.append("错误率极低")
        
        return strengths if strengths else ["暂无明显优势"]
    
    def _identify_weaknesses(self, metrics: PerformanceMetrics, tasks: List[Dict]) -> List[str]:
        """识别劣势"""
        weaknesses = []
        
        if metrics.success_rate < 0.7:
            weaknesses.append("成功率偏低")
        
        if metrics.error_rate > 0.2:
            weaknesses.append("错误率过高")
        
        if metrics.user_satisfaction < 0.6:
            weaknesses.append("用户满意度低")
        
        if metrics.resource_utilization < 0.4:
            weaknesses.append("资源利用率不足")
        elif metrics.resource_utilization > 0.95:
            weaknesses.append("资源过度使用")
        
        if metrics.average_duration > 300:
            weaknesses.append("任务执行时间过长")
        
        return weaknesses if weaknesses else ["暂无明显劣势"]
    
    def _generate_improvement_suggestions(self, weaknesses: List[str], metrics: PerformanceMetrics) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        if "成功率偏低" in weaknesses:
            suggestions.append("增加任务执行前的可行性检查")
            suggestions.append("改进错误处理和重试机制")
        
        if "错误率过高" in weaknesses:
            suggestions.append("分析常见错误模式并预防")
            suggestions.append("增强异常检测和恢复能力")
        
        if "用户满意度低" in weaknesses:
            suggestions.append("改进用户交互和反馈机制")
            suggestions.append("优化任务执行的可见性")
        
        if "资源利用率不足" in weaknesses:
            suggestions.append("优化资源分配策略")
            suggestions.append("启用并行执行能力")
        
        if "资源过度使用" in weaknesses:
            suggestions.append("实施资源限流和配额管理")
            suggestions.append("优化资源释放机制")
        
        if "任务执行时间过长" in weaknesses:
            suggestions.append("优化任务分解和并行化")
            suggestions.append("缓存常用结果")
        
        return suggestions if suggestions else ["继续保持当前水平"]
    
    def extract_insights(self, tasks: List[Dict], world_state: Dict) -> List[LearningInsight]:
        """提取学习洞察"""
        logger.info("提取学习洞察")
        
        insights = []
        
        # 模式识别
        pattern_insights = self._identify_patterns(tasks)
        insights.extend(pattern_insights)
        
        # 优化机会
        optimization_insights = self._identify_optimizations(tasks, world_state)
        insights.extend(optimization_insights)
        
        # 失败分析
        failure_insights = self._analyze_failures(tasks)
        insights.extend(failure_insights)
        
        self.insights.extend(insights)
        logger.info(f"提取了 {len(insights)} 个洞察")
        
        return insights
    
    def _identify_patterns(self, tasks: List[Dict]) -> List[LearningInsight]:
        """识别模式"""
        insights = []
        
        # 简单的模式识别
        task_types = {}
        for task in tasks:
            task_type = task.get('type', 'unknown')
            if task_type not in task_types:
                task_types[task_type] = {'count': 0, 'success': 0}
            task_types[task_type]['count'] += 1
            if task.get('success', False):
                task_types[task_type]['success'] += 1
        
        # 识别高频任务类型
        for task_type, stats in task_types.items():
            if stats['count'] >= 5:
                success_rate = stats['success'] / stats['count']
                insights.append(LearningInsight(
                    insight_type='pattern',
                    description=f"任务类型 '{task_type}' 出现频率高 (成功率: {success_rate:.1%})",
                    confidence=0.8,
                    actionable_steps=[
                        f"为 '{task_type}' 类型任务创建专用优化",
                        "考虑预加载相关资源"
                    ],
                    timestamp=time.time()
                ))
        
        return insights
    
    def _identify_optimizations(self, tasks: List[Dict], world_state: Dict) -> List[LearningInsight]:
        """识别优化机会"""
        insights = []
        
        # 检查资源利用
        avg_resource_usage = sum(t.get('resource_utilization', 0.5) for t in tasks) / len(tasks) if tasks else 0
        
        if avg_resource_usage < 0.5:
            insights.append(LearningInsight(
                insight_type='optimization',
                description="资源利用率偏低，存在并行化机会",
                confidence=0.7,
                actionable_steps=[
                    "识别可并行执行的任务",
                    "增加并发执行能力"
                ],
                timestamp=time.time()
            ))
        
        return insights
    
    def _analyze_failures(self, tasks: List[Dict]) -> List[LearningInsight]:
        """分析失败"""
        insights = []
        
        failed_tasks = [t for t in tasks if not t.get('success', False)]
        
        if len(failed_tasks) > len(tasks) * 0.2:  # 失败率超过 20%
            # 分析失败原因
            failure_reasons = {}
            for task in failed_tasks:
                reason = task.get('failure_reason', 'unknown')
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            
            # 找出最常见的失败原因
            if failure_reasons:
                most_common = max(failure_reasons.items(), key=lambda x: x[1])
                insights.append(LearningInsight(
                    insight_type='failure_analysis',
                    description=f"最常见的失败原因: {most_common[0]} ({most_common[1]} 次)",
                    confidence=0.9,
                    actionable_steps=[
                        f"针对 '{most_common[0]}' 实施专门的预防措施",
                        "增强相关错误处理逻辑"
                    ],
                    timestamp=time.time()
                ))
        
        return insights
    
    def should_adjust_strategy(self) -> bool:
        """判断是否应该调整策略"""
        if not self.assessments:
            return False
        
        latest = self.assessments[-1]
        
        # 如果性能不佳，建议调整策略
        if latest.overall_performance in [PerformanceLevel.POOR, PerformanceLevel.FAILING]:
            logger.info("性能不佳，建议调整策略")
            return True
        
        # 如果有多个连续的弱点，建议调整
        if len(latest.weaknesses) >= 3:
            logger.info("存在多个弱点，建议调整策略")
            return True
        
        return False


if __name__ == '__main__':
    # 测试元认知服务
    logging.basicConfig(level=logging.INFO)
    
    metacog = MetaCognitionService()
    
    # 模拟一些任务数据
    tasks = [
        {'type': 'search', 'success': True, 'duration': 30, 'resource_utilization': 0.6, 'user_satisfaction': 0.9},
        {'type': 'search', 'success': True, 'duration': 25, 'resource_utilization': 0.5, 'user_satisfaction': 0.8},
        {'type': 'execute', 'success': False, 'duration': 120, 'resource_utilization': 0.8, 'user_satisfaction': 0.3, 'failure_reason': 'timeout'},
        {'type': 'write', 'success': True, 'duration': 45, 'resource_utilization': 0.7, 'user_satisfaction': 0.85},
        {'type': 'execute', 'success': False, 'duration': 90, 'resource_utilization': 0.9, 'user_satisfaction': 0.4, 'failure_reason': 'timeout'},
    ]
    
    # 评估性能
    assessment = metacog.assess_performance(tasks)
    
    print(f"\n性能评估:")
    print(f"  整体性能: {assessment.overall_performance.value}")
    print(f"  成功率: {assessment.metrics.success_rate:.1%}")
    print(f"  错误率: {assessment.metrics.error_rate:.1%}")
    print(f"  用户满意度: {assessment.metrics.user_satisfaction:.1%}")
    print(f"\n优势:")
    for strength in assessment.strengths:
        print(f"  - {strength}")
    print(f"\n劣势:")
    for weakness in assessment.weaknesses:
        print(f"  - {weakness}")
    print(f"\n改进建议:")
    for suggestion in assessment.improvement_suggestions:
        print(f"  - {suggestion}")
    
    # 提取洞察
    insights = metacog.extract_insights(tasks, {})
    print(f"\n学习洞察: {len(insights)} 个")
    for insight in insights:
        print(f"  - [{insight.insight_type}] {insight.description}")
        for step in insight.actionable_steps:
            print(f"    → {step}")
    
    # 判断是否需要调整策略
    should_adjust = metacog.should_adjust_strategy()
    print(f"\n是否需要调整策略: {'是' if should_adjust else '否'}")
