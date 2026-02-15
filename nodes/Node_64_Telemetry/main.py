"""
Node 64: Predictive Telemetry & Anomaly Detection
UFO Galaxy 64-Core MCP Matrix - Phase 6: Immune System

Multi-resolution time series with predictive alerts.
"""

import os
import json
import asyncio
import logging
import time
import statistics
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import math
import random

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "64")
NODE_NAME = os.getenv("NODE_NAME", "Telemetry")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Telemetry constraints (5% CPU rule)
MAX_CPU_USAGE = 0.05  # 5% of system CPU
SAMPLE_INTERVAL_HIGH = 1      # 1 second for high-freq
SAMPLE_INTERVAL_MEDIUM = 10   # 10 seconds for medium-freq
SAMPLE_INTERVAL_LOW = 60      # 60 seconds for low-freq
MAX_HISTORY_SIZE = 10000

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class MetricType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    QUEUE_LENGTH = "queue_length"
    LOCK_CONTENTION = "lock_contention"

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

class AnomalyType(str, Enum):
    SPIKE = "spike"
    DROP = "drop"
    TREND = "trend"
    PATTERN = "pattern"
    THRESHOLD = "threshold"

@dataclass
class MetricPoint:
    """A single metric data point."""
    timestamp: float
    value: float
    node_id: str
    metric_type: MetricType
    tags: Dict[str, str] = field(default_factory=dict)

@dataclass
class Anomaly:
    """Detected anomaly."""
    timestamp: float
    metric_type: MetricType
    node_id: str
    anomaly_type: AnomalyType
    severity: AlertSeverity
    value: float
    expected_range: Tuple[float, float]
    description: str
    confidence: float

@dataclass
class PredictiveAlert:
    """Predictive alert for future issues."""
    timestamp: float
    metric_type: MetricType
    node_id: str
    prediction: str
    time_to_issue: int  # seconds
    confidence: float
    recommended_action: str

class MetricReport(BaseModel):
    node_id: str
    metrics: Dict[str, float]
    timestamp: Optional[float] = None

class TelemetryStats(BaseModel):
    total_points: int
    nodes_monitored: int
    anomalies_detected: int
    alerts_generated: int
    cpu_usage_percent: float

# =============================================================================
# Time Series Storage
# =============================================================================

class CircularBuffer:
    """Efficient circular buffer for time series data."""
    
    def __init__(self, max_size: int = 1000):
        self.buffer = deque(maxlen=max_size)
        self.max_size = max_size
    
    def append(self, item: Any):
        self.buffer.append(item)
    
    def get_recent(self, n: int) -> List[Any]:
        return list(self.buffer)[-n:]
    
    def get_all(self) -> List[Any]:
        return list(self.buffer)
    
    def __len__(self) -> int:
        return len(self.buffer)

class TimeSeriesStore:
    """Multi-resolution time series storage."""
    
    def __init__(self):
        # High-frequency (1s) - last 10 minutes
        self.high_freq: Dict[str, CircularBuffer] = {}
        
        # Medium-frequency (10s) - last 1 hour
        self.medium_freq: Dict[str, CircularBuffer] = {}
        
        # Low-frequency (60s) - last 24 hours
        self.low_freq: Dict[str, CircularBuffer] = {}
        
        # Aggregation timestamps
        self.last_medium_agg: Dict[str, float] = {}
        self.last_low_agg: Dict[str, float] = {}
    
    def _get_key(self, node_id: str, metric_type: MetricType) -> str:
        return f"{node_id}:{metric_type.value}"
    
    def store(self, point: MetricPoint):
        """Store a metric point with automatic downsampling."""
        key = self._get_key(point.node_id, point.metric_type)
        
        # Initialize buffers if needed
        if key not in self.high_freq:
            self.high_freq[key] = CircularBuffer(600)   # 10 min at 1s
            self.medium_freq[key] = CircularBuffer(360)  # 1 hour at 10s
            self.low_freq[key] = CircularBuffer(1440)    # 24 hours at 60s
            self.last_medium_agg[key] = 0
            self.last_low_agg[key] = 0
        
        # Store in high-freq
        self.high_freq[key].append(point)
        
        # Downsample to medium-freq
        if point.timestamp - self.last_medium_agg.get(key, 0) >= SAMPLE_INTERVAL_MEDIUM:
            recent = self.high_freq[key].get_recent(SAMPLE_INTERVAL_MEDIUM)
            if recent:
                avg_value = statistics.mean(p.value for p in recent)
                agg_point = MetricPoint(
                    timestamp=point.timestamp,
                    value=avg_value,
                    node_id=point.node_id,
                    metric_type=point.metric_type
                )
                self.medium_freq[key].append(agg_point)
                self.last_medium_agg[key] = point.timestamp
        
        # Downsample to low-freq
        if point.timestamp - self.last_low_agg.get(key, 0) >= SAMPLE_INTERVAL_LOW:
            recent = self.medium_freq[key].get_recent(6)  # Last 6 medium samples
            if recent:
                avg_value = statistics.mean(p.value for p in recent)
                agg_point = MetricPoint(
                    timestamp=point.timestamp,
                    value=avg_value,
                    node_id=point.node_id,
                    metric_type=point.metric_type
                )
                self.low_freq[key].append(agg_point)
                self.last_low_agg[key] = point.timestamp
    
    def get_series(
        self,
        node_id: str,
        metric_type: MetricType,
        resolution: str = "high",
        limit: int = 100
    ) -> List[MetricPoint]:
        """Get time series data at specified resolution."""
        key = self._get_key(node_id, metric_type)
        
        if resolution == "high":
            buffer = self.high_freq.get(key)
        elif resolution == "medium":
            buffer = self.medium_freq.get(key)
        else:
            buffer = self.low_freq.get(key)
        
        if not buffer:
            return []
        
        return buffer.get_recent(limit)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        return {
            "high_freq_series": len(self.high_freq),
            "medium_freq_series": len(self.medium_freq),
            "low_freq_series": len(self.low_freq),
            "total_high_freq_points": sum(len(b) for b in self.high_freq.values()),
            "total_medium_freq_points": sum(len(b) for b in self.medium_freq.values()),
            "total_low_freq_points": sum(len(b) for b in self.low_freq.values()),
        }

# =============================================================================
# Anomaly Detection
# =============================================================================

class AnomalyDetector:
    """Multi-method anomaly detection."""
    
    def __init__(self):
        self.baselines: Dict[str, Dict[str, float]] = {}
        self.thresholds: Dict[MetricType, Tuple[float, float]] = {
            MetricType.CPU: (0, 90),
            MetricType.MEMORY: (0, 85),
            MetricType.LATENCY: (0, 1000),  # ms
            MetricType.ERROR_RATE: (0, 5),   # %
            MetricType.QUEUE_LENGTH: (0, 100),
            MetricType.LOCK_CONTENTION: (0, 50),
        }
    
    def detect(self, points: List[MetricPoint]) -> List[Anomaly]:
        """Detect anomalies using ensemble of methods."""
        if len(points) < 10:
            return []
        
        anomalies = []
        
        # Method 1: Statistical (Z-score)
        stat_anomalies = self._statistical_detection(points)
        
        # Method 2: Rule-based (thresholds)
        rule_anomalies = self._rule_based_detection(points)
        
        # Method 3: Pattern-based (simple trend)
        pattern_anomalies = self._pattern_detection(points)
        
        # Ensemble voting
        all_anomalies = stat_anomalies + rule_anomalies + pattern_anomalies
        
        # Deduplicate and vote
        anomalies = self._ensemble_vote(all_anomalies)
        
        return anomalies
    
    def _statistical_detection(self, points: List[MetricPoint]) -> List[Anomaly]:
        """Z-score based anomaly detection."""
        anomalies = []
        
        values = [p.value for p in points]
        if len(values) < 3:
            return []
        
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0
        
        if stdev == 0:
            return []
        
        for point in points[-5:]:  # Check recent points
            z_score = abs(point.value - mean) / stdev
            
            if z_score > 3:  # 3 sigma rule
                anomalies.append(Anomaly(
                    timestamp=point.timestamp,
                    metric_type=point.metric_type,
                    node_id=point.node_id,
                    anomaly_type=AnomalyType.SPIKE if point.value > mean else AnomalyType.DROP,
                    severity=AlertSeverity.WARNING if z_score < 4 else AlertSeverity.CRITICAL,
                    value=point.value,
                    expected_range=(mean - 2*stdev, mean + 2*stdev),
                    description=f"Z-score {z_score:.2f} exceeds threshold",
                    confidence=min(z_score / 5, 1.0)
                ))
        
        return anomalies
    
    def _rule_based_detection(self, points: List[MetricPoint]) -> List[Anomaly]:
        """Threshold-based anomaly detection."""
        anomalies = []
        
        if not points:
            return []
        
        metric_type = points[0].metric_type
        thresholds = self.thresholds.get(metric_type, (0, 100))
        
        for point in points[-5:]:
            if point.value < thresholds[0] or point.value > thresholds[1]:
                anomalies.append(Anomaly(
                    timestamp=point.timestamp,
                    metric_type=point.metric_type,
                    node_id=point.node_id,
                    anomaly_type=AnomalyType.THRESHOLD,
                    severity=AlertSeverity.CRITICAL if point.value > thresholds[1] * 1.2 else AlertSeverity.WARNING,
                    value=point.value,
                    expected_range=thresholds,
                    description=f"Value {point.value:.2f} outside threshold [{thresholds[0]}, {thresholds[1]}]",
                    confidence=0.9
                ))
        
        return anomalies
    
    def _pattern_detection(self, points: List[MetricPoint]) -> List[Anomaly]:
        """Simple trend detection."""
        anomalies = []
        
        if len(points) < 10:
            return []
        
        # Check for consistent upward/downward trend
        recent = [p.value for p in points[-10:]]
        
        # Simple linear regression
        n = len(recent)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(recent)
        
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return []
        
        slope = numerator / denominator
        
        # Significant trend
        if abs(slope) > y_mean * 0.1:  # 10% change per sample
            anomalies.append(Anomaly(
                timestamp=points[-1].timestamp,
                metric_type=points[-1].metric_type,
                node_id=points[-1].node_id,
                anomaly_type=AnomalyType.TREND,
                severity=AlertSeverity.WARNING,
                value=points[-1].value,
                expected_range=(y_mean * 0.9, y_mean * 1.1),
                description=f"{'Increasing' if slope > 0 else 'Decreasing'} trend detected (slope: {slope:.2f})",
                confidence=min(abs(slope) / (y_mean * 0.2), 1.0)
            ))
        
        return anomalies
    
    def _ensemble_vote(self, anomalies: List[Anomaly]) -> List[Anomaly]:
        """Combine anomalies from different detectors."""
        if not anomalies:
            return []
        
        # Group by timestamp (within 5 seconds)
        groups: Dict[int, List[Anomaly]] = {}
        for a in anomalies:
            key = int(a.timestamp / 5)
            if key not in groups:
                groups[key] = []
            groups[key].append(a)
        
        # Keep anomalies detected by multiple methods
        result = []
        for group in groups.values():
            if len(group) >= 2:  # At least 2 methods agree
                # Take the one with highest confidence
                best = max(group, key=lambda a: a.confidence)
                best.confidence = min(best.confidence + 0.1 * (len(group) - 1), 1.0)
                result.append(best)
            elif group[0].severity in [AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY]:
                # Keep critical anomalies even with single detection
                result.append(group[0])
        
        return result

# =============================================================================
# Predictive Analytics
# =============================================================================

class PredictiveAnalyzer:
    """Predictive analytics for proactive alerting."""
    
    def __init__(self):
        self.correlation_cache: Dict[str, List[Tuple[str, float]]] = {}
    
    def predict(
        self,
        store: TimeSeriesStore,
        node_id: str,
        metric_type: MetricType
    ) -> List[PredictiveAlert]:
        """Generate predictive alerts."""
        alerts = []
        
        # Get historical data
        series = store.get_series(node_id, metric_type, "medium", 100)
        
        if len(series) < 20:
            return []
        
        values = [p.value for p in series]
        
        # Predict resource exhaustion
        exhaustion_alert = self._predict_exhaustion(node_id, metric_type, values)
        if exhaustion_alert:
            alerts.append(exhaustion_alert)
        
        # Predict based on correlations
        correlation_alerts = self._predict_from_correlations(store, node_id, metric_type)
        alerts.extend(correlation_alerts)
        
        return alerts
    
    def _predict_exhaustion(
        self,
        node_id: str,
        metric_type: MetricType,
        values: List[float]
    ) -> Optional[PredictiveAlert]:
        """Predict when a resource will be exhausted."""
        if len(values) < 10:
            return None
        
        # Simple linear extrapolation
        recent = values[-10:]
        n = len(recent)
        
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(recent)
        
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return None
        
        slope = numerator / denominator
        
        # Only predict if increasing
        if slope <= 0:
            return None
        
        # Thresholds for exhaustion
        thresholds = {
            MetricType.CPU: 95,
            MetricType.MEMORY: 90,
            MetricType.QUEUE_LENGTH: 200,
        }
        
        threshold = thresholds.get(metric_type, 100)
        current = values[-1]
        
        if current >= threshold:
            return None  # Already exhausted
        
        # Time to threshold (in samples)
        samples_to_threshold = (threshold - current) / slope
        
        # Convert to seconds (assuming 10s samples)
        seconds_to_threshold = int(samples_to_threshold * 10)
        
        if seconds_to_threshold < 3600:  # Alert if within 1 hour
            return PredictiveAlert(
                timestamp=time.time(),
                metric_type=metric_type,
                node_id=node_id,
                prediction=f"{metric_type.value} will reach {threshold}% in {seconds_to_threshold}s",
                time_to_issue=seconds_to_threshold,
                confidence=min(0.5 + slope / 10, 0.9),
                recommended_action=self._get_recommended_action(metric_type)
            )
        
        return None
    
    def _predict_from_correlations(
        self,
        store: TimeSeriesStore,
        node_id: str,
        metric_type: MetricType
    ) -> List[PredictiveAlert]:
        """Predict issues based on correlated metrics."""
        # Simplified correlation-based prediction
        # In production, this would use historical correlation data
        
        alerts = []
        
        # Known correlations
        correlations = {
            (MetricType.LATENCY, MetricType.CPU): "High CPU often precedes latency spikes",
            (MetricType.ERROR_RATE, MetricType.MEMORY): "Memory pressure can cause errors",
            (MetricType.QUEUE_LENGTH, MetricType.THROUGHPUT): "Queue buildup affects throughput",
        }
        
        for (metric_a, metric_b), description in correlations.items():
            if metric_type == metric_a:
                series_b = store.get_series(node_id, metric_b, "medium", 20)
                if series_b:
                    recent_b = [p.value for p in series_b[-5:]]
                    if recent_b and statistics.mean(recent_b) > 70:  # High value
                        alerts.append(PredictiveAlert(
                            timestamp=time.time(),
                            metric_type=metric_type,
                            node_id=node_id,
                            prediction=description,
                            time_to_issue=300,  # 5 minutes
                            confidence=0.6,
                            recommended_action=f"Monitor {metric_b.value} closely"
                        ))
        
        return alerts
    
    def _get_recommended_action(self, metric_type: MetricType) -> str:
        """Get recommended action for metric type."""
        actions = {
            MetricType.CPU: "Consider scaling up or optimizing CPU-intensive operations",
            MetricType.MEMORY: "Clear caches or increase memory allocation",
            MetricType.LATENCY: "Check network conditions and reduce request complexity",
            MetricType.ERROR_RATE: "Review error logs and check service dependencies",
            MetricType.QUEUE_LENGTH: "Scale consumers or implement backpressure",
            MetricType.LOCK_CONTENTION: "Review locking strategy and reduce critical sections",
        }
        return actions.get(metric_type, "Investigate and take appropriate action")

# =============================================================================
# Telemetry Service
# =============================================================================

class TelemetryService:
    """Main telemetry service."""
    
    def __init__(self):
        self.store = TimeSeriesStore()
        self.detector = AnomalyDetector()
        self.predictor = PredictiveAnalyzer()
        
        self.anomalies: List[Anomaly] = []
        self.alerts: List[PredictiveAlert] = []
        self.nodes_seen: set = set()
        
        # Adaptive sampling
        self.sampling_rate = 1.0  # 100%
        self.last_cpu_check = 0
    
    async def report_metrics(self, report: MetricReport):
        """Process incoming metric report."""
        timestamp = report.timestamp or time.time()
        self.nodes_seen.add(report.node_id)
        
        # Adaptive sampling
        if random.random() > self.sampling_rate:
            return  # Skip this sample
        
        for metric_name, value in report.metrics.items():
            try:
                metric_type = MetricType(metric_name)
            except ValueError:
                continue
            
            point = MetricPoint(
                timestamp=timestamp,
                value=value,
                node_id=report.node_id,
                metric_type=metric_type
            )
            
            self.store.store(point)
        
        # Run anomaly detection periodically
        await self._check_anomalies(report.node_id)
    
    async def _check_anomalies(self, node_id: str):
        """Check for anomalies on a node."""
        for metric_type in MetricType:
            series = self.store.get_series(node_id, metric_type, "high", 100)
            
            if series:
                anomalies = self.detector.detect(series)
                self.anomalies.extend(anomalies)
                
                # Limit stored anomalies
                if len(self.anomalies) > 1000:
                    self.anomalies = self.anomalies[-500:]
    
    async def generate_predictions(self, node_id: str) -> List[PredictiveAlert]:
        """Generate predictive alerts for a node."""
        alerts = []
        
        for metric_type in MetricType:
            predictions = self.predictor.predict(self.store, node_id, metric_type)
            alerts.extend(predictions)
        
        self.alerts.extend(alerts)
        
        # Limit stored alerts
        if len(self.alerts) > 500:
            self.alerts = self.alerts[-250:]
        
        return alerts
    
    def get_metrics(
        self,
        node_id: str,
        metric_type: MetricType,
        resolution: str = "medium",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get metrics for a node."""
        series = self.store.get_series(node_id, metric_type, resolution, limit)
        return [
            {
                "timestamp": p.timestamp,
                "value": p.value,
                "node_id": p.node_id,
                "metric_type": p.metric_type.value
            }
            for p in series
        ]
    
    def get_anomalies(self, node_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get detected anomalies."""
        anomalies = self.anomalies
        
        if node_id:
            anomalies = [a for a in anomalies if a.node_id == node_id]
        
        return [
            {
                "timestamp": a.timestamp,
                "node_id": a.node_id,
                "metric_type": a.metric_type.value,
                "anomaly_type": a.anomaly_type.value,
                "severity": a.severity.value,
                "value": a.value,
                "expected_range": a.expected_range,
                "description": a.description,
                "confidence": a.confidence
            }
            for a in anomalies[-limit:]
        ]
    
    def get_stats(self) -> TelemetryStats:
        """Get telemetry statistics."""
        store_stats = self.store.get_stats()
        
        return TelemetryStats(
            total_points=store_stats["total_high_freq_points"],
            nodes_monitored=len(self.nodes_seen),
            anomalies_detected=len(self.anomalies),
            alerts_generated=len(self.alerts),
            cpu_usage_percent=self.sampling_rate * MAX_CPU_USAGE * 100
        )

# =============================================================================
# FastAPI Application
# =============================================================================

service: Optional[TelemetryService] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global service
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    service = TelemetryService()
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Predictive Telemetry & Anomaly Detection",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    stats = service.get_stats() if service else None
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "nodes_monitored": stats.nodes_monitored if stats else 0
    }

@app.post("/report")
async def report_metrics(report: MetricReport):
    """Report metrics from a node."""
    await service.report_metrics(report)
    return {"status": "received", "node_id": report.node_id}

@app.get("/metrics/{node_id}/{metric_type}")
async def get_metrics(
    node_id: str,
    metric_type: MetricType,
    resolution: str = "medium",
    limit: int = 100
):
    """Get metrics for a node."""
    return {
        "node_id": node_id,
        "metric_type": metric_type.value,
        "resolution": resolution,
        "data": service.get_metrics(node_id, metric_type, resolution, limit)
    }

@app.get("/anomalies")
async def get_anomalies(node_id: Optional[str] = None, limit: int = 100):
    """Get detected anomalies."""
    return {
        "anomalies": service.get_anomalies(node_id, limit),
        "total": len(service.anomalies)
    }

@app.get("/predictions/{node_id}")
async def get_predictions(node_id: str):
    """Generate and get predictive alerts for a node."""
    alerts = await service.generate_predictions(node_id)
    return {
        "node_id": node_id,
        "predictions": [
            {
                "timestamp": a.timestamp,
                "metric_type": a.metric_type.value,
                "prediction": a.prediction,
                "time_to_issue_seconds": a.time_to_issue,
                "confidence": a.confidence,
                "recommended_action": a.recommended_action
            }
            for a in alerts
        ]
    }

@app.get("/stats")
async def get_stats():
    """Get telemetry statistics."""
    return service.get_stats()

@app.get("/nodes")
async def get_monitored_nodes():
    """Get list of monitored nodes."""
    return {
        "nodes": list(service.nodes_seen),
        "count": len(service.nodes_seen)
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L0_KERNEL",
        "capabilities": ["telemetry", "anomaly_detection", "predictive_alerts"]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8064,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
