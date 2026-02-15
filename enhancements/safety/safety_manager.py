"""
安全管理器 (Safety Manager)
负责错误处理、故障恢复和安全检查
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    """安全级别"""
    LOW = "low"  # 低风险操作
    MEDIUM = "medium"  # 中等风险操作
    HIGH = "high"  # 高风险操作
    CRITICAL = "critical"  # 关键风险操作


class RecoveryStrategy(Enum):
    """恢复策略"""
    RETRY = "retry"  # 重试
    FALLBACK = "fallback"  # 后备方案
    SKIP = "skip"  # 跳过
    ABORT = "abort"  # 中止
    MANUAL = "manual"  # 手动介入


@dataclass
class SafetyRule:
    """安全规则"""
    rule_id: str
    name: str
    description: str
    check_function: Callable
    level: SafetyLevel
    enabled: bool = True


@dataclass
class SafetyViolation:
    """安全违规"""
    timestamp: float
    rule_id: str
    rule_name: str
    level: SafetyLevel
    message: str
    context: Dict = field(default_factory=dict)


@dataclass
class RecoveryAction:
    """恢复动作"""
    action_id: str
    strategy: RecoveryStrategy
    description: str
    execute_function: Callable
    max_retries: int = 3
    retry_delay: float = 1.0


class SafetyManager:
    """安全管理器"""
    
    def __init__(self):
        """初始化安全管理器"""
        self.safety_rules: Dict[str, SafetyRule] = {}
        self.recovery_actions: Dict[str, RecoveryAction] = {}
        self.violations: List[SafetyViolation] = []
        self.recovery_history: List[Dict] = []
        
        # 初始化默认安全规则
        self._initialize_default_rules()
        
        logger.info("SafetyManager 初始化完成")
    
    def _initialize_default_rules(self):
        """初始化默认安全规则"""
        # 规则 1: 电池电量检查
        self.register_safety_rule(SafetyRule(
            rule_id="battery_check",
            name="电池电量检查",
            description="确保设备电池电量充足",
            check_function=self._check_battery_level,
            level=SafetyLevel.HIGH
        ))
        
        # 规则 2: GPS 信号检查
        self.register_safety_rule(SafetyRule(
            rule_id="gps_check",
            name="GPS 信号检查",
            description="确保 GPS 信号正常",
            check_function=self._check_gps_signal,
            level=SafetyLevel.HIGH
        ))
        
        # 规则 3: 温度检查
        self.register_safety_rule(SafetyRule(
            rule_id="temperature_check",
            name="温度检查",
            description="确保设备温度在安全范围内",
            check_function=self._check_temperature,
            level=SafetyLevel.MEDIUM
        ))
        
        # 规则 4: 连接状态检查
        self.register_safety_rule(SafetyRule(
            rule_id="connection_check",
            name="连接状态检查",
            description="确保设备连接正常",
            check_function=self._check_connection,
            level=SafetyLevel.HIGH
        ))
        
        # 规则 5: 高度限制检查
        self.register_safety_rule(SafetyRule(
            rule_id="altitude_limit_check",
            name="高度限制检查",
            description="确保飞行高度在安全范围内",
            check_function=self._check_altitude_limit,
            level=SafetyLevel.CRITICAL
        ))
    
    def register_safety_rule(self, rule: SafetyRule):
        """注册安全规则"""
        self.safety_rules[rule.rule_id] = rule
        logger.info(f"注册安全规则: {rule.name} ({rule.level.value})")
    
    def register_recovery_action(self, action: RecoveryAction):
        """注册恢复动作"""
        self.recovery_actions[action.action_id] = action
        logger.info(f"注册恢复动作: {action.description} ({action.strategy.value})")
    
    async def check_safety(self, context: Dict[str, Any]) -> tuple[bool, List[SafetyViolation]]:
        """
        执行安全检查
        
        Args:
            context: 检查上下文，包含设备状态等信息
        
        Returns:
            (是否安全, 违规列表)
        """
        logger.info("执行安全检查...")
        
        violations = []
        
        for rule_id, rule in self.safety_rules.items():
            if not rule.enabled:
                continue
            
            try:
                # 执行检查函数
                is_safe, message = await rule.check_function(context)
                
                if not is_safe:
                    violation = SafetyViolation(
                        timestamp=time.time(),
                        rule_id=rule_id,
                        rule_name=rule.name,
                        level=rule.level,
                        message=message,
                        context=context.copy()
                    )
                    violations.append(violation)
                    self.violations.append(violation)
                    
                    logger.warning(f"安全检查失败: {rule.name} - {message}")
            
            except Exception as e:
                logger.error(f"安全检查异常: {rule.name} - {e}")
                violation = SafetyViolation(
                    timestamp=time.time(),
                    rule_id=rule_id,
                    rule_name=rule.name,
                    level=rule.level,
                    message=f"检查异常: {str(e)}",
                    context=context.copy()
                )
                violations.append(violation)
                self.violations.append(violation)
        
        is_safe = len(violations) == 0
        
        if is_safe:
            logger.info("✓ 安全检查通过")
        else:
            logger.warning(f"✗ 安全检查失败: {len(violations)} 个违规")
        
        return is_safe, violations
    
    async def _check_battery_level(self, context: Dict[str, Any]) -> tuple[bool, str]:
        """检查电池电量"""
        device_state = context.get("device_state", {})
        battery = device_state.get("battery", 100.0)
        
        min_battery = context.get("min_battery", 20.0)
        
        if battery < min_battery:
            return False, f"电池电量过低: {battery}% (最低要求: {min_battery}%)"
        
        return True, "电池电量正常"
    
    async def _check_gps_signal(self, context: Dict[str, Any]) -> tuple[bool, str]:
        """检查 GPS 信号"""
        device_state = context.get("device_state", {})
        gps_fix = device_state.get("gps_fix", True)
        
        if not gps_fix:
            return False, "GPS 信号丢失"
        
        return True, "GPS 信号正常"
    
    async def _check_temperature(self, context: Dict[str, Any]) -> tuple[bool, str]:
        """检查温度"""
        device_state = context.get("device_state", {})
        temperature = device_state.get("temperature", {})
        
        bed_temp = temperature.get("bed", {}).get("actual", 25.0)
        nozzle_temp = temperature.get("nozzle", {}).get("actual", 25.0)
        
        # 检查是否过热
        if bed_temp > 120.0:
            return False, f"热床温度过高: {bed_temp}°C"
        
        if nozzle_temp > 300.0:
            return False, f"喷嘴温度过高: {nozzle_temp}°C"
        
        return True, "温度正常"
    
    async def _check_connection(self, context: Dict[str, Any]) -> tuple[bool, str]:
        """检查连接状态"""
        device_state = context.get("device_state", {})
        connected = device_state.get("connected", False)
        
        if not connected:
            return False, "设备未连接"
        
        return True, "连接正常"
    
    async def _check_altitude_limit(self, context: Dict[str, Any]) -> tuple[bool, str]:
        """检查高度限制"""
        device_state = context.get("device_state", {})
        altitude = device_state.get("altitude", 0.0)
        
        max_altitude = context.get("max_altitude", 120.0)  # 默认最大高度 120 米
        
        if altitude > max_altitude:
            return False, f"飞行高度超限: {altitude}m (最大允许: {max_altitude}m)"
        
        return True, "高度正常"
    
    async def handle_error(self, error: Exception, context: Dict[str, Any]) -> Optional[Any]:
        """
        处理错误
        
        Args:
            error: 异常对象
            context: 错误上下文
        
        Returns:
            恢复结果（如果成功）
        """
        logger.error(f"处理错误: {type(error).__name__} - {str(error)}")
        
        # 根据错误类型选择恢复策略
        recovery_strategy = self._determine_recovery_strategy(error, context)
        
        logger.info(f"选择恢复策略: {recovery_strategy.value}")
        
        if recovery_strategy == RecoveryStrategy.RETRY:
            return await self._retry_action(context)
        
        elif recovery_strategy == RecoveryStrategy.FALLBACK:
            return await self._execute_fallback(context)
        
        elif recovery_strategy == RecoveryStrategy.SKIP:
            logger.info("跳过当前动作")
            return {"status": "skipped", "reason": str(error)}
        
        elif recovery_strategy == RecoveryStrategy.ABORT:
            logger.critical("中止执行")
            return {"status": "aborted", "reason": str(error)}
        
        elif recovery_strategy == RecoveryStrategy.MANUAL:
            logger.warning("需要手动介入")
            return {"status": "manual_required", "reason": str(error)}
        
        return None
    
    def _determine_recovery_strategy(self, error: Exception, context: Dict[str, Any]) -> RecoveryStrategy:
        """确定恢复策略"""
        error_type = type(error).__name__
        
        # 根据错误类型选择策略
        if error_type in ["TimeoutError", "ConnectionError"]:
            return RecoveryStrategy.RETRY
        
        elif error_type in ["ValueError", "KeyError"]:
            return RecoveryStrategy.FALLBACK
        
        elif error_type in ["PermissionError", "FileNotFoundError"]:
            return RecoveryStrategy.SKIP
        
        elif error_type in ["RuntimeError", "SystemError"]:
            return RecoveryStrategy.ABORT
        
        else:
            return RecoveryStrategy.RETRY
    
    async def _retry_action(self, context: Dict[str, Any]) -> Optional[Any]:
        """重试动作"""
        max_retries = context.get("max_retries", 3)
        retry_delay = context.get("retry_delay", 1.0)
        action_function = context.get("action_function")
        
        if not action_function:
            logger.error("未提供动作函数，无法重试")
            return None
        
        for attempt in range(1, max_retries + 1):
            logger.info(f"重试 {attempt}/{max_retries}...")
            
            try:
                result = await action_function()
                logger.info("重试成功")
                
                # 记录恢复历史
                self.recovery_history.append({
                    "timestamp": time.time(),
                    "strategy": RecoveryStrategy.RETRY.value,
                    "attempts": attempt,
                    "success": True
                })
                
                return result
            
            except Exception as e:
                logger.warning(f"重试 {attempt} 失败: {e}")
                
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error("所有重试都失败")
                    
                    # 记录恢复历史
                    self.recovery_history.append({
                        "timestamp": time.time(),
                        "strategy": RecoveryStrategy.RETRY.value,
                        "attempts": attempt,
                        "success": False,
                        "error": str(e)
                    })
        
        return None
    
    async def _execute_fallback(self, context: Dict[str, Any]) -> Optional[Any]:
        """执行后备方案"""
        fallback_function = context.get("fallback_function")
        
        if not fallback_function:
            logger.warning("未提供后备方案函数")
            return None
        
        try:
            logger.info("执行后备方案...")
            result = await fallback_function()
            logger.info("后备方案执行成功")
            
            # 记录恢复历史
            self.recovery_history.append({
                "timestamp": time.time(),
                "strategy": RecoveryStrategy.FALLBACK.value,
                "success": True
            })
            
            return result
        
        except Exception as e:
            logger.error(f"后备方案执行失败: {e}")
            
            # 记录恢复历史
            self.recovery_history.append({
                "timestamp": time.time(),
                "strategy": RecoveryStrategy.FALLBACK.value,
                "success": False,
                "error": str(e)
            })
            
            return None
    
    def get_violations(self, level: Optional[SafetyLevel] = None, limit: int = 100) -> List[SafetyViolation]:
        """获取违规列表"""
        violations = self.violations
        
        if level:
            violations = [v for v in violations if v.level == level]
        
        return violations[-limit:]
    
    def get_recovery_history(self, limit: int = 100) -> List[Dict]:
        """获取恢复历史"""
        return self.recovery_history[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取安全摘要"""
        total_violations = len(self.violations)
        critical_violations = len([v for v in self.violations if v.level == SafetyLevel.CRITICAL])
        high_violations = len([v for v in self.violations if v.level == SafetyLevel.HIGH])
        
        total_recoveries = len(self.recovery_history)
        successful_recoveries = len([r for r in self.recovery_history if r.get("success", False)])
        
        return {
            "total_violations": total_violations,
            "critical_violations": critical_violations,
            "high_violations": high_violations,
            "total_recoveries": total_recoveries,
            "successful_recoveries": successful_recoveries,
            "recovery_success_rate": (
                successful_recoveries / total_recoveries
                if total_recoveries > 0 else 0
            ),
            "active_rules": len([r for r in self.safety_rules.values() if r.enabled])
        }


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self, safety_manager: SafetyManager):
        """
        初始化错误处理器
        
        Args:
            safety_manager: 安全管理器实例
        """
        self.safety_manager = safety_manager
        self.error_history: List[Dict] = []
        
        logger.info("ErrorHandler 初始化完成")
    
    async def handle_execution_error(self, action_id: str, error: Exception, 
                                    context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理执行错误
        
        Args:
            action_id: 动作 ID
            error: 异常对象
            context: 错误上下文
        
        Returns:
            处理结果
        """
        logger.error(f"处理执行错误: {action_id} - {type(error).__name__}: {str(error)}")
        
        # 记录错误
        error_record = {
            "timestamp": time.time(),
            "action_id": action_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context
        }
        self.error_history.append(error_record)
        
        # 尝试恢复
        recovery_result = await self.safety_manager.handle_error(error, context)
        
        if recovery_result:
            logger.info(f"错误恢复成功: {action_id}")
            return {
                "success": True,
                "status": "recovered",
                "recovery_result": recovery_result
            }
        else:
            logger.error(f"错误恢复失败: {action_id}")
            return {
                "success": False,
                "status": "recovery_failed",
                "error": str(error)
            }
    
    def get_error_history(self, limit: int = 100) -> List[Dict]:
        """获取错误历史"""
        return self.error_history[-limit:]
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计"""
        if not self.error_history:
            return {
                "total_errors": 0,
                "error_types": {},
                "most_common_error": None
            }
        
        # 统计错误类型
        error_types = {}
        for error in self.error_history:
            error_type = error["error_type"]
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        # 找出最常见的错误
        most_common_error = max(error_types.items(), key=lambda x: x[1])[0] if error_types else None
        
        return {
            "total_errors": len(self.error_history),
            "error_types": error_types,
            "most_common_error": most_common_error
        }
