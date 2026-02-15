"""
Galaxy 主循环 L4 版本
集成了所有 L4 级自主性智能组件
"""

import asyncio
import logging
import signal
import time
import sys
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

# 添加路径
sys.path.insert(0, '/home/ubuntu/code_audit/ufo-galaxy-realization')

# L4 组件
from enhancements.perception.environment_scanner import EnvironmentScanner
from enhancements.reasoning.goal_decomposer import GoalDecomposer, Goal, GoalType
from enhancements.reasoning.autonomous_planner import AutonomousPlanner, Resource, ResourceType
from enhancements.reasoning.world_model import WorldModel, Entity, EntityType, EntityState
from enhancements.reasoning.metacognition_service import MetaCognitionService
from enhancements.reasoning.autonomous_coder import AutonomousCoder
from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
from enhancements.learning.learning_optimizer import LearningOptimizer
from enhancements.execution.action_executor import ActionExecutor, ExecutionStatus
from enhancements.monitoring.status_monitor import StatusMonitor, FeedbackCollector, MonitorLevel
from enhancements.safety.safety_manager import SafetyManager, ErrorHandler


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
        
        # L4 核心组件
        self.env_scanner = EnvironmentScanner()
        self.goal_decomposer = GoalDecomposer()
        self.planner = AutonomousPlanner()
        self.world_model = WorldModel()
        self.metacog = MetaCognitionService()
        self.auto_coder = AutonomousCoder(llm_available=False)
        self.learning_engine = AutonomousLearningEngine()
        self.learning_optimizer = LearningOptimizer()
        
        # 执行和监控组件
        self.action_executor = ActionExecutor()
        self.status_monitor = StatusMonitor()
        self.feedback_collector = FeedbackCollector(self.status_monitor)
        self.safety_manager = SafetyManager()
        self.error_handler = ErrorHandler(self.safety_manager)
        
        # 状态
        self.running = False
        self.current_state = CycleState.IDLE
        self.cycle_count = 0
        self.cycle_results: List[L4CycleResult] = []
        self.task_history: List[Dict] = []
        self._shutdown_event = asyncio.Event()
        self._main_task: Optional[asyncio.Task] = None
        
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
    
    async def start(self):
        """启动主循环"""
        self.logger.info("=" * 60)
        self.logger.info("启动 UFO Galaxy L4 级自主性智能系统")
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
        for tool in tools:
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
            for t in tools
        ]
        self.planner.available_resources = resources
        
        self.logger.info("L4 环境初始化完成")
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(
                sig, 
                lambda: asyncio.create_task(self.stop())
            )
    
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
        """感知目标"""
        # 这里应该从多个来源接收目标：
        # - WebSocket 服务器（用户输入）
        # - 定时任务
        # - 自主生成的目标
        
        # 简单实现：返回 None（无目标）
        # 实际实现中应该连接到 WebSocket 服务器
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
        self.learning_optimizer.record_execution(execution_result)
        
        # 提取观察
        summary = execution_result.get('summary', {})
        
        observation = {
            'goal': summary.get('goal', 'unknown'),
            'success': execution_result.get('success', False),
            'duration': summary.get('total_duration', 0),
            'actions_count': summary.get('total_actions', 0),
            'success_rate': summary.get('success_rate', 0)
        }
        
        # 记录到历史
        self.task_history.append(observation)
        
        # 检查是否需要优化
        if self.learning_optimizer.should_optimize():
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
        
        self.logger.info("优化完成")
    
    async def submit_goal(self, goal_description: str, goal_type: GoalType = GoalType.TASK_EXECUTION):
        """提交外部目标"""
        goal = Goal(
            description=goal_description,
            type=goal_type,
            constraints=[],
            success_criteria=[],
            deadline=None
        )
        self.logger.info(f"接收到外部目标: {goal_description}")
        # 这里应该将目标放入队列
        # 简化实现：直接处理
    
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
