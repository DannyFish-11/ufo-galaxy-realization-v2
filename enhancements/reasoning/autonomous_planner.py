"""
自主规划器 (Autonomous Planner)
根据分解的子任务生成可执行的计划
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

from .goal_decomposer import SubTask, DecompositionResult

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """资源类型"""
    NODE = "node"
    DEVICE = "device"
    API = "api"
    TOOL = "tool"


@dataclass
class Resource:
    """资源"""
    id: str
    type: ResourceType
    name: str
    capabilities: List[str]
    availability: float  # 0-1
    metadata: Dict


@dataclass
class Action:
    """动作"""
    id: str
    subtask_id: str
    node_id: Optional[str]
    device_id: Optional[str]
    command: str
    parameters: Dict
    expected_duration: int
    fallback_actions: List['Action']


@dataclass
class Plan:
    """计划"""
    goal_description: str
    actions: List[Action]
    execution_order: List[str]  # Action IDs
    total_estimated_duration: int
    required_resources: List[Resource]
    contingency_plans: Dict[str, List[Action]]  # 应急计划


class AutonomousPlanner:
    """自主规划器"""
    
    def __init__(self, available_resources: Optional[List[Resource]] = None):
        self.available_resources = available_resources or []
        logger.info(f"AutonomousPlanner initialized with {len(self.available_resources)} resources")
    
    def create_plan(self, decomposition: DecompositionResult) -> Plan:
        """创建计划"""
        logger.info(f"开始为目标创建计划: {decomposition.goal.description}")
        
        # 1. 为每个子任务分配资源
        actions = []
        for subtask in decomposition.subtasks:
            action = self._create_action_for_subtask(subtask)
            if action:
                actions.append(action)
            else:
                logger.warning(f"无法为子任务创建动作: {subtask.id}")
        
        logger.info(f"创建了 {len(actions)} 个动作")
        
        # 2. 确定执行顺序
        execution_order = self._determine_action_order(actions, decomposition.execution_order)
        
        # 3. 识别所需资源
        required_resources = self._identify_required_resources(actions)
        
        # 4. 生成应急计划
        contingency_plans = self._generate_contingency_plans(actions)
        
        plan = Plan(
            goal_description=decomposition.goal.description,
            actions=actions,
            execution_order=execution_order,
            total_estimated_duration=decomposition.estimated_total_duration,
            required_resources=required_resources,
            contingency_plans=contingency_plans
        )
        
        logger.info(f"计划创建完成，包含 {len(actions)} 个动作")
        return plan
    
    def _create_action_for_subtask(self, subtask: SubTask) -> Optional[Action]:
        """为子任务创建动作"""
        # 查找匹配的资源
        matching_resources = self._find_matching_resources(subtask.required_capabilities)
        
        if not matching_resources:
            logger.warning(f"未找到匹配的资源: {subtask.id}")
            return None
        
        # 选择最佳资源
        best_resource = max(matching_resources, key=lambda r: r.availability)
        
        # 根据子任务类型生成命令
        command, parameters = self._generate_command(subtask, best_resource)
        
        action = Action(
            id=f"action_{subtask.id}",
            subtask_id=subtask.id,
            node_id=best_resource.id if best_resource.type == ResourceType.NODE else None,
            device_id=best_resource.id if best_resource.type == ResourceType.DEVICE else None,
            command=command,
            parameters=parameters,
            expected_duration=subtask.estimated_duration,
            fallback_actions=[]
        )
        
        return action
    
    def _find_matching_resources(self, required_capabilities: List[str]) -> List[Resource]:
        """查找匹配的资源"""
        matching = []
        
        for resource in self.available_resources:
            # 检查资源是否具备所有必需的能力
            if all(cap in resource.capabilities for cap in required_capabilities):
                matching.append(resource)
        
        return matching
    
    def _generate_command(self, subtask: SubTask, resource: Resource) -> tuple[str, Dict]:
        """生成命令"""
        command_map = {
            "search": ("web_search", {"query": subtask.description}),
            "read": ("read_file", {"path": ""}),
            "write": ("write_file", {"path": "", "content": ""}),
            "execute": ("execute_command", {"command": ""}),
            "analyze": ("analyze_data", {"data": ""}),
            "synthesize": ("synthesize_info", {"sources": []}),
            "control_device": ("device_control", {"action": ""}),
            "communicate": ("send_message", {"message": ""}),
        }
        
        command, params = command_map.get(subtask.type.value, ("unknown", {}))
        
        # 添加子任务描述到参数中
        params["description"] = subtask.description
        params["subtask_id"] = subtask.id
        
        return command, params
    
    def _determine_action_order(self, actions: List[Action], subtask_order: List[str]) -> List[str]:
        """确定动作执行顺序"""
        # 基于子任务顺序
        action_map = {a.subtask_id: a.id for a in actions}
        order = []
        
        for subtask_id in subtask_order:
            if subtask_id in action_map:
                order.append(action_map[subtask_id])
        
        return order
    
    def _identify_required_resources(self, actions: List[Action]) -> List[Resource]:
        """识别所需资源"""
        resource_ids = set()
        required = []
        
        for action in actions:
            if action.node_id and action.node_id not in resource_ids:
                resource_ids.add(action.node_id)
                # 查找资源
                for res in self.available_resources:
                    if res.id == action.node_id:
                        required.append(res)
                        break
            
            if action.device_id and action.device_id not in resource_ids:
                resource_ids.add(action.device_id)
                # 查找资源
                for res in self.available_resources:
                    if res.id == action.device_id:
                        required.append(res)
                        break
        
        return required
    
    def _generate_contingency_plans(self, actions: List[Action]) -> Dict[str, List[Action]]:
        """生成应急计划"""
        contingency = {}
        
        for action in actions:
            # 为每个动作生成备用方案
            fallback = self._generate_fallback_action(action)
            if fallback:
                contingency[action.id] = [fallback]
        
        return contingency
    
    def _generate_fallback_action(self, action: Action) -> Optional[Action]:
        """生成备用动作：使用相同命令但增加 retry 标记和降低超时"""
        fallback_params = dict(action.parameters)
        fallback_params["retry"] = True
        fallback_params["fallback_source"] = action.id

        # 尝试找到同 capability 的替代节点
        alt_node_id = action.node_id
        if action.node_id:
            for resource in self.available_resources:
                if (resource.id != action.node_id
                        and action.command in resource.capabilities
                        and resource.availability > 0.3):
                    alt_node_id = resource.id
                    break

        return Action(
            id=f"{action.id}_fallback",
            subtask_id=action.subtask_id,
            node_id=alt_node_id,
            device_id=action.device_id,
            command=action.command,
            parameters=fallback_params,
            expected_duration=min(action.expected_duration * 2, 300),
            fallback_actions=[],
        )
    
    def update_decision_weights(self, performance_metrics: Dict) -> None:
        """根据学习/优化输出更新规划器的决策权重"""
        try:
            avg_success_rate = performance_metrics.get('average_success_rate', 0.0)
            for resource in self.available_resources:
                if avg_success_rate < 0.5:
                    # Low success rate: reduce availability to encourage fallback paths
                    resource.availability = max(0.1, resource.availability * 0.9)
                elif avg_success_rate > 0.8:
                    # High success rate: gradually restore availability
                    resource.availability = min(1.0, resource.availability * 1.05)
            logger.info(
                f"决策权重已更新: 成功率={avg_success_rate:.1%}, "
                f"资源数={len(self.available_resources)}"
            )
        except Exception as e:
            logger.warning(f"更新决策权重失败: {e}")

    def update_plan(self, plan: Plan, feedback: Dict) -> Plan:
        """根据反馈更新计划。

        .. note:: **当前全仓没有调用方** —— 这不是遗漏,是有意保留现状。

            ``_generate_contingency_plans()`` 会为每个动作生成备用方案,
            但没有任何执行链路在失败后回来调用本方法,所以 ``contingency_plans``
            生成之后无人消费。天然的接入点是
            ``core/galaxy_main_loop_l4_enhanced.py::_process_goal()`` 第 3 步
            ``_execute_plan()`` 之后 —— 那里已经能拿到 ``ExecutionResult.action_id``
            和失败状态,数据是齐的。

            没有直接接上去的原因是:``ActionExecutor.execute_plan()`` 总是从
            ``execution_order`` 的**第 0 项**重头跑(见 action_executor.py:100),
            不支持从失败点续跑。因此"替换动作后重新执行"会把已经成功的动作
            连同副作用再跑一遍。要真正接通,需要先给执行器加上部分重放
            (partial re-execution)能力,并明确动作的幂等性约定 —— 那是一个
            设计决策,不是修个缺陷,故不在此擅自展开。

            本方法自身的替换逻辑是完整且安全的:替换保持原位置、执行顺序同步
            展开、用过的应急方案会被 pop 掉(因此同一动作不会反复回退成死循环),
            接通时可以直接依赖。
        """
        logger.info(f"根据反馈更新计划: {feedback}")
        
        # 如果某个动作失败，用它的应急动作替换掉。
        #
        # 此前这里只打一行日志就 return,替换动作与执行顺序的更新都停留在注释里 ——
        # _generate_contingency_plans() 为每个动作生成的备用方案(见第 198-208 行)
        # 因此从来没有被真正使用过:写进 plan.contingency_plans 就再也没人动它。
        if 'failed_action_id' in feedback:
            failed_id = feedback['failed_action_id']
            fallback_actions = plan.contingency_plans.get(failed_id) or []
            if fallback_actions:
                logger.info(
                    "使用应急计划替换失败的动作: %s -> %s",
                    failed_id,
                    [a.id for a in fallback_actions],
                )
                # 1) 动作列表:把失败动作替换为它的备用动作(保持原位置)
                new_actions: List[Action] = []
                for act in plan.actions:
                    if act.id == failed_id:
                        new_actions.extend(fallback_actions)
                    else:
                        new_actions.append(act)
                plan.actions = new_actions

                # 2) 执行顺序:同样在原位置展开,顺序语义才不会错乱
                new_order: List[str] = []
                for aid in plan.execution_order:
                    if aid == failed_id:
                        new_order.extend(a.id for a in fallback_actions)
                    else:
                        new_order.append(aid)
                plan.execution_order = new_order

                # 3) 该动作的应急方案已消耗,移除以避免同一动作反复回退成死循环
                plan.contingency_plans.pop(failed_id, None)
            else:
                logger.info("动作 %s 失败,但没有可用的应急计划", failed_id)

        return plan


if __name__ == '__main__':
    # 测试自主规划器
    logging.basicConfig(level=logging.INFO)
    
    from .goal_decomposer import GoalDecomposer, Goal, GoalType
    
    # 创建一些模拟资源
    resources = [
        Resource(
            id="node_13",
            type=ResourceType.NODE,
            name="Web Node",
            capabilities=['web_search', 'information_retrieval'],
            availability=1.0,
            metadata={}
        ),
        Resource(
            id="node_12",
            type=ResourceType.NODE,
            name="File Node",
            capabilities=['read_file', 'write_file', 'text_understanding', 'summarization'],
            availability=1.0,
            metadata={}
        ),
        Resource(
            id="node_50",
            type=ResourceType.NODE,
            name="AI Node",
            capabilities=['text_generation', 'analysis', 'synthesize_info'],
            availability=0.9,
            metadata={}
        ),
    ]
    
    # 创建目标分解
    decomposer = GoalDecomposer()
    goal = Goal(
        description="了解量子计算的最新进展",
        type=GoalType.INFORMATION_GATHERING,
        constraints=[],
        success_criteria=[],
        deadline=None
    )
    decomposition = decomposer.decompose(goal)
    
    # 创建计划
    planner = AutonomousPlanner(available_resources=resources)
    plan = planner.create_plan(decomposition)
    
    print(f"\n执行计划:")
    print(f"  目标: {plan.goal_description}")
    print(f"  动作数量: {len(plan.actions)}")
    print(f"  执行顺序: {' -> '.join(plan.execution_order)}")
    print(f"  所需资源: {len(plan.required_resources)} 个")
    print(f"\n动作详情:")
    for action in plan.actions:
        print(f"  - {action.id}:")
        print(f"    命令: {action.command}")
        print(f"    节点: {action.node_id or 'N/A'}")
        print(f"    参数: {action.parameters}")
