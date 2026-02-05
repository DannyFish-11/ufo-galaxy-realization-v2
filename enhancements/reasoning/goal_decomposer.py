"""
目标分解器 (Goal Decomposer)
将高层次目标分解为可执行的子任务
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class GoalType(Enum):
    """目标类型"""
    INFORMATION_GATHERING = "information_gathering"
    TASK_EXECUTION = "task_execution"
    PROBLEM_SOLVING = "problem_solving"
    CREATION = "creation"
    AUTOMATION = "automation"


class SubTaskType(Enum):
    """子任务类型"""
    SEARCH = "search"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ANALYZE = "analyze"
    SYNTHESIZE = "synthesize"
    CONTROL_DEVICE = "control_device"
    COMMUNICATE = "communicate"


@dataclass
class SubTask:
    """子任务"""
    id: str
    type: SubTaskType
    description: str
    dependencies: List[str]  # 依赖的子任务 ID
    required_capabilities: List[str]
    estimated_duration: int  # 秒
    priority: int  # 1-10, 10 最高
    metadata: Dict


@dataclass
class Goal:
    """目标"""
    description: str
    type: GoalType
    constraints: List[str]
    success_criteria: List[str]
    deadline: Optional[int]  # Unix timestamp


@dataclass
class DecompositionResult:
    """分解结果"""
    goal: Goal
    subtasks: List[SubTask]
    execution_order: List[str]  # 子任务 ID 的执行顺序
    estimated_total_duration: int


class GoalDecomposer:
    """目标分解器"""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        logger.info("GoalDecomposer initialized")
    
    def decompose(self, goal: Goal) -> DecompositionResult:
        """分解目标"""
        logger.info(f"开始分解目标: {goal.description}")
        
        # 1. 识别目标类型
        goal_type = self._identify_goal_type(goal)
        logger.info(f"目标类型: {goal_type.value}")
        
        # 2. 生成子任务
        subtasks = self._generate_subtasks(goal, goal_type)
        logger.info(f"生成了 {len(subtasks)} 个子任务")
        
        # 3. 确定执行顺序
        execution_order = self._determine_execution_order(subtasks)
        logger.info(f"执行顺序: {' -> '.join(execution_order)}")
        
        # 4. 估算总时长
        total_duration = sum(st.estimated_duration for st in subtasks)
        
        return DecompositionResult(
            goal=goal,
            subtasks=subtasks,
            execution_order=execution_order,
            estimated_total_duration=total_duration
        )
    
    def _identify_goal_type(self, goal: Goal) -> GoalType:
        """识别目标类型"""
        description_lower = goal.description.lower()
        
        # 简单的关键词匹配
        if any(kw in description_lower for kw in ['查找', '搜索', '了解', 'find', 'search', 'learn']):
            return GoalType.INFORMATION_GATHERING
        
        if any(kw in description_lower for kw in ['创建', '生成', '设计', 'create', 'generate', 'design']):
            return GoalType.CREATION
        
        if any(kw in description_lower for kw in ['解决', '修复', '调试', 'solve', 'fix', 'debug']):
            return GoalType.PROBLEM_SOLVING
        
        if any(kw in description_lower for kw in ['自动化', '定时', 'automate', 'schedule']):
            return GoalType.AUTOMATION
        
        return GoalType.TASK_EXECUTION
    
    def _generate_subtasks(self, goal: Goal, goal_type: GoalType) -> List[SubTask]:
        """生成子任务"""
        if goal_type == GoalType.INFORMATION_GATHERING:
            return self._generate_information_gathering_subtasks(goal)
        elif goal_type == GoalType.CREATION:
            return self._generate_creation_subtasks(goal)
        elif goal_type == GoalType.PROBLEM_SOLVING:
            return self._generate_problem_solving_subtasks(goal)
        elif goal_type == GoalType.AUTOMATION:
            return self._generate_automation_subtasks(goal)
        else:
            return self._generate_generic_subtasks(goal)
    
    def _generate_information_gathering_subtasks(self, goal: Goal) -> List[SubTask]:
        """生成信息收集子任务"""
        subtasks = [
            SubTask(
                id="search_1",
                type=SubTaskType.SEARCH,
                description=f"搜索相关信息: {goal.description}",
                dependencies=[],
                required_capabilities=['web_search', 'information_retrieval'],
                estimated_duration=30,
                priority=10,
                metadata={}
            ),
            SubTask(
                id="read_1",
                type=SubTaskType.READ,
                description="阅读和理解搜索结果",
                dependencies=["search_1"],
                required_capabilities=['text_understanding', 'summarization'],
                estimated_duration=60,
                priority=9,
                metadata={}
            ),
            SubTask(
                id="synthesize_1",
                type=SubTaskType.SYNTHESIZE,
                description="综合信息并生成报告",
                dependencies=["read_1"],
                required_capabilities=['text_generation', 'analysis'],
                estimated_duration=45,
                priority=8,
                metadata={}
            ),
        ]
        return subtasks
    
    def _generate_creation_subtasks(self, goal: Goal) -> List[SubTask]:
        """生成创作子任务"""
        subtasks = [
            SubTask(
                id="analyze_1",
                type=SubTaskType.ANALYZE,
                description=f"分析创作需求: {goal.description}",
                dependencies=[],
                required_capabilities=['requirement_analysis'],
                estimated_duration=30,
                priority=10,
                metadata={}
            ),
            SubTask(
                id="write_1",
                type=SubTaskType.WRITE,
                description="生成初稿",
                dependencies=["analyze_1"],
                required_capabilities=['content_generation', 'creativity'],
                estimated_duration=120,
                priority=9,
                metadata={}
            ),
            SubTask(
                id="analyze_2",
                type=SubTaskType.ANALYZE,
                description="评估和优化",
                dependencies=["write_1"],
                required_capabilities=['quality_assessment', 'optimization'],
                estimated_duration=60,
                priority=8,
                metadata={}
            ),
        ]
        return subtasks
    
    def _generate_problem_solving_subtasks(self, goal: Goal) -> List[SubTask]:
        """生成问题解决子任务"""
        subtasks = [
            SubTask(
                id="analyze_1",
                type=SubTaskType.ANALYZE,
                description=f"分析问题: {goal.description}",
                dependencies=[],
                required_capabilities=['problem_analysis', 'root_cause_analysis'],
                estimated_duration=45,
                priority=10,
                metadata={}
            ),
            SubTask(
                id="search_1",
                type=SubTaskType.SEARCH,
                description="搜索解决方案",
                dependencies=["analyze_1"],
                required_capabilities=['web_search', 'knowledge_retrieval'],
                estimated_duration=30,
                priority=9,
                metadata={}
            ),
            SubTask(
                id="execute_1",
                type=SubTaskType.EXECUTE,
                description="执行解决方案",
                dependencies=["search_1"],
                required_capabilities=['task_execution', 'system_control'],
                estimated_duration=90,
                priority=8,
                metadata={}
            ),
            SubTask(
                id="analyze_2",
                type=SubTaskType.ANALYZE,
                description="验证解决方案",
                dependencies=["execute_1"],
                required_capabilities=['testing', 'validation'],
                estimated_duration=30,
                priority=7,
                metadata={}
            ),
        ]
        return subtasks
    
    def _generate_automation_subtasks(self, goal: Goal) -> List[SubTask]:
        """生成自动化子任务"""
        subtasks = [
            SubTask(
                id="analyze_1",
                type=SubTaskType.ANALYZE,
                description=f"分析自动化需求: {goal.description}",
                dependencies=[],
                required_capabilities=['workflow_analysis'],
                estimated_duration=30,
                priority=10,
                metadata={}
            ),
            SubTask(
                id="write_1",
                type=SubTaskType.WRITE,
                description="编写自动化脚本",
                dependencies=["analyze_1"],
                required_capabilities=['code_generation', 'scripting'],
                estimated_duration=120,
                priority=9,
                metadata={}
            ),
            SubTask(
                id="execute_1",
                type=SubTaskType.EXECUTE,
                description="测试自动化脚本",
                dependencies=["write_1"],
                required_capabilities=['testing', 'execution'],
                estimated_duration=60,
                priority=8,
                metadata={}
            ),
            SubTask(
                id="execute_2",
                type=SubTaskType.EXECUTE,
                description="部署自动化任务",
                dependencies=["execute_1"],
                required_capabilities=['deployment', 'scheduling'],
                estimated_duration=30,
                priority=7,
                metadata={}
            ),
        ]
        return subtasks
    
    def _generate_generic_subtasks(self, goal: Goal) -> List[SubTask]:
        """生成通用子任务"""
        description_lower = goal.description.lower()
        
        # 检测是否涉及 3D 打印机
        has_3d_printer = any(kw in description_lower for kw in ['3d打印', '打印机', '3d print', 'printer'])
        # 检测是否涉及无人机
        has_drone = any(kw in description_lower for kw in ['无人机', '飞机', 'drone', 'uav'])
        
        subtasks = []
        
        if has_3d_printer:
            subtasks.append(SubTask(
                id="print_1",
                type=SubTaskType.CONTROL_DEVICE,
                description=f"使用 3D 打印机打印",
                dependencies=[],
                required_capabilities=['3d_printing', 'file_upload'],
                estimated_duration=120,
                priority=10,
                metadata={'device_type': '3d_printer'}
            ))
        
        if has_drone:
            subtasks.append(SubTask(
                id="drone_1",
                type=SubTaskType.CONTROL_DEVICE,
                description=f"控制无人机执行任务",
                dependencies=["print_1"] if has_3d_printer else [],
                required_capabilities=['drone_control', 'takeoff', 'land', 'capture_image'],
                estimated_duration=60,
                priority=9,
                metadata={'device_type': 'drone'}
            ))
        
        # 如果没有检测到特定设备，使用通用子任务
        if not subtasks:
            subtasks = [
                SubTask(
                    id="analyze_1",
                    type=SubTaskType.ANALYZE,
                    description=f"分析任务: {goal.description}",
                    dependencies=[],
                    required_capabilities=['text_understanding', 'analysis'],
                    estimated_duration=30,
                    priority=10,
                    metadata={}
                ),
                SubTask(
                    id="execute_1",
                    type=SubTaskType.EXECUTE,
                    description="执行任务",
                    dependencies=["analyze_1"],
                    required_capabilities=['task_execution', 'system_control'],
                    estimated_duration=90,
                    priority=9,
                    metadata={}
                ),
            ]
        
        return subtasks
    
    def _determine_execution_order(self, subtasks: List[SubTask]) -> List[str]:
        """确定执行顺序（拓扑排序）"""
        # 构建依赖图
        dep_graph = {st.id: st.dependencies for st in subtasks}
        
        # 拓扑排序
        order = []
        visited = set()
        
        def visit(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)
            
            # 先访问依赖
            for dep in dep_graph.get(task_id, []):
                visit(dep)
            
            order.append(task_id)
        
        # 访问所有任务
        for task in subtasks:
            visit(task.id)
        
        return order


if __name__ == '__main__':
    # 测试目标分解器
    logging.basicConfig(level=logging.INFO)
    
    decomposer = GoalDecomposer()
    
    # 测试信息收集目标
    goal = Goal(
        description="了解量子计算的最新进展",
        type=GoalType.INFORMATION_GATHERING,
        constraints=["使用可信来源", "时间限制 10 分钟"],
        success_criteria=["获得至少 3 个关键发现"],
        deadline=None
    )
    
    result = decomposer.decompose(goal)
    
    print(f"\n目标分解结果:")
    print(f"  目标: {result.goal.description}")
    print(f"  子任务数量: {len(result.subtasks)}")
    print(f"  执行顺序: {' -> '.join(result.execution_order)}")
    print(f"  预计时长: {result.estimated_total_duration} 秒")
    print(f"\n子任务详情:")
    for st in result.subtasks:
        print(f"  - {st.id}: {st.description}")
        print(f"    依赖: {st.dependencies or '无'}")
        print(f"    能力: {', '.join(st.required_capabilities)}")
