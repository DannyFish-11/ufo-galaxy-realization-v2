"""
Galaxy 主循环 L4 版本
集成了所有 L4 级自主性智能组件

.. deprecated::
    Direct import/use of this module is deprecated.  L4 capabilities are now
    managed by ``unified_launcher.py``.  The recommended entrypoint is
    ``main.py`` (or ``unified_launcher.py``).

    Migration::

        # Before:
        python start_l4.py   # which imports GalaxyMainLoopL4 from here

        # After (full system with L4 enabled):
        python main.py
"""

import asyncio
import logging
import signal
import time
import sys
import warnings
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

# 添加路径
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

# L4 组件 —— 核心模块（每个模块独立降级，缺少任一不影响其他模块）
_logger = logging.getLogger(__name__)
_logger.warning(
    "galaxy_main_loop_l4.py is deprecated; use unified_launcher.py (via main.py) instead."
)

try:
    from enhancements.perception.environment_scanner import EnvironmentScanner
    _PERCEPTION_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"感知模块不可用: {_e}")
    EnvironmentScanner = None  # type: ignore
    _PERCEPTION_AVAILABLE = False

try:
    from enhancements.reasoning.goal_decomposer import GoalDecomposer, Goal, GoalType
    _GOAL_DECOMPOSER_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"目标分解模块不可用: {_e}")
    GoalDecomposer = None  # type: ignore
    Goal = None  # type: ignore
    GoalType = None  # type: ignore
    _GOAL_DECOMPOSER_AVAILABLE = False

try:
    from enhancements.reasoning.autonomous_planner import AutonomousPlanner, Resource, ResourceType
    _PLANNER_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"规划模块不可用: {_e}")
    AutonomousPlanner = None  # type: ignore
    Resource = None  # type: ignore
    ResourceType = None  # type: ignore
    _PLANNER_AVAILABLE = False

try:
    from enhancements.reasoning.world_model import WorldModel, Entity, EntityType, EntityState
    _WORLD_MODEL_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"世界模型不可用: {_e}")
    WorldModel = None  # type: ignore
    Entity = None  # type: ignore
    EntityType = None  # type: ignore
    EntityState = None  # type: ignore
    _WORLD_MODEL_AVAILABLE = False

try:
    from enhancements.reasoning.metacognition_service import MetaCognitionService
    _METACOGNITION_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"元认知模块不可用: {_e}")
    MetaCognitionService = None  # type: ignore
    _METACOGNITION_AVAILABLE = False

try:
    from enhancements.reasoning.autonomous_coder import AutonomousCoder
    _CODER_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"自主编码模块不可用: {_e}")
    AutonomousCoder = None  # type: ignore
    _CODER_AVAILABLE = False

try:
    from enhancements.execution.action_executor import ActionExecutor, ExecutionStatus
    _EXECUTOR_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"执行器不可用: {_e}")
    ActionExecutor = None  # type: ignore
    ExecutionStatus = None  # type: ignore
    _EXECUTOR_AVAILABLE = False

try:
    from enhancements.monitoring.status_monitor import StatusMonitor, FeedbackCollector, MonitorLevel
    _MONITOR_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"状态监控不可用: {_e}")
    StatusMonitor = None  # type: ignore
    FeedbackCollector = None  # type: ignore
    MonitorLevel = None  # type: ignore
    _MONITOR_AVAILABLE = False

try:
    from enhancements.safety.safety_manager import SafetyManager, ErrorHandler
    _SAFETY_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"安全管理器不可用: {_e}")
    SafetyManager = None  # type: ignore
    ErrorHandler = None  # type: ignore
    _SAFETY_AVAILABLE = False

# L4 组件 —— 学习模块（依赖 numpy/sklearn，允许降级）
try:
    from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
    from enhancements.learning.learning_optimizer import LearningOptimizer
    _LEARNING_AVAILABLE = True
except ImportError as _e:
    logging.getLogger(__name__).warning(f"学习模块不可用（缺少依赖: {_e}），L4 将以基础模式运行")
    AutonomousLearningEngine = None  # type: ignore
    LearningOptimizer = None  # type: ignore
    _LEARNING_AVAILABLE = False


class CycleState(Enum):
    """主循环周期状态"""
    IDLE = auto()
    PERCEIVING = auto()
    DECOMPOSING = auto()
    PLANNING = auto()
    EXECUTING = auto()
    LEARNING = auto()
    REFLECTING = auto()
    ERROR = auto()


@dataclass
class L4CycleResult:
    """L4 周期执行结果"""
    cycle_id: str
    state: CycleState
    start_time: datetime
    end_time: Optional[datetime] = None
    goal_description: str = ""
    subtasks_count: int = 0
    actions_count: int = 0
    success: bool = False
    insights_count: int = 0
    performance_level: str = ""
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class GalaxyMainLoopL4:
    """Galaxy 主循环 L4 版本 - 完全自主性智能"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # L4 核心组件（每个模块可独立降级）
        self.env_scanner = EnvironmentScanner() if _PERCEPTION_AVAILABLE else None
        self.goal_decomposer = GoalDecomposer() if _GOAL_DECOMPOSER_AVAILABLE else None
        self.planner = AutonomousPlanner() if _PLANNER_AVAILABLE else None
        self.world_model = WorldModel() if _WORLD_MODEL_AVAILABLE else None
        self.metacog = MetaCognitionService() if _METACOGNITION_AVAILABLE else None
        self.auto_coder = AutonomousCoder() if _CODER_AVAILABLE else None
        self.learning_engine = AutonomousLearningEngine() if _LEARNING_AVAILABLE else None
        self.learning_optimizer = LearningOptimizer() if _LEARNING_AVAILABLE else None

        # 执行和监控组件
        self.action_executor = ActionExecutor() if _EXECUTOR_AVAILABLE else None
        self.status_monitor = StatusMonitor() if _MONITOR_AVAILABLE else None
        self.feedback_collector = FeedbackCollector(self.status_monitor) if (_MONITOR_AVAILABLE and self.status_monitor) else None
        self.safety_manager = SafetyManager() if _SAFETY_AVAILABLE else None
        self.error_handler = ErrorHandler(self.safety_manager) if (_SAFETY_AVAILABLE and self.safety_manager) else None
        
        # 状态
        self.running = False
        self.current_state = CycleState.IDLE
        self.cycle_count = 0
        self.cycle_results: List[L4CycleResult] = []
        self.task_history: List[Dict] = []
        self._max_task_history = 500  # 限制历史长度防止内存泄漏
        self._shutdown_event = asyncio.Event()
        self._main_task: Optional[asyncio.Task] = None

        _logger.info(f"L4 模块状态: {self._module_status()}")

        # 目标队列 —— 接收来自 API / WebSocket / 定时任务的目标
        self._goal_queue: asyncio.Queue = asyncio.Queue()
        
        # 配置
        self.cycle_interval = self.config.get("cycle_interval", 5.0)
        self.auto_scan_interval = self.config.get("auto_scan_interval", 300.0)  # 5 分钟
        self.last_scan_time = 0
        
        # 设置日志
        self._setup_logging()
        
        self.logger.info("GalaxyMainLoopL4 initialized - L4 级自主性智能已就绪")
    
    def _setup_logging(self):
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger("GalaxyL4")
    
    def _module_status(self) -> Dict[str, bool]:
        """返回每个增强模块的可用性状态"""
        return {
            "perception": _PERCEPTION_AVAILABLE,
            "goal_decomposer": _GOAL_DECOMPOSER_AVAILABLE,
            "planner": _PLANNER_AVAILABLE,
            "world_model": _WORLD_MODEL_AVAILABLE,
            "metacognition": _METACOGNITION_AVAILABLE,
            "autonomous_coder": _CODER_AVAILABLE,
            "executor": _EXECUTOR_AVAILABLE,
            "monitor": _MONITOR_AVAILABLE,
            "safety": _SAFETY_AVAILABLE,
            "learning": _LEARNING_AVAILABLE,
        }

    async def start(self):
        """启动主循环"""
        self.logger.info("=" * 60)
        self.logger.info("启动 Galaxy L4 级自主性智能系统")
        self.logger.info("=" * 60)
        
        # 初始化
        await self._initialize()
        
        # 设置信号处理
        self._setup_signal_handlers()
        
        # 启动主循环
        self.running = True
        self._main_task = asyncio.create_task(self._main_loop())
        
        self.logger.info("L4 主循环启动成功")
        
        # 等待关闭信号
        await self._shutdown_event.wait()
    
    async def _initialize(self):
        """初始化环境"""
        self.logger.info("初始化 L4 环境")
        
        # 扫描环境
        tools = self.env_scanner.scan_and_register_all()
        self.logger.info(f"发现 {len(tools)} 个工具")
        
        # 注册到世界模型
        for tool in tools.values():
            entity = Entity(
                id=f"tool_{tool.name.lower().replace(' ', '_')}",
                type=EntityType.SERVICE,
                name=tool.name,
                state=EntityState.ACTIVE,
                properties={
                    "version": tool.version,
                    "path": tool.path,
                    "capabilities": tool.capabilities
                }
            )
            self.world_model.register_entity(entity)
        
        # 更新规划器的可用资源
        resources = [
            Resource(
                id=f"tool_{t.name.lower().replace(' ', '_')}",
                type=ResourceType.TOOL,
                name=t.name,
                capabilities=t.capabilities,
                availability=1.0,
                metadata={}
            )
            for t in tools.values()
        ]
        self.planner.available_resources = resources
        
        self.logger.info("L4 环境初始化完成")
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig,
                    lambda: asyncio.create_task(self.stop())
                )
        else:
            signal.signal(signal.SIGINT, lambda s, f: asyncio.ensure_future(self.stop()))
    
    async def _main_loop(self):
        """主循环"""
        while self.running:
            try:
                await self.run_cycle()
                await asyncio.sleep(self.cycle_interval)
            except Exception as e:
                self.logger.error(f"主循环错误: {e}", exc_info=True)
                await asyncio.sleep(10.0)
    
    async def run_cycle(self) -> L4CycleResult:
        """运行一个完整的 L4 周期"""
        cycle_id = f"l4_cycle_{self.cycle_count}_{int(time.time() * 1000)}"
        result = L4CycleResult(
            cycle_id=cycle_id,
            state=CycleState.IDLE,
            start_time=datetime.now()
        )
        
        try:
            self.cycle_count += 1
            self.logger.info(f"开始 L4 周期 #{self.cycle_count}")
            
            # 定期重新扫描环境
            if time.time() - self.last_scan_time > self.auto_scan_interval:
                await self._rescan_environment()
                self.last_scan_time = time.time()
            
            # 1. 感知：接收或生成目标
            self.current_state = CycleState.PERCEIVING
            goal = await self._perceive_goal()
            
            if goal:
                result.goal_description = goal.description
                self.logger.info(f"目标: {goal.description}")
                
                # 2. 分解：将目标分解为子任务
                self.current_state = CycleState.DECOMPOSING
                decomposition = self.goal_decomposer.decompose(goal)
                result.subtasks_count = len(decomposition.subtasks)
                self.logger.info(f"分解为 {len(decomposition.subtasks)} 个子任务")
                
                # 3. 规划：创建执行计划
                self.current_state = CycleState.PLANNING
                plan = self.planner.create_plan(decomposition)
                result.actions_count = len(plan.actions)
                self.logger.info(f"创建了包含 {len(plan.actions)} 个动作的计划")
                
                # 4. 执行：执行计划
                self.current_state = CycleState.EXECUTING
                execution_result = await self._execute_plan(plan)
                result.success = execution_result['success']
                
                # 5. 学习：从执行中学习
                self.current_state = CycleState.LEARNING
                await self._learn_from_execution(execution_result)
                
                # 6. 反思：评估性能
                self.current_state = CycleState.REFLECTING
                insights = await self._reflect_on_performance()
                result.insights_count = len(insights)
                
                # 获取性能等级
                if self.metacog.assessments:
                    result.performance_level = self.metacog.assessments[-1].overall_performance.value
                
                # 7. 自我优化
                if self.metacog.should_adjust_strategy():
                    await self._adjust_strategy()
            
            self.logger.info(f"L4 周期 #{self.cycle_count} 完成")
            
        except Exception as e:
            result.state = CycleState.ERROR
            result.success = False
            result.errors.append(str(e))
            self.logger.error(f"L4 周期 #{self.cycle_count} 失败: {e}", exc_info=True)
        
        finally:
            result.end_time = datetime.now()
            self.cycle_results.append(result)
            
            # 清理旧结果
            if len(self.cycle_results) > 100:
                self.cycle_results = self.cycle_results[-100:]
        
        return result
    
    async def _rescan_environment(self):
        """重新扫描环境"""
        self.logger.info("重新扫描环境")
        tools = self.env_scanner.scan_and_register_all()
        self.logger.info(f"发现 {len(tools)} 个工具")
    
    async def _perceive_goal(self) -> Optional[Goal]:
        """
        感知目标 —— 从目标队列中获取待处理的目标。
        来源：API 提交 / WebSocket 用户输入 / 定时任务 / 自主生成
        """
        try:
            goal = self._goal_queue.get_nowait()
            self.logger.info(f"从目标队列获取到目标: {goal.description}")
            return goal
        except asyncio.QueueEmpty:
            return None
    
    async def _execute_plan(self, plan) -> Dict:
        """执行计划"""
        self.logger.info(f"执行计划: {plan.goal_description}")
        
        # 执行前安全检查
        safety_context = {
            "plan": plan,
            "min_battery": 20.0,
            "max_altitude": 120.0
        }
        
        is_safe, violations = await self.safety_manager.check_safety(safety_context)
        
        if not is_safe:
            self.logger.error(f"安全检查失败: {len(violations)} 个违规")
            for violation in violations:
                self.logger.error(f"  - {violation.rule_name}: {violation.message}")
            
            return {
                'success': False,
                'reason': 'safety_check_failed',
                'violations': violations,
                'results': []
            }
        
        # 启动状态监控
        await self.status_monitor.start_monitoring()
        
        try:
            # 使用 ActionExecutor 执行计划
            execution_context = await self.action_executor.execute_plan(plan, self.world_model)
            
            # 收集反馈
            for result in execution_context.results:
                self.feedback_collector.collect_action_feedback(
                    action_id=result.action_id,
                    success=(result.status == ExecutionStatus.SUCCESS),
                    duration=result.duration,
                    output=result.output,
                    error=result.error
                )
            
            # 获取执行摘要
            summary = self.action_executor.get_execution_summary(execution_context)
            
            self.logger.info(f"计划执行完成: 成功率 {summary['success_rate']:.1%}")
            
            return {
                'success': summary['success_rate'] > 0.5,
                'execution_context': execution_context,
                'summary': summary,
                'results': execution_context.results
            }
        
        except Exception as e:
            self.logger.error(f"执行计划失败: {e}")
            
            # 错误处理
            error_result = await self.error_handler.handle_execution_error(
                action_id="plan_execution",
                error=e,
                context={'plan': plan}
            )
            
            return {
                'success': False,
                'reason': 'execution_error',
                'error': str(e),
                'error_result': error_result,
                'results': []
            }
        
        finally:
            # 停止状态监控
            await self.status_monitor.stop_monitoring()
    
    async def _learn_from_execution(self, execution_result: Dict):
        """从执行中学习"""
        self.logger.info("从执行中学习")

        # 记录执行结果
        if self.learning_optimizer:
            self.learning_optimizer.record_execution(execution_result)

        # 提取观察
        summary = execution_result.get('summary', {})

        observation = {
            'goal': summary.get('goal', 'unknown'),
            'success': execution_result.get('success', False),
            'duration': summary.get('total_duration', 0),
            'actions_count': summary.get('total_actions', 0),
            'success_rate': summary.get('success_rate', 0),
            'timestamp': datetime.now().isoformat(),
        }

        # 记录到历史（限制大小，防止内存泄漏）
        self.task_history.append(observation)
        if len(self.task_history) > self._max_task_history:
            self.task_history = self.task_history[-self._max_task_history:]

        # 使用指数加权移动平均 (EWMA) 更新决策权重，比简单平均更能反映近期趋势
        _DEFAULT_SUCCESS_RATE = 0.5
        recent = self.task_history[-20:] if self.task_history else []
        if recent:
            alpha = 0.3  # EWMA 衰减因子
            ewma = recent[0].get('success_rate', _DEFAULT_SUCCESS_RATE)
            for t in recent[1:]:
                ewma = alpha * t.get('success_rate', 0) + (1 - alpha) * ewma
            avg_success = ewma
        else:
            avg_success = _DEFAULT_SUCCESS_RATE

        # 计算趋势（是否在改善）
        if len(recent) >= 4:
            first_half = sum(t.get('success_rate', 0) for t in recent[:len(recent)//2]) / (len(recent) // 2)
            second_half = sum(t.get('success_rate', 0) for t in recent[len(recent)//2:]) / (len(recent) - len(recent) // 2)
            trend = "improving" if second_half > first_half + 0.05 else ("declining" if second_half < first_half - 0.05 else "stable")
        else:
            trend = "insufficient_data"

        self.planner.update_decision_weights({
            "average_success_rate": avg_success,
            "trend": trend,
            "sample_size": len(recent),
        })
        self.logger.info(f"[LEARNING] 决策权重已更新 (EWMA 成功率={avg_success:.1%}, 趋势={trend})")

        # 检查是否需要优化
        if self.learning_optimizer and self.learning_optimizer.should_optimize():
            self.logger.info("检测到需要优化")
            await self._perform_optimization()

        self.logger.info(f"学习完成: 成功={observation['success']}, 时长={observation['duration']:.1f}s, 成功率={observation['success_rate']:.1%}")
    
    async def _reflect_on_performance(self) -> List:
        """反思性能"""
        self.logger.info("反思性能")
        
        # 获取最近的任务
        recent_tasks = self.task_history[-10:] if self.task_history else []
        
        insights = []
        
        if recent_tasks:
            # 评估性能
            assessment = self.metacog.assess_performance(recent_tasks)
            self.logger.info(f"性能评估: {assessment.overall_performance.value}")
            
            # 提取洞察
            world_state = self.world_model.query_state("")
            insights = self.metacog.extract_insights(recent_tasks, world_state)
            self.logger.info(f"提取了 {len(insights)} 个洞察")
        
        return insights
    
    async def _adjust_strategy(self):
        """调整策略"""
        self.logger.info("调整策略")
        
        if self.metacog.assessments:
            latest = self.metacog.assessments[-1]
            
            for suggestion in latest.improvement_suggestions:
                self.logger.info(f"应用建议: {suggestion}")
    
    async def _perform_optimization(self):
        """执行优化"""
        self.logger.info("执行优化...")
        
        # 分析性能
        if not self.learning_optimizer:
            self.logger.info("学习模块不可用，跳过优化")
            return

        insights = self.learning_optimizer.analyze_performance()

        if not insights:
            self.logger.info("没有发现优化机会")
            return

        self.logger.info(f"发现 {len(insights)} 个优化洞察")

        # 生成优化计划
        optimization_plan = self.learning_optimizer.generate_optimization_plan(insights)

        # 应用优化
        for action in optimization_plan:
            success = self.learning_optimizer.apply_optimization(action)
            if success:
                self.logger.info(f"优化应用成功: {action['description']}")
            else:
                self.logger.warning(f"优化应用失败: {action['description']}")

        # 将学习输出反馈给规划器，更新决策权重
        self.planner.update_decision_weights(self.learning_optimizer.performance_metrics)
        
        self.logger.info("优化完成")
    
    async def submit_goal(self, goal_description: str, goal_type: GoalType = GoalType.TASK_EXECUTION):
        """提交外部目标 —— 放入队列，由主循环的下一个周期处理"""
        goal = Goal(
            description=goal_description,
            type=goal_type,
            constraints=[],
            success_criteria=[],
            deadline=None
        )
        await self._goal_queue.put(goal)
        self.logger.info(f"目标已入队 (队列深度={self._goal_queue.qsize()}): {goal_description}")
        return {"queued": True, "queue_size": self._goal_queue.qsize(), "description": goal_description}
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "running": self.running,
            "state": self.current_state.name,
            "cycle_count": self.cycle_count,
            "task_history_count": len(self.task_history),
            "world_entities_count": len(self.world_model.entities),
            "available_resources": len(self.planner.available_resources),
            "performance_level": self.metacog.assessments[-1].overall_performance.value if self.metacog.assessments else "unknown"
        }
    
    async def stop(self):
        """停止主循环"""
        self.logger.info("停止 L4 主循环")
        
        self.running = False
        
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        
        self._shutdown_event.set()
        
        self.logger.info("L4 主循环已停止")


async def main():
    """主入口"""
    config = {
        "cycle_interval": 5.0,
        "auto_scan_interval": 300.0
    }
    
    loop = GalaxyMainLoopL4(config)
    
    try:
        await loop.start()
    except Exception as e:
        logging.error(f"致命错误: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
