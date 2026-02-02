"""
Node_109_ProactiveSensing - FastAPI Server
主动感知节点服务器
"""

import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import uvicorn

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.proactive_sensing_engine import (
    ProactiveSensingEngine,
    AlertLevel,
    OpportunityType,
    AnomalyType,
    EnvironmentState
)

# ========== 配置 ==========
NODE_PORT = int(os.getenv("NODE_109_PORT", "9101"))
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="Node_109_ProactiveSensing",
    description="主动感知节点 - 主动发现环境变化、潜在问题和优化机会",
    version="0.1.0"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 全局引擎实例 ==========
engine = ProactiveSensingEngine()

# ========== Pydantic 模型 ==========

class ScanEnvironmentResponse(BaseModel):
    """扫描环境响应"""
    timestamp: float
    metrics: Dict[str, Any]
    events: List[Dict[str, Any]]
    context: Dict[str, Any]

class DetectAnomaliesRequest(BaseModel):
    """检测异常请求"""
    current_state: Optional[Dict[str, Any]] = Field(None, description="当前状态，None 则使用最新状态")

class DiscoverOpportunitiesRequest(BaseModel):
    """发现机会请求"""
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="上下文信息")

class CreateAlertRequest(BaseModel):
    """创建预警请求"""
    level: str = Field(..., description="预警级别: info/warning/critical")
    title: str = Field(..., description="标题")
    description: str = Field(..., description="描述")
    source: str = Field(..., description="来源")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")

class AcknowledgeAlertRequest(BaseModel):
    """确认预警请求"""
    alert_id: str = Field(..., description="预警ID")

class RegisterMonitorRequest(BaseModel):
    """注册监控器请求"""
    name: str = Field(..., description="监控器名称")
    endpoint: str = Field(..., description="监控器端点 URL")

# ========== API 端点 ==========

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_109_ProactiveSensing",
        "status": "running",
        "version": "0.1.0",
        "description": "主动感知节点 - 主动发现环境变化、潜在问题和优化机会"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "monitors_count": len(engine.monitors),
        "active_alerts_count": len(engine.get_active_alerts()),
        "opportunities_count": len(engine.opportunities),
        "anomalies_count": len(engine.anomalies)
    }

@app.post("/api/v1/scan_environment", response_model=ScanEnvironmentResponse)
async def scan_environment():
    """
    扫描环境状态
    
    Returns:
        ScanEnvironmentResponse: 环境状态
    """
    try:
        state = engine.scan_environment()
        return ScanEnvironmentResponse(
            timestamp=state.timestamp,
            metrics=state.metrics,
            events=state.events,
            context=state.context
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/detect_anomalies", response_model=List[Dict[str, Any]])
async def detect_anomalies(request: DetectAnomaliesRequest):
    """
    检测异常
    
    Args:
        request: 检测异常请求
        
    Returns:
        List[Dict]: 检测到的异常列表
    """
    try:
        current_state = None
        if request.current_state:
            current_state = EnvironmentState(
                metrics=request.current_state.get("metrics", {}),
                events=request.current_state.get("events", []),
                context=request.current_state.get("context", {})
            )
        
        anomalies = engine.detect_anomalies(current_state=current_state)
        return [a.to_dict() for a in anomalies]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/discover_opportunities", response_model=List[Dict[str, Any]])
async def discover_opportunities(request: DiscoverOpportunitiesRequest):
    """
    发现机会
    
    Args:
        request: 发现机会请求
        
    Returns:
        List[Dict]: 发现的机会列表
    """
    try:
        opportunities = engine.discover_opportunities(context=request.context)
        return [o.to_dict() for o in opportunities]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/create_alert", response_model=Dict[str, Any])
async def create_alert(request: CreateAlertRequest):
    """
    创建预警
    
    Args:
        request: 创建预警请求
        
    Returns:
        Dict: 预警信息
    """
    try:
        # 验证预警级别
        try:
            level = AlertLevel(request.level)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid level. Must be one of: {[l.value for l in AlertLevel]}"
            )
        
        alert = engine.create_alert(
            level=level,
            title=request.title,
            description=request.description,
            source=request.source,
            metadata=request.metadata
        )
        
        return alert.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/acknowledge_alert", response_model=Dict[str, bool])
async def acknowledge_alert(request: AcknowledgeAlertRequest):
    """
    确认预警
    
    Args:
        request: 确认预警请求
        
    Returns:
        Dict: 确认结果
    """
    try:
        success = engine.acknowledge_alert(request.alert_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Alert {request.alert_id} not found")
        return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/alerts", response_model=List[Dict[str, Any]])
async def get_alerts(active_only: bool = True):
    """
    获取预警列表
    
    Args:
        active_only: 是否只返回未确认的预警
        
    Returns:
        List[Dict]: 预警列表
    """
    try:
        if active_only:
            alerts = engine.get_active_alerts()
        else:
            alerts = engine.alerts
        return [a.to_dict() for a in alerts]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/opportunities", response_model=List[Dict[str, Any]])
async def get_opportunities(limit: int = 10):
    """
    获取机会列表
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 机会列表（按优先级排序）
    """
    try:
        opportunities = engine.get_recent_opportunities(limit=limit)
        return [o.to_dict() for o in opportunities]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/anomalies", response_model=List[Dict[str, Any]])
async def get_anomalies(limit: int = 10):
    """
    获取异常列表
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 异常列表
    """
    try:
        anomalies = engine.get_recent_anomalies(limit=limit)
        return [a.to_dict() for a in anomalies]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/state_history", response_model=List[Dict[str, Any]])
async def get_state_history(limit: int = 100):
    """
    获取状态历史
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 状态历史
    """
    try:
        states = engine.state_history[-limit:]
        return [s.to_dict() for s in states]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/register_monitor", response_model=Dict[str, str])
async def register_monitor(request: RegisterMonitorRequest):
    """
    注册监控器
    
    Args:
        request: 注册监控器请求
        
    Returns:
        Dict: 注册结果
    """
    try:
        # 创建监控器函数（简化实现：返回静态数据）
        def monitor_func():
            return {"status": "ok", "endpoint": request.endpoint}
        
        engine.register_monitor(request.name, monitor_func)
        
        return {
            "status": "registered",
            "monitor_name": request.name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/monitors", response_model=Dict[str, List[str]])
async def get_monitors():
    """
    获取已注册的监控器列表
    
    Returns:
        Dict: 监控器列表
    """
    try:
        return {"monitors": list(engine.monitors.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 主函数 ==========

if __name__ == "__main__":
    print(f"🚀 Starting Node_109_ProactiveSensing on {NODE_HOST}:{NODE_PORT}")
    print(f"📚 API Documentation: http://{NODE_HOST}:{NODE_PORT}/docs")
    
    uvicorn.run(
        app,
        host=NODE_HOST,
        port=NODE_PORT,
        log_level="info"
    )
