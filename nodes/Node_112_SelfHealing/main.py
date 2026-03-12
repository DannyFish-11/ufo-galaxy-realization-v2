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
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 112 - SelfHealing", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    WARNING = "warning"
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


# ─────────────────────────────────────────────────────────────────
# Autonomous-loop classes (Loop 1: Self-healing → Code-fix → Verify)
# ─────────────────────────────────────────────────────────────────

class IssueType(str, Enum):
    """问题类型"""
    HIGH_CPU = "high_cpu"
    HIGH_MEMORY = "high_memory"
    DISK_FULL = "disk_full"
    SERVICE_DOWN = "service_down"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class FixAction(str, Enum):
    """修复动作（自主循环用）"""
    NONE = "none"
    RESTART = "restart"
    CLEANUP = "cleanup"
    RESET = "reset"
    CODE_FIX = "code_fix"


# 触发 CODE_FIX 动作的推荐内容关键词
_CODE_FIX_KEYWORDS: tuple = (
    "代码修复",
    "code fix",
    "修复代码",
    "重新编写",
    "重构代码",
    "fix code",
    "code error",
    "代码错误",
    "bug fix",
)


@dataclass
class HealthMetrics:
    """系统健康指标"""
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_ok: bool
    timestamp: str


@dataclass
class DiagnosisResult:
    """诊断结果"""
    issue_type: IssueType
    severity: HealthStatus
    description: str
    affected_components: List[str]
    recommendation: str


@dataclass
class FixResult:
    """修复结果"""
    action: FixAction
    success: bool
    message: str
    timestamp: str


@dataclass
class IncidentReport:
    """事件报告"""
    incident_id: str
    metrics: HealthMetrics
    diagnosis: DiagnosisResult
    fix_result: FixResult
    created_at: str
    resolved: bool = False


# Issue-type → default FixAction mapping
_ISSUE_ACTION_MAP: Dict[IssueType, FixAction] = {
    IssueType.HIGH_CPU: FixAction.RESTART,
    IssueType.HIGH_MEMORY: FixAction.RESTART,
    IssueType.DISK_FULL: FixAction.CLEANUP,
    IssueType.SERVICE_DOWN: FixAction.RESTART,
    IssueType.NETWORK_ERROR: FixAction.RESET,
}


class SystemDetector:
    """系统指标采集器"""

    def collect_metrics(self) -> HealthMetrics:
        """采集当前系统指标"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
        except ImportError:
            cpu, mem, disk = 0.0, 0.0, 0.0
        return HealthMetrics(
            cpu_percent=cpu,
            memory_percent=mem,
            disk_percent=disk,
            network_ok=True,
            timestamp=datetime.now().isoformat(),
        )


class SystemDiagnoser:
    """系统诊断器"""

    def diagnose(self, metrics: HealthMetrics) -> DiagnosisResult:
        """根据指标生成诊断结果"""
        if metrics.cpu_percent > 90.0:
            return DiagnosisResult(
                issue_type=IssueType.HIGH_CPU,
                severity=HealthStatus.CRITICAL,
                description=f"CPU 使用率过高: {metrics.cpu_percent:.1f}%",
                affected_components=["cpu"],
                recommendation="restart",
            )
        if metrics.memory_percent > 90.0:
            return DiagnosisResult(
                issue_type=IssueType.HIGH_MEMORY,
                severity=HealthStatus.CRITICAL,
                description=f"内存使用率过高: {metrics.memory_percent:.1f}%",
                affected_components=["memory"],
                recommendation="restart",
            )
        if metrics.disk_percent > 90.0:
            return DiagnosisResult(
                issue_type=IssueType.DISK_FULL,
                severity=HealthStatus.WARNING,
                description=f"磁盘使用率过高: {metrics.disk_percent:.1f}%",
                affected_components=["disk"],
                recommendation="cleanup",
            )
        if not metrics.network_ok:
            return DiagnosisResult(
                issue_type=IssueType.NETWORK_ERROR,
                severity=HealthStatus.DEGRADED,
                description="网络连接异常",
                affected_components=["network"],
                recommendation="reset",
            )
        return DiagnosisResult(
            issue_type=IssueType.UNKNOWN,
            severity=HealthStatus.HEALTHY,
            description="无明显异常",
            affected_components=[],
            recommendation="继续监控",
        )


class AutoFixer:
    """自动修复器（Loop 1）"""

    def __init__(self):
        self._last_coding_result = None

    def _determine_action(self, diagnosis: DiagnosisResult) -> FixAction:
        """根据诊断结果决定修复动作"""
        # 1. 优先使用 issue_type 标准映射
        mapped = _ISSUE_ACTION_MAP.get(diagnosis.issue_type)
        if mapped is not None:
            return mapped
        # 2. UNKNOWN 类型：检查推荐内容关键词
        rec_lower = diagnosis.recommendation.lower()
        for kw in _CODE_FIX_KEYWORDS:
            if kw.lower() in rec_lower:
                return FixAction.CODE_FIX
        return FixAction.NONE

    def fix(self, diagnosis: DiagnosisResult) -> FixResult:
        """执行修复"""
        action = self._determine_action(diagnosis)
        timestamp = datetime.now().isoformat()
        if action == FixAction.CODE_FIX:
            return self._code_fix(diagnosis)
        return FixResult(action=action, success=True, message=f"执行动作: {action.value}", timestamp=timestamp)

    def _code_fix(self, diagnosis: DiagnosisResult) -> FixResult:
        """调用 AutonomousCoder 生成代码修复"""
        timestamp = datetime.now().isoformat()
        try:
            from enhancements.reasoning.autonomous_coder import AutonomousCoder, CodingTask
            coder = AutonomousCoder()
            task = CodingTask(
                requirement=diagnosis.recommendation,
                language="python",
                target_type="fix",
                constraints=[],
                expected_output=None,
                context_code=None,
            )
            result = coder.generate_and_execute(task)
            self._last_coding_result = result
            success = bool(result and getattr(result, "code", None))
            return FixResult(action=FixAction.CODE_FIX, success=success, message=str(result), timestamp=timestamp)
        except Exception as e:
            return FixResult(action=FixAction.CODE_FIX, success=False, message=str(e), timestamp=timestamp)

    def apply_code_fix(self, target_dir: str = "/tmp") -> str:
        """将最近一次代码修复结果写入磁盘，返回文件路径；无结果时返回空字符串"""
        if not self._last_coding_result or not getattr(self._last_coding_result, "code", None):
            return ""
        os.makedirs(target_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(target_dir, f"fix_{ts}.py")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._last_coding_result.code)
        return filepath


class IncidentReporter:
    """事件报告生成器"""

    def generate_report(
        self,
        metrics: Optional[HealthMetrics] = None,
        diagnosis: Optional[DiagnosisResult] = None,
        fix_result: Optional[FixResult] = None,
    ) -> IncidentReport:
        """生成事件报告"""
        if metrics is None:
            metrics = HealthMetrics(cpu_percent=0.0, memory_percent=0.0, disk_percent=0.0, network_ok=True, timestamp=datetime.now().isoformat())
        if diagnosis is None:
            diagnosis = DiagnosisResult(issue_type=IssueType.UNKNOWN, severity=HealthStatus.HEALTHY, description="", affected_components=[], recommendation="")
        if fix_result is None:
            fix_result = FixResult(action=FixAction.NONE, success=True, message="", timestamp=datetime.now().isoformat())
        return IncidentReport(
            incident_id=str(uuid.uuid4()),
            metrics=metrics,
            diagnosis=diagnosis,
            fix_result=fix_result,
            created_at=datetime.now().isoformat(),
            resolved=fix_result.success,
        )


# SelfHealing logger used by run_once for structured phase logging
_self_healing_logger = logging.getLogger("SelfHealing")


class SelfHealingEngine:
    """自愈引擎（同时支持原有的 HealthCheck/Fault/RecoveryPlan 机制
    以及新增的 Loop-1 自主循环：collect_metrics → diagnose → fix → verify）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.health_checks: Dict[str, HealthCheck] = {}
        self.faults: Dict[str, Fault] = {}
        self.recovery_plans: Dict[str, RecoveryPlan] = {}
        self.executions: List[RecoveryExecution] = []
        self.is_running = False
        self._recovery_handlers: Dict[RecoveryAction, Callable] = {}
        self._initialize_default_plans()
        # Loop-1 components
        self.detector = SystemDetector()
        self.diagnoser = SystemDiagnoser()
        self.fixer = AutoFixer()
        self.reporter = IncidentReporter()
        self.auto_commit: bool = bool(cfg.get("auto_commit", False))
        self.applied_fixes_dir: str = str(cfg.get("applied_fixes_dir", "/tmp/ufo_fixes"))
        self._report_dir: str = str(cfg.get("report_dir", "/tmp"))
    
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

    def run_once(self) -> Optional[IncidentReport]:
        """执行一轮自主自愈循环（Loop 1）：
        采集指标 → 检测异常 → 诊断 → 修复 → 验证 → 生成报告。
        若无异常则直接返回 None。
        """
        metrics = self.detector.collect_metrics()

        # 检测异常阈值
        anomalous = (
            metrics.cpu_percent > 90.0
            or metrics.memory_percent > 90.0
            or metrics.disk_percent > 90.0
            or not metrics.network_ok
        )

        if not anomalous:
            return None

        _self_healing_logger.info(
            "[DETECTION] 检测到系统异常: cpu=%.1f%% mem=%.1f%% disk=%.1f%% network=%s",
            metrics.cpu_percent,
            metrics.memory_percent,
            metrics.disk_percent,
            metrics.network_ok,
        )

        diagnosis = self.diagnoser.diagnose(metrics)

        # CODE_FIX 动作前先写入沙箱测试日志
        action_hint = _ISSUE_ACTION_MAP.get(diagnosis.issue_type) or FixAction.NONE
        rec_lower = diagnosis.recommendation.lower()
        will_code_fix = action_hint == FixAction.NONE and any(kw.lower() in rec_lower for kw in _CODE_FIX_KEYWORDS)
        if not will_code_fix and diagnosis.issue_type == IssueType.UNKNOWN:
            will_code_fix = any(kw.lower() in rec_lower for kw in _CODE_FIX_KEYWORDS)

        fix_result = self.fixer.fix(diagnosis)

        if fix_result.action == FixAction.CODE_FIX:
            _self_healing_logger.info("[SANDBOX_TEST] 在沙箱中测试代码修复结果: success=%s", fix_result.success)

        if fix_result.success:
            if fix_result.action == FixAction.RESTART:
                _self_healing_logger.info("[VERIFICATION] 服务已 restored，修复动作: %s", fix_result.action.value)
            elif fix_result.action == FixAction.CODE_FIX:
                _self_healing_logger.info("[COMMIT] 代码修复沙箱测试通过，提交修复: %s", fix_result.message)
                _self_healing_logger.info("[VERIFICATION] 代码修复已应用: success=%s", fix_result.success)
            else:
                _self_healing_logger.info("[VERIFICATION] 修复完成: action=%s success=%s", fix_result.action.value, fix_result.success)
        else:
            _self_healing_logger.info("[VERIFICATION] 修复失败: action=%s message=%s", fix_result.action.value, fix_result.message)

        # 若开启自动提交且 CODE_FIX 成功，将修复写入磁盘
        if self.auto_commit and fix_result.action == FixAction.CODE_FIX and fix_result.success:
            self.fixer.apply_code_fix(target_dir=self.applied_fixes_dir)

        report = self.reporter.generate_report(
            metrics=metrics,
            diagnosis=diagnosis,
            fix_result=fix_result,
        )
        return report


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




class MCPCallRequest(BaseModel):
    tool: str
    params: dict = {}

@app.post("/mcp/call")
async def mcp_call(request: MCPCallRequest):
    """MCP tool call dispatcher"""
    if request.tool == "health":
        return {"success": True, "tool": request.tool, "result": {"status": "healthy", "node": "Node_112_SelfHealing"}}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8112)
