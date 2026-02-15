"""
Node 112 - SelfHealing (自愈节点)
提供系统自动故障检测、诊断和恢复能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 112 - SelfHealing", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class FaultType(str, Enum):
    """故障类型"""
    CONNECTIVITY = "connectivity"
    PERFORMANCE = "performance"
    RESOURCE = "resource"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    DATA = "data"
    SECURITY = "security"


class RecoveryAction(str, Enum):
    """恢复动作"""
    RESTART = "restart"
    RECONNECT = "reconnect"
    RECONFIGURE = "reconfigure"
    SCALE = "scale"
    FAILOVER = "failover"
    ROLLBACK = "rollback"
    NOTIFY = "notify"


@dataclass
class HealthCheck:
    """健康检查"""
    check_id: str
    target: str
    check_type: str
    interval: int  # 秒
    timeout: int   # 秒
    enabled: bool = True
    last_check: Optional[datetime] = None
    last_status: HealthStatus = HealthStatus.UNKNOWN
    consecutive_failures: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Fault:
    """故障记录"""
    fault_id: str
    fault_type: FaultType
    target: str
    description: str
    severity: int  # 1-5
    detected_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    recovery_attempts: int = 0
    is_resolved: bool = False
    root_cause: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryPlan:
    """恢复计划"""
    plan_id: str
    fault_type: FaultType
    target_pattern: str
    actions: List[RecoveryAction]
    max_attempts: int = 3
    cooldown: int = 60  # 秒
    enabled: bool = True
    success_count: int = 0
    failure_count: int = 0


@dataclass
class RecoveryExecution:
    """恢复执行记录"""
    execution_id: str
    fault_id: str
    plan_id: str
    actions_executed: List[str]
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    success: bool = False
    error: Optional[str] = None


class SelfHealingEngine:
    """自愈引擎"""
    
    def __init__(self):
        self.health_checks: Dict[str, HealthCheck] = {}
        self.faults: Dict[str, Fault] = {}
        self.recovery_plans: Dict[str, RecoveryPlan] = {}
        self.executions: List[RecoveryExecution] = []
        self.is_running = False
        self._recovery_handlers: Dict[RecoveryAction, Callable] = {}
        self._initialize_default_plans()
    
    def _initialize_default_plans(self):
        """初始化默认恢复计划"""
        default_plans = [
            RecoveryPlan(
                plan_id="connectivity_recovery",
                fault_type=FaultType.CONNECTIVITY,
                target_pattern="*",
                actions=[RecoveryAction.RECONNECT, RecoveryAction.RESTART, RecoveryAction.NOTIFY]
            ),
            RecoveryPlan(
                plan_id="performance_recovery",
                fault_type=FaultType.PERFORMANCE,
                target_pattern="*",
                actions=[RecoveryAction.SCALE, RecoveryAction.RESTART, RecoveryAction.NOTIFY]
            ),
            RecoveryPlan(
                plan_id="resource_recovery",
                fault_type=FaultType.RESOURCE,
                target_pattern="*",
                actions=[RecoveryAction.SCALE, RecoveryAction.NOTIFY]
            ),
            RecoveryPlan(
                plan_id="configuration_recovery",
                fault_type=FaultType.CONFIGURATION,
                target_pattern="*",
                actions=[RecoveryAction.RECONFIGURE, RecoveryAction.ROLLBACK, RecoveryAction.NOTIFY]
            ),
        ]
        for plan in default_plans:
            self.recovery_plans[plan.plan_id] = plan
    
    def register_health_check(self, check: HealthCheck) -> bool:
        """注册健康检查"""
        self.health_checks[check.check_id] = check
        logger.info(f"Registered health check: {check.check_id} for {check.target}")
        return True
    
    def unregister_health_check(self, check_id: str) -> bool:
        """注销健康检查"""
        if check_id in self.health_checks:
            del self.health_checks[check_id]
            return True
        return False
    
    async def run_health_check(self, check_id: str) -> HealthStatus:
        """运行健康检查"""
        if check_id not in self.health_checks:
            return HealthStatus.UNKNOWN
        
        check = self.health_checks[check_id]
        
        try:
            status = await self._perform_check(check)
            
            check.last_check = datetime.now()
            check.last_status = status
            
            if status in [HealthStatus.UNHEALTHY, HealthStatus.CRITICAL]:
                check.consecutive_failures += 1
                
                # 检测到故障
                if check.consecutive_failures >= 3:
                    await self._detect_fault(check)
            else:
                check.consecutive_failures = 0
            
            return status
            
        except Exception as e:
            logger.error(f"Health check {check_id} failed: {e}")
            check.consecutive_failures += 1
            check.last_status = HealthStatus.UNKNOWN
            return HealthStatus.UNKNOWN
    
    async def _perform_check(self, check: HealthCheck) -> HealthStatus:
        """执行健康检查"""
        check_type = check.check_type
        
        if check_type == "http":
            return await self._http_check(check)
        elif check_type == "tcp":
            return await self._tcp_check(check)
        elif check_type == "process":
            return await self._process_check(check)
        elif check_type == "resource":
            return await self._resource_check(check)
        else:
            # 默认检查
            return HealthStatus.HEALTHY
    
    async def _http_check(self, check: HealthCheck) -> HealthStatus:
        """HTTP 健康检查"""
        import aiohttp
        url = check.metadata.get("url", f"http://{check.target}/health")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=check.timeout) as response:
                    if response.status == 200:
                        return HealthStatus.HEALTHY
                    elif response.status < 500:
                        return HealthStatus.DEGRADED
                    else:
                        return HealthStatus.UNHEALTHY
        except Exception:
            return HealthStatus.UNHEALTHY
    
    async def _tcp_check(self, check: HealthCheck) -> HealthStatus:
        """TCP 连接检查"""
        host = check.metadata.get("host", check.target)
        port = check.metadata.get("port", 80)
        
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=check.timeout
            )
            writer.close()
            await writer.wait_closed()
            return HealthStatus.HEALTHY
        except (OSError, asyncio.TimeoutError):
            return HealthStatus.UNHEALTHY
    
    async def _process_check(self, check: HealthCheck) -> HealthStatus:
        """进程检查"""
        process_name = check.metadata.get("process_name", check.target)
        
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if process_name.lower() in proc.info['name'].lower():
                    return HealthStatus.HEALTHY
            return HealthStatus.UNHEALTHY
        except Exception:
            return HealthStatus.UNKNOWN
    
    async def _resource_check(self, check: HealthCheck) -> HealthStatus:
        """资源检查"""
        try:
            import psutil
            
            cpu_threshold = check.metadata.get("cpu_threshold", 90)
            mem_threshold = check.metadata.get("mem_threshold", 90)
            disk_threshold = check.metadata.get("disk_threshold", 90)
            
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            
            if cpu > cpu_threshold or mem > mem_threshold or disk > disk_threshold:
                return HealthStatus.CRITICAL
            elif cpu > cpu_threshold * 0.8 or mem > mem_threshold * 0.8:
                return HealthStatus.DEGRADED
            return HealthStatus.HEALTHY
        except Exception:
            return HealthStatus.UNKNOWN
    
    async def _detect_fault(self, check: HealthCheck):
        """检测故障"""
        fault = Fault(
            fault_id=str(uuid.uuid4()),
            fault_type=self._determine_fault_type(check),
            target=check.target,
            description=f"Health check {check.check_id} failed {check.consecutive_failures} times",
            severity=self._calculate_severity(check)
        )
        
        self.faults[fault.fault_id] = fault
        logger.warning(f"Fault detected: {fault.fault_id} - {fault.description}")
        
        # 触发自动恢复
        await self.attempt_recovery(fault.fault_id)
    
    def _determine_fault_type(self, check: HealthCheck) -> FaultType:
        """确定故障类型"""
        check_type = check.check_type
        if check_type in ["http", "tcp"]:
            return FaultType.CONNECTIVITY
        elif check_type == "resource":
            return FaultType.RESOURCE
        elif check_type == "process":
            return FaultType.DEPENDENCY
        return FaultType.CONNECTIVITY
    
    def _calculate_severity(self, check: HealthCheck) -> int:
        """计算故障严重程度"""
        if check.last_status == HealthStatus.CRITICAL:
            return 5
        elif check.last_status == HealthStatus.UNHEALTHY:
            return 4
        elif check.consecutive_failures > 10:
            return 4
        elif check.consecutive_failures > 5:
            return 3
        return 2
    
    def add_recovery_plan(self, plan: RecoveryPlan) -> bool:
        """添加恢复计划"""
        self.recovery_plans[plan.plan_id] = plan
        logger.info(f"Added recovery plan: {plan.plan_id}")
        return True
    
    def register_recovery_handler(self, action: RecoveryAction, handler: Callable):
        """注册恢复处理器"""
        self._recovery_handlers[action] = handler
    
    async def attempt_recovery(self, fault_id: str) -> bool:
        """尝试恢复"""
        if fault_id not in self.faults:
            return False
        
        fault = self.faults[fault_id]
        
        if fault.is_resolved:
            return True
        
        # 查找匹配的恢复计划
        plan = self._find_recovery_plan(fault)
        if not plan:
            logger.warning(f"No recovery plan found for fault {fault_id}")
            return False
        
        # 检查是否超过最大尝试次数
        if fault.recovery_attempts >= plan.max_attempts:
            logger.error(f"Max recovery attempts reached for fault {fault_id}")
            return False
        
        fault.recovery_attempts += 1
        
        # 创建执行记录
        execution = RecoveryExecution(
            execution_id=str(uuid.uuid4()),
            fault_id=fault_id,
            plan_id=plan.plan_id,
            actions_executed=[]
        )
        
        try:
            # 执行恢复动作
            for action in plan.actions:
                success = await self._execute_recovery_action(action, fault)
                execution.actions_executed.append(f"{action.value}:{success}")
                
                if success:
                    # 验证恢复是否成功
                    if await self._verify_recovery(fault):
                        fault.is_resolved = True
                        fault.resolved_at = datetime.now()
                        execution.success = True
                        plan.success_count += 1
                        logger.info(f"Fault {fault_id} recovered successfully")
                        break
            
            if not execution.success:
                plan.failure_count += 1
            
        except Exception as e:
            execution.error = str(e)
            logger.error(f"Recovery failed for fault {fault_id}: {e}")
        
        execution.completed_at = datetime.now()
        self.executions.append(execution)
        
        return execution.success
    
    def _find_recovery_plan(self, fault: Fault) -> Optional[RecoveryPlan]:
        """查找恢复计划"""
        for plan in self.recovery_plans.values():
            if not plan.enabled:
                continue
            if plan.fault_type != fault.fault_type:
                continue
            if plan.target_pattern == "*" or plan.target_pattern in fault.target:
                return plan
        return None
    
    async def _execute_recovery_action(self, action: RecoveryAction, fault: Fault) -> bool:
        """执行恢复动作"""
        handler = self._recovery_handlers.get(action)
        
        if handler:
            try:
                return await handler(fault)
            except Exception as e:
                logger.error(f"Recovery action {action} failed: {e}")
                return False
        
        # 默认处理
        if action == RecoveryAction.RESTART:
            return await self._default_restart(fault)
        elif action == RecoveryAction.RECONNECT:
            return await self._default_reconnect(fault)
        elif action == RecoveryAction.NOTIFY:
            return await self._default_notify(fault)
        elif action == RecoveryAction.SCALE:
            return await self._default_scale(fault)
        
        return False
    
    async def _default_restart(self, fault: Fault) -> bool:
        """默认重启处理"""
        logger.info(f"Attempting restart for {fault.target}")
        await asyncio.sleep(1)  # 模拟重启
        return True
    
    async def _default_reconnect(self, fault: Fault) -> bool:
        """默认重连处理"""
        logger.info(f"Attempting reconnect for {fault.target}")
        await asyncio.sleep(0.5)  # 模拟重连
        return True
    
    async def _default_notify(self, fault: Fault) -> bool:
        """默认通知处理"""
        logger.info(f"Sending notification for fault: {fault.fault_id}")
        return True
    
    async def _default_scale(self, fault: Fault) -> bool:
        """默认扩容处理"""
        logger.info(f"Attempting scale for {fault.target}")
        return True
    
    async def _verify_recovery(self, fault: Fault) -> bool:
        """验证恢复是否成功"""
        # 查找相关的健康检查
        for check in self.health_checks.values():
            if check.target == fault.target:
                status = await self.run_health_check(check.check_id)
                return status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        return True  # 如果没有健康检查，假设成功
    
    async def start(self):
        """启动自愈引擎"""
        self.is_running = True
        logger.info("Self-healing engine started")
        
        while self.is_running:
            for check_id, check in list(self.health_checks.items()):
                if not check.enabled:
                    continue
                
                if check.last_check is None or \
                   (datetime.now() - check.last_check).total_seconds() >= check.interval:
                    await self.run_health_check(check_id)
            
            await asyncio.sleep(5)
    
    def stop(self):
        """停止自愈引擎"""
        self.is_running = False
        logger.info("Self-healing engine stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        return {
            "is_running": self.is_running,
            "health_checks": len(self.health_checks),
            "active_faults": sum(1 for f in self.faults.values() if not f.is_resolved),
            "resolved_faults": sum(1 for f in self.faults.values() if f.is_resolved),
            "recovery_plans": len(self.recovery_plans),
            "total_recoveries": len(self.executions),
            "successful_recoveries": sum(1 for e in self.executions if e.success)
        }


# 全局实例
healing_engine = SelfHealingEngine()


# API 模型
class RegisterHealthCheckRequest(BaseModel):
    check_id: str
    target: str
    check_type: str
    interval: int = 30
    timeout: int = 10
    metadata: Dict[str, Any] = {}

class AddRecoveryPlanRequest(BaseModel):
    plan_id: str
    fault_type: str
    target_pattern: str
    actions: List[str]
    max_attempts: int = 3

class ReportFaultRequest(BaseModel):
    fault_type: str
    target: str
    description: str
    severity: int = 3


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_112_SelfHealing"}

@app.get("/status")
async def get_status():
    return healing_engine.get_status()

@app.post("/checks")
async def register_check(request: RegisterHealthCheckRequest):
    check = HealthCheck(
        check_id=request.check_id,
        target=request.target,
        check_type=request.check_type,
        interval=request.interval,
        timeout=request.timeout,
        metadata=request.metadata
    )
    healing_engine.register_health_check(check)
    return {"success": True}

@app.get("/checks")
async def list_checks():
    return {cid: asdict(c) for cid, c in healing_engine.health_checks.items()}

@app.post("/checks/{check_id}/run")
async def run_check(check_id: str):
    status = await healing_engine.run_health_check(check_id)
    return {"status": status.value}

@app.get("/faults")
async def list_faults(resolved: Optional[bool] = None):
    faults = list(healing_engine.faults.values())
    if resolved is not None:
        faults = [f for f in faults if f.is_resolved == resolved]
    return [asdict(f) for f in faults]

@app.post("/faults")
async def report_fault(request: ReportFaultRequest):
    fault = Fault(
        fault_id=str(uuid.uuid4()),
        fault_type=FaultType(request.fault_type),
        target=request.target,
        description=request.description,
        severity=request.severity
    )
    healing_engine.faults[fault.fault_id] = fault
    return {"fault_id": fault.fault_id}

@app.post("/faults/{fault_id}/recover")
async def recover_fault(fault_id: str):
    success = await healing_engine.attempt_recovery(fault_id)
    return {"success": success}

@app.post("/plans")
async def add_plan(request: AddRecoveryPlanRequest):
    plan = RecoveryPlan(
        plan_id=request.plan_id,
        fault_type=FaultType(request.fault_type),
        target_pattern=request.target_pattern,
        actions=[RecoveryAction(a) for a in request.actions],
        max_attempts=request.max_attempts
    )
    healing_engine.add_recovery_plan(plan)
    return {"success": True}

@app.get("/plans")
async def list_plans():
    return {pid: asdict(p) for pid, p in healing_engine.recovery_plans.items()}

@app.get("/executions")
async def list_executions(limit: int = 50):
    executions = sorted(healing_engine.executions, key=lambda e: e.started_at, reverse=True)[:limit]
    return [asdict(e) for e in executions]

@app.post("/start")
async def start_engine(background_tasks: BackgroundTasks):
    if not healing_engine.is_running:
        background_tasks.add_task(healing_engine.start)
        return {"status": "started"}
    return {"status": "already_running"}

@app.post("/stop")
async def stop_engine():
    healing_engine.stop()
    return {"status": "stopped"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8112)
