"""
Proactive Sensing Engine - 主动感知引擎核心模块

功能：
1. 环境状态监控
2. 异常模式识别
3. 机会发现
4. 主动预警
"""

import time
import json
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field


class AlertLevel(Enum):
    """预警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class OpportunityType(Enum):
    """机会类型"""
    OPTIMIZATION = "optimization"  # 优化机会
    INTEGRATION = "integration"    # 集成机会
    LEARNING = "learning"          # 学习机会
    AUTOMATION = "automation"      # 自动化机会


class AnomalyType(Enum):
    """异常类型"""
    PERFORMANCE = "performance"    # 性能异常
    ERROR = "error"                # 错误异常
    PATTERN = "pattern"            # 模式异常
    RESOURCE = "resource"          # 资源异常


@dataclass
class EnvironmentState:
    """环境状态"""
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics,
            "events": self.events,
            "context": self.context
        }


@dataclass
class Alert:
    """预警"""
    alert_id: str
    level: AlertLevel
    title: str
    description: str
    source: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "level": self.level.value,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "acknowledged": self.acknowledged
        }


@dataclass
class Opportunity:
    """机会"""
    opportunity_id: str
    type: OpportunityType
    title: str
    description: str
    potential_value: float  # 0-1
    effort_required: float  # 0-1
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "potential_value": self.potential_value,
            "effort_required": self.effort_required,
            "priority_score": self.potential_value / max(self.effort_required, 0.1),
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class Anomaly:
    """异常"""
    anomaly_id: str
    type: AnomalyType
    title: str
    description: str
    severity: float  # 0-1
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class ProactiveSensingEngine:
    """主动感知引擎"""
    
    def __init__(self, metacognition_client=None, search_client=None):
        """
        初始化主动感知引擎
        
        Args:
            metacognition_client: 元认知客户端（Node_108）
            search_client: 搜索客户端（Node_22/Node_25）
        """
        self.metacognition_client = metacognition_client
        self.search_client = search_client
        
        # 状态历史
        self.state_history: List[EnvironmentState] = []
        
        # 预警、机会、异常
        self.alerts: List[Alert] = []
        self.opportunities: List[Opportunity] = []
        self.anomalies: List[Anomaly] = []
        
        # 监控器注册表
        self.monitors: Dict[str, Callable] = {}
        
        # 配置
        self.config = {
            "scan_interval": 60,  # 扫描间隔（秒）
            "history_window": 3600,  # 历史窗口（秒）
            "anomaly_threshold": 0.7,  # 异常阈值
            "opportunity_threshold": 0.6  # 机会阈值
        }
    
    def register_monitor(self, name: str, monitor_func: Callable):
        """
        注册监控器
        
        Args:
            name: 监控器名称
            monitor_func: 监控函数，返回 Dict[str, Any]
        """
        self.monitors[name] = monitor_func
    
    def scan_environment(self) -> EnvironmentState:
        """
        扫描环境状态
        
        Returns:
            EnvironmentState: 环境状态
        """
        state = EnvironmentState()
        
        # 执行所有注册的监控器
        for monitor_name, monitor_func in self.monitors.items():
            try:
                result = monitor_func()
                state.metrics[monitor_name] = result
            except Exception as e:
                state.events.append({
                    "type": "monitor_error",
                    "monitor": monitor_name,
                    "error": str(e)
                })
        
        # 记录到历史
        self.state_history.append(state)
        
        # 清理旧历史
        self._cleanup_old_history()
        
        return state
    
    def detect_anomalies(
        self,
        current_state: Optional[EnvironmentState] = None
    ) -> List[Anomaly]:
        """
        检测异常
        
        Args:
            current_state: 当前状态，None 则使用最新状态
            
        Returns:
            List[Anomaly]: 检测到的异常列表
        """
        if current_state is None:
            if not self.state_history:
                return []
            current_state = self.state_history[-1]
        
        detected_anomalies = []
        
        # 1. 性能异常检测
        performance_anomalies = self._detect_performance_anomalies(current_state)
        detected_anomalies.extend(performance_anomalies)
        
        # 2. 错误异常检测
        error_anomalies = self._detect_error_anomalies(current_state)
        detected_anomalies.extend(error_anomalies)
        
        # 3. 模式异常检测
        pattern_anomalies = self._detect_pattern_anomalies(current_state)
        detected_anomalies.extend(pattern_anomalies)
        
        # 4. 资源异常检测
        resource_anomalies = self._detect_resource_anomalies(current_state)
        detected_anomalies.extend(resource_anomalies)
        
        # 记录异常
        self.anomalies.extend(detected_anomalies)
        
        # 为严重异常生成预警
        for anomaly in detected_anomalies:
            if anomaly.severity >= self.config["anomaly_threshold"]:
                self._create_alert_from_anomaly(anomaly)
        
        return detected_anomalies
    
    def discover_opportunities(
        self,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Opportunity]:
        """
        发现机会
        
        Args:
            context: 上下文信息
            
        Returns:
            List[Opportunity]: 发现的机会列表
        """
        context = context or {}
        discovered_opportunities = []
        
        # 1. 优化机会
        optimization_opps = self._discover_optimization_opportunities(context)
        discovered_opportunities.extend(optimization_opps)
        
        # 2. 集成机会
        integration_opps = self._discover_integration_opportunities(context)
        discovered_opportunities.extend(integration_opps)
        
        # 3. 学习机会
        learning_opps = self._discover_learning_opportunities(context)
        discovered_opportunities.extend(learning_opps)
        
        # 4. 自动化机会
        automation_opps = self._discover_automation_opportunities(context)
        discovered_opportunities.extend(automation_opps)
        
        # 过滤低价值机会
        filtered_opportunities = [
            opp for opp in discovered_opportunities
            if opp.potential_value >= self.config["opportunity_threshold"]
        ]
        
        # 记录机会
        self.opportunities.extend(filtered_opportunities)
        
        return filtered_opportunities
    
    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        description: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Alert:
        """
        创建预警
        
        Args:
            level: 预警级别
            title: 标题
            description: 描述
            source: 来源
            metadata: 元数据
            
        Returns:
            Alert: 预警对象
        """
        alert_id = f"alert_{int(time.time() * 1000)}"
        alert = Alert(
            alert_id=alert_id,
            level=level,
            title=title,
            description=description,
            source=source,
            metadata=metadata or {}
        )
        
        self.alerts.append(alert)
        return alert
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """
        确认预警
        
        Args:
            alert_id: 预警ID
            
        Returns:
            bool: 是否成功
        """
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False
    
    def get_active_alerts(self) -> List[Alert]:
        """获取未确认的预警"""
        return [a for a in self.alerts if not a.acknowledged]
    
    def get_recent_opportunities(self, limit: int = 10) -> List[Opportunity]:
        """获取最近的机会"""
        sorted_opps = sorted(
            self.opportunities,
            key=lambda o: o.potential_value / max(o.effort_required, 0.1),
            reverse=True
        )
        return sorted_opps[:limit]
    
    def get_recent_anomalies(self, limit: int = 10) -> List[Anomaly]:
        """获取最近的异常"""
        sorted_anomalies = sorted(
            self.anomalies,
            key=lambda a: a.timestamp,
            reverse=True
        )
        return sorted_anomalies[:limit]
    
    # ========== 私有方法 ==========
    
    def _cleanup_old_history(self):
        """清理旧历史"""
        current_time = time.time()
        cutoff_time = current_time - self.config["history_window"]
        
        self.state_history = [
            s for s in self.state_history
            if s.timestamp >= cutoff_time
        ]
    
    def _detect_performance_anomalies(
        self, state: EnvironmentState
    ) -> List[Anomaly]:
        """检测性能异常"""
        anomalies = []
        
        # 检查响应时间
        if "response_time" in state.metrics:
            response_time = state.metrics["response_time"]
            if isinstance(response_time, (int, float)) and response_time > 5000:
                anomalies.append(Anomaly(
                    anomaly_id=f"anomaly_{int(time.time() * 1000)}",
                    type=AnomalyType.PERFORMANCE,
                    title="响应时间过长",
                    description=f"响应时间 {response_time}ms 超过阈值 5000ms",
                    severity=min(response_time / 10000, 1.0),
                    metadata={"response_time": response_time}
                ))
        
        return anomalies
    
    def _detect_error_anomalies(self, state: EnvironmentState) -> List[Anomaly]:
        """检测错误异常"""
        anomalies = []
        
        # 检查错误事件
        error_events = [e for e in state.events if e.get("type") == "error"]
        if len(error_events) > 3:
            anomalies.append(Anomaly(
                anomaly_id=f"anomaly_{int(time.time() * 1000)}",
                type=AnomalyType.ERROR,
                title="错误率过高",
                description=f"检测到 {len(error_events)} 个错误事件",
                severity=min(len(error_events) / 10, 1.0),
                metadata={"error_count": len(error_events)}
            ))
        
        return anomalies
    
    def _detect_pattern_anomalies(self, state: EnvironmentState) -> List[Anomaly]:
        """检测模式异常"""
        anomalies = []
        
        # 简化实现：检查与历史模式的偏离
        if len(self.state_history) >= 10:
            # 这里可以实现更复杂的模式识别算法
            pass
        
        return anomalies
    
    def _detect_resource_anomalies(self, state: EnvironmentState) -> List[Anomaly]:
        """检测资源异常"""
        anomalies = []
        
        # 检查资源使用
        if "resource_usage" in state.metrics:
            usage = state.metrics["resource_usage"]
            if isinstance(usage, dict):
                cpu_usage = usage.get("cpu", 0)
                memory_usage = usage.get("memory", 0)
                
                if cpu_usage > 90:
                    anomalies.append(Anomaly(
                        anomaly_id=f"anomaly_{int(time.time() * 1000)}",
                        type=AnomalyType.RESOURCE,
                        title="CPU 使用率过高",
                        description=f"CPU 使用率 {cpu_usage}% 超过阈值 90%",
                        severity=min(cpu_usage / 100, 1.0),
                        metadata={"cpu_usage": cpu_usage}
                    ))
                
                if memory_usage > 90:
                    anomalies.append(Anomaly(
                        anomaly_id=f"anomaly_{int(time.time() * 1000)}",
                        type=AnomalyType.RESOURCE,
                        title="内存使用率过高",
                        description=f"内存使用率 {memory_usage}% 超过阈值 90%",
                        severity=min(memory_usage / 100, 1.0),
                        metadata={"memory_usage": memory_usage}
                    ))
        
        return anomalies
    
    def _discover_optimization_opportunities(
        self, context: Dict[str, Any]
    ) -> List[Opportunity]:
        """发现优化机会"""
        opportunities = []
        
        # 基于异常历史发现优化机会
        recent_anomalies = self.get_recent_anomalies(limit=20)
        
        # 统计异常类型
        anomaly_counts = {}
        for anomaly in recent_anomalies:
            anomaly_type = anomaly.type.value
            anomaly_counts[anomaly_type] = anomaly_counts.get(anomaly_type, 0) + 1
        
        # 如果某类异常频繁出现，建议优化
        for anomaly_type, count in anomaly_counts.items():
            if count >= 5:
                opportunities.append(Opportunity(
                    opportunity_id=f"opp_{int(time.time() * 1000)}",
                    type=OpportunityType.OPTIMIZATION,
                    title=f"优化 {anomaly_type} 相关问题",
                    description=f"最近检测到 {count} 次 {anomaly_type} 异常，建议进行系统性优化",
                    potential_value=min(count / 10, 1.0),
                    effort_required=0.5,
                    metadata={"anomaly_type": anomaly_type, "count": count}
                ))
        
        return opportunities
    
    def _discover_integration_opportunities(
        self, context: Dict[str, Any]
    ) -> List[Opportunity]:
        """发现集成机会"""
        opportunities = []
        
        # 简化实现：基于上下文中的关键词
        if "tools" in context or "integration" in context:
            opportunities.append(Opportunity(
                opportunity_id=f"opp_{int(time.time() * 1000)}",
                type=OpportunityType.INTEGRATION,
                title="集成新工具",
                description="检测到可能的工具集成需求",
                potential_value=0.8,
                effort_required=0.6,
                metadata=context
            ))
        
        return opportunities
    
    def _discover_learning_opportunities(
        self, context: Dict[str, Any]
    ) -> List[Opportunity]:
        """发现学习机会"""
        opportunities = []
        
        # 基于重复模式发现学习机会
        if len(self.state_history) >= 20:
            # 这里可以实现模式学习算法
            opportunities.append(Opportunity(
                opportunity_id=f"opp_{int(time.time() * 1000)}",
                type=OpportunityType.LEARNING,
                title="学习重复模式",
                description="检测到足够的历史数据，可以学习常见模式",
                potential_value=0.7,
                effort_required=0.4,
                metadata={"history_size": len(self.state_history)}
            ))
        
        return opportunities
    
    def _discover_automation_opportunities(
        self, context: Dict[str, Any]
    ) -> List[Opportunity]:
        """发现自动化机会"""
        opportunities = []
        
        # 基于重复任务发现自动化机会
        if "repetitive_task" in context:
            opportunities.append(Opportunity(
                opportunity_id=f"opp_{int(time.time() * 1000)}",
                type=OpportunityType.AUTOMATION,
                title="自动化重复任务",
                description="检测到重复性任务，建议自动化",
                potential_value=0.9,
                effort_required=0.7,
                metadata=context
            ))
        
        return opportunities
    
    def _create_alert_from_anomaly(self, anomaly: Anomaly):
        """从异常创建预警"""
        level = AlertLevel.INFO
        if anomaly.severity >= 0.9:
            level = AlertLevel.CRITICAL
        elif anomaly.severity >= 0.7:
            level = AlertLevel.WARNING
        
        self.create_alert(
            level=level,
            title=anomaly.title,
            description=anomaly.description,
            source=f"anomaly_detector_{anomaly.type.value}",
            metadata={
                "anomaly_id": anomaly.anomaly_id,
                "severity": anomaly.severity
            }
        )
