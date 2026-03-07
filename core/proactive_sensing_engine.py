"""
UFO Galaxy - 主动感知引擎
==========================

提供环境扫描、异常检测、机会发现和告警管理能力。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.ProactiveSensing")


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class OpportunityType(str, Enum):
    OPTIMIZATION = "optimization"
    AUTOMATION = "automation"
    INTEGRATION = "integration"
    LEARNING = "learning"


class AnomalyType(str, Enum):
    PERFORMANCE = "performance"
    SECURITY = "security"
    RESOURCE = "resource"
    BEHAVIOR = "behavior"


@dataclass
class EnvironmentState:
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "metrics": self.metrics,
            "events": self.events,
            "context": self.context,
        }


@dataclass
class Anomaly:
    anomaly_id: str
    anomaly_type: AnomalyType
    description: str
    severity: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "description": self.description,
            "severity": self.severity,
            "timestamp": self.timestamp,
        }


@dataclass
class Opportunity:
    opportunity_id: str
    opportunity_type: OpportunityType
    description: str
    potential_value: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "opportunity_id": self.opportunity_id,
            "opportunity_type": self.opportunity_type.value,
            "description": self.description,
            "potential_value": self.potential_value,
            "timestamp": self.timestamp,
        }


@dataclass
class Alert:
    alert_id: str
    level: AlertLevel
    title: str
    description: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "level": self.level.value,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "metadata": self.metadata,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp,
        }


class ProactiveSensingEngine:
    """主动感知引擎 - 环境监控、异常检测、机会发现"""

    def __init__(self):
        self.monitors: Dict[str, Callable] = {}
        self.opportunities: List[Opportunity] = []
        self.anomalies: List[Anomaly] = []
        self.alerts: List[Alert] = []
        self.state_history: List[EnvironmentState] = []
        logger.info("主动感知引擎已初始化")

    def scan_environment(self) -> EnvironmentState:
        state = EnvironmentState(
            metrics={"cpu_usage": 0.0, "memory_usage": 0.0, "active_nodes": 0},
            events=[],
            context={"scan_source": "proactive_sensing"},
        )
        self.state_history.append(state)
        return state

    def detect_anomalies(self, current_state: Optional[EnvironmentState] = None) -> List[Anomaly]:
        if current_state is None:
            current_state = self.scan_environment()
        return []

    def discover_opportunities(self, context: Optional[Dict] = None) -> List[Opportunity]:
        return []

    def create_alert(
        self,
        level: str,
        title: str,
        description: str,
        source: str = "system",
        metadata: Optional[Dict] = None,
    ) -> Alert:
        alert = Alert(
            alert_id=f"alert_{uuid.uuid4().hex[:12]}",
            level=AlertLevel(level) if isinstance(level, str) else level,
            title=title,
            description=description,
            source=source,
            metadata=metadata or {},
        )
        self.alerts.append(alert)
        logger.info(f"告警已创建: [{alert.level.value}] {title}")
        return alert

    def acknowledge_alert(self, alert_id: str) -> bool:
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def get_active_alerts(self) -> List[Alert]:
        return [a for a in self.alerts if not a.acknowledged]

    def get_recent_opportunities(self, limit: int = 10) -> List[Opportunity]:
        return sorted(self.opportunities, key=lambda o: o.timestamp, reverse=True)[:limit]

    def get_recent_anomalies(self, limit: int = 10) -> List[Anomaly]:
        return sorted(self.anomalies, key=lambda a: a.timestamp, reverse=True)[:limit]

    def register_monitor(self, name: str, func: Callable) -> None:
        self.monitors[name] = func
        logger.info(f"监控器已注册: {name}")
