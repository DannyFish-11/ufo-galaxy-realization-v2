"""
实时状态监控和反馈系统 (Status Monitor)
负责监控系统和设备状态，提供实时反馈
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class MonitorLevel(Enum):
    """监控级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class StatusEvent:
    """状态事件"""
    timestamp: float
    source: str  # 事件来源（设备 ID 或模块名）
    level: MonitorLevel
    message: str
    data: Dict = field(default_factory=dict)


@dataclass
class DeviceStatus:
    """设备状态"""
    device_id: str
    device_type: str
    connected: bool
    status: str
    last_update: float
    metrics: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)


class StatusMonitor:
    """状态监控器"""
    
    def __init__(self, max_events: int = 1000, update_interval: float = 1.0):
        """
        初始化状态监控器
        
        Args:
            max_events: 最大事件数量
            update_interval: 更新间隔（秒）
        """
        self.max_events = max_events
        self.update_interval = update_interval
        
        # 事件队列
        self.events: deque = deque(maxlen=max_events)
        
        # 设备状态
        self.device_statuses: Dict[str, DeviceStatus] = {}
        
        # 系统指标
        self.system_metrics = {
            'uptime': 0.0,
            'total_actions': 0,
            'successful_actions': 0,
            'failed_actions': 0,
            'active_devices': 0,
            'cpu_usage': 0.0,
            'memory_usage': 0.0
        }
        
        # 回调函数
        self.event_callbacks: List[Callable] = []
        self.status_callbacks: List[Callable] = []
        
        # 监控任务
        self.monitoring_task = None
        self.running = False
        
        self.start_time = time.time()
        
        logger.info("StatusMonitor 初始化完成")
    
    def register_event_callback(self, callback: Callable):
        """注册事件回调"""
        self.event_callbacks.append(callback)
        logger.info(f"注册事件回调: {callback.__name__}")
    
    def register_status_callback(self, callback: Callable):
        """注册状态回调"""
        self.status_callbacks.append(callback)
        logger.info(f"注册状态回调: {callback.__name__}")
    
    def log_event(self, source: str, level: MonitorLevel, message: str, data: Optional[Dict] = None):
        """
        记录事件
        
        Args:
            source: 事件来源
            level: 监控级别
            message: 事件消息
            data: 附加数据
        """
        event = StatusEvent(
            timestamp=time.time(),
            source=source,
            level=level,
            message=message,
            data=data or {}
        )
        
        self.events.append(event)
        
        # 触发回调
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"事件回调失败: {e}")
        
        # 根据级别记录日志
        log_message = f"[{source}] {message}"
        if level == MonitorLevel.DEBUG:
            logger.debug(log_message)
        elif level == MonitorLevel.INFO:
            logger.info(log_message)
        elif level == MonitorLevel.WARNING:
            logger.warning(log_message)
        elif level == MonitorLevel.ERROR:
            logger.error(log_message)
        elif level == MonitorLevel.CRITICAL:
            logger.critical(log_message)
    
    def update_device_status(self, device_id: str, device_type: str, connected: bool, 
                           status: str, metrics: Optional[Dict] = None, 
                           metadata: Optional[Dict] = None):
        """
        更新设备状态
        
        Args:
            device_id: 设备 ID
            device_type: 设备类型
            connected: 是否连接
            status: 状态描述
            metrics: 性能指标
            metadata: 元数据
        """
        device_status = DeviceStatus(
            device_id=device_id,
            device_type=device_type,
            connected=connected,
            status=status,
            last_update=time.time(),
            metrics=metrics or {},
            metadata=metadata or {}
        )
        
        self.device_statuses[device_id] = device_status
        
        # 更新活跃设备数
        self.system_metrics['active_devices'] = sum(
            1 for ds in self.device_statuses.values() if ds.connected
        )
        
        # 触发回调
        for callback in self.status_callbacks:
            try:
                callback(device_status)
            except Exception as e:
                logger.error(f"状态回调失败: {e}")
        
        logger.debug(f"设备状态更新: {device_id} - {status}")
    
    def update_system_metrics(self, metrics: Dict[str, Any]):
        """更新系统指标"""
        self.system_metrics.update(metrics)
        self.system_metrics['uptime'] = time.time() - self.start_time
    
    def increment_action_count(self, success: bool):
        """增加动作计数"""
        self.system_metrics['total_actions'] += 1
        if success:
            self.system_metrics['successful_actions'] += 1
        else:
            self.system_metrics['failed_actions'] += 1
    
    def get_events(self, source: Optional[str] = None, level: Optional[MonitorLevel] = None, 
                   limit: int = 100) -> List[StatusEvent]:
        """
        获取事件列表
        
        Args:
            source: 过滤来源
            level: 过滤级别
            limit: 最大数量
        
        Returns:
            事件列表
        """
        events = list(self.events)
        
        # 过滤
        if source:
            events = [e for e in events if e.source == source]
        if level:
            events = [e for e in events if e.level == level]
        
        # 限制数量
        return events[-limit:]
    
    def get_device_status(self, device_id: str) -> Optional[DeviceStatus]:
        """获取设备状态"""
        return self.device_statuses.get(device_id)
    
    def get_all_device_statuses(self) -> List[DeviceStatus]:
        """获取所有设备状态"""
        return list(self.device_statuses.values())
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统指标"""
        return self.system_metrics.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        return {
            'uptime': self.system_metrics['uptime'],
            'total_events': len(self.events),
            'total_devices': len(self.device_statuses),
            'active_devices': self.system_metrics['active_devices'],
            'total_actions': self.system_metrics['total_actions'],
            'successful_actions': self.system_metrics['successful_actions'],
            'failed_actions': self.system_metrics['failed_actions'],
            'success_rate': (
                self.system_metrics['successful_actions'] / self.system_metrics['total_actions']
                if self.system_metrics['total_actions'] > 0 else 0
            ),
            'recent_events': len([e for e in self.events if time.time() - e.timestamp < 60]),
            'error_events': len([e for e in self.events if e.level in [MonitorLevel.ERROR, MonitorLevel.CRITICAL]])
        }
    
    async def start_monitoring(self):
        """启动监控"""
        if self.running:
            logger.warning("监控已在运行")
            return
        
        self.running = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("状态监控已启动")
    
    async def stop_monitoring(self):
        """停止监控"""
        if not self.running:
            return
        
        self.running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("状态监控已停止")
    
    async def _monitoring_loop(self):
        """监控循环"""
        while self.running:
            try:
                # 更新系统指标
                await self._update_system_metrics()
                
                # 检查设备状态
                await self._check_device_statuses()
                
                # 等待下一次更新
                await asyncio.sleep(self.update_interval)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(self.update_interval)
    
    async def _update_system_metrics(self):
        """更新系统指标"""
        try:
            import psutil
            
            # CPU 使用率
            cpu_usage = psutil.cpu_percent(interval=0.1)
            
            # 内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            
            self.system_metrics['cpu_usage'] = cpu_usage
            self.system_metrics['memory_usage'] = memory_usage
            self.system_metrics['uptime'] = time.time() - self.start_time
        
        except ImportError:
            # psutil 未安装
            pass
        except Exception as e:
            logger.debug(f"更新系统指标失败: {e}")
    
    async def _check_device_statuses(self):
        """检查设备状态"""
        current_time = time.time()
        
        for device_id, status in self.device_statuses.items():
            # 检查设备是否超时
            if status.connected and (current_time - status.last_update) > 30:
                self.log_event(
                    source=device_id,
                    level=MonitorLevel.WARNING,
                    message=f"设备状态超时: 上次更新于 {current_time - status.last_update:.1f} 秒前"
                )


class FeedbackCollector:
    """反馈收集器"""
    
    def __init__(self, monitor: StatusMonitor):
        """
        初始化反馈收集器
        
        Args:
            monitor: 状态监控器实例
        """
        self.monitor = monitor
        self.feedbacks: List[Dict] = []
        
        logger.info("FeedbackCollector 初始化完成")
    
    def collect_action_feedback(self, action_id: str, success: bool, 
                               duration: float, output: Any, 
                               error: Optional[str] = None):
        """
        收集动作执行反馈
        
        Args:
            action_id: 动作 ID
            success: 是否成功
            duration: 执行时长
            output: 输出结果
            error: 错误信息
        """
        feedback = {
            'timestamp': time.time(),
            'type': 'action',
            'action_id': action_id,
            'success': success,
            'duration': duration,
            'output': output,
            'error': error
        }
        
        self.feedbacks.append(feedback)
        
        # 记录事件
        level = MonitorLevel.INFO if success else MonitorLevel.ERROR
        message = f"动作 {action_id} {'成功' if success else '失败'} (耗时: {duration:.2f}s)"
        
        self.monitor.log_event(
            source="ActionExecutor",
            level=level,
            message=message,
            data=feedback
        )
        
        # 更新系统指标
        self.monitor.increment_action_count(success)
    
    def collect_device_feedback(self, device_id: str, device_type: str, 
                               state: Dict[str, Any]):
        """
        收集设备状态反馈
        
        Args:
            device_id: 设备 ID
            device_type: 设备类型
            state: 设备状态
        """
        feedback = {
            'timestamp': time.time(),
            'type': 'device',
            'device_id': device_id,
            'device_type': device_type,
            'state': state
        }
        
        self.feedbacks.append(feedback)
        
        # 更新设备状态
        self.monitor.update_device_status(
            device_id=device_id,
            device_type=device_type,
            connected=state.get('connected', False),
            status=state.get('status', 'unknown'),
            metrics=state.get('metrics', {}),
            metadata=state
        )
    
    def collect_system_feedback(self, component: str, message: str, 
                               data: Optional[Dict] = None):
        """
        收集系统反馈
        
        Args:
            component: 组件名称
            message: 反馈消息
            data: 附加数据
        """
        feedback = {
            'timestamp': time.time(),
            'type': 'system',
            'component': component,
            'message': message,
            'data': data or {}
        }
        
        self.feedbacks.append(feedback)
        
        # 记录事件
        self.monitor.log_event(
            source=component,
            level=MonitorLevel.INFO,
            message=message,
            data=data or {}
        )
    
    def get_feedbacks(self, feedback_type: Optional[str] = None, 
                     limit: int = 100) -> List[Dict]:
        """
        获取反馈列表
        
        Args:
            feedback_type: 反馈类型过滤
            limit: 最大数量
        
        Returns:
            反馈列表
        """
        feedbacks = self.feedbacks
        
        if feedback_type:
            feedbacks = [f for f in feedbacks if f['type'] == feedback_type]
        
        return feedbacks[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取反馈摘要"""
        total = len(self.feedbacks)
        action_feedbacks = [f for f in self.feedbacks if f['type'] == 'action']
        device_feedbacks = [f for f in self.feedbacks if f['type'] == 'device']
        system_feedbacks = [f for f in self.feedbacks if f['type'] == 'system']
        
        successful_actions = sum(1 for f in action_feedbacks if f['success'])
        
        return {
            'total_feedbacks': total,
            'action_feedbacks': len(action_feedbacks),
            'device_feedbacks': len(device_feedbacks),
            'system_feedbacks': len(system_feedbacks),
            'successful_actions': successful_actions,
            'failed_actions': len(action_feedbacks) - successful_actions,
            'success_rate': (
                successful_actions / len(action_feedbacks)
                if action_feedbacks else 0
            )
        }
