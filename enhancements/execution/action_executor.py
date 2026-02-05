"""
动作执行器 (Action Executor)
负责执行自主规划器生成的动作计划
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ExecutionResult:
    """执行结果"""
    action_id: str
    status: ExecutionStatus
    start_time: float
    end_time: float
    duration: float
    output: Any
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class ExecutionContext:
    """执行上下文"""
    plan_id: str
    goal_description: str
    start_time: float
    current_action_index: int
    total_actions: int
    results: List[ExecutionResult] = field(default_factory=list)
    shared_state: Dict = field(default_factory=dict)


class ActionExecutor:
    """动作执行器"""
    
    def __init__(self, node_registry: Optional[Dict] = None):
        """
        初始化动作执行器
        
        Args:
            node_registry: 节点注册表，格式为 {node_id: node_instance}
        """
        self.node_registry = node_registry or {}
        self.device_controllers = {}  # 设备控制器缓存
        self.execution_history: List[ExecutionContext] = []
        logger.info("ActionExecutor initialized")
    
    def register_node(self, node_id: str, node_instance: Any):
        """注册节点"""
        self.node_registry[node_id] = node_instance
        logger.info(f"注册节点: {node_id}")
    
    def register_device_controller(self, device_id: str, controller: Any):
        """注册设备控制器"""
        self.device_controllers[device_id] = controller
        logger.info(f"注册设备控制器: {device_id}")
    
    async def execute_plan(self, plan, world_model=None) -> ExecutionContext:
        """
        执行完整的计划
        
        Args:
            plan: 自主规划器生成的计划对象
            world_model: 世界模型实例（用于状态更新）
        
        Returns:
            ExecutionContext: 执行上下文，包含所有结果
        """
        logger.info(f"开始执行计划: {plan.goal_description}")
        
        # 创建执行上下文
        context = ExecutionContext(
            plan_id=f"plan_{int(time.time())}",
            goal_description=plan.goal_description,
            start_time=time.time(),
            current_action_index=0,
            total_actions=len(plan.actions)
        )
        
        # 按顺序执行动作
        for i, action_id in enumerate(plan.execution_order):
            context.current_action_index = i
            
            # 查找动作
            action = next((a for a in plan.actions if a.id == action_id), None)
            if not action:
                logger.error(f"未找到动作: {action_id}")
                continue
            
            logger.info(f"执行动作 {i+1}/{len(plan.execution_order)}: {action.command}")
            
            # 执行动作
            result = await self.execute_action(action, context, world_model)
            context.results.append(result)
            
            # 如果动作失败，检查是否有后备动作
            if result.status == ExecutionStatus.FAILED:
                logger.warning(f"动作失败: {action_id}, 状态: {result.error}")
                
                # 尝试执行后备动作
                if action.fallback_actions:
                    logger.info(f"尝试执行 {len(action.fallback_actions)} 个后备动作")
                    for fallback_action in action.fallback_actions:
                        fallback_result = await self.execute_action(fallback_action, context, world_model)
                        if fallback_result.status == ExecutionStatus.SUCCESS:
                            logger.info("后备动作执行成功")
                            context.results.append(fallback_result)
                            break
                    else:
                        logger.error("所有后备动作都失败")
                        # 根据策略决定是否继续
                        # 这里选择继续执行
                else:
                    logger.warning("没有后备动作，继续执行下一个动作")
            
            # 更新共享状态
            if result.output:
                context.shared_state[action_id] = result.output
        
        # 记录执行历史
        self.execution_history.append(context)
        
        # 计算总体成功率
        success_count = sum(1 for r in context.results if r.status == ExecutionStatus.SUCCESS)
        success_rate = success_count / len(context.results) if context.results else 0
        
        logger.info(f"计划执行完成: 成功率 {success_rate:.1%} ({success_count}/{len(context.results)})")
        
        return context
    
    async def execute_action(self, action, context: ExecutionContext, world_model=None) -> ExecutionResult:
        """
        执行单个动作
        
        Args:
            action: 动作对象
            context: 执行上下文
            world_model: 世界模型实例
        
        Returns:
            ExecutionResult: 执行结果
        """
        start_time = time.time()
        
        try:
            # 根据动作类型选择执行方式
            if action.node_id:
                # 通过节点执行
                output = await self._execute_via_node(action)
            elif action.device_id:
                # 通过设备控制器执行
                output = await self._execute_via_device(action)
            else:
                # 直接执行命令
                output = await self._execute_command(action)
            
            # 更新世界模型
            if world_model and action.device_id:
                await self._update_world_model(world_model, action, output)
            
            end_time = time.time()
            duration = end_time - start_time
            
            return ExecutionResult(
                action_id=action.id,
                status=ExecutionStatus.SUCCESS,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                output=output,
                metadata={
                    'command': action.command,
                    'parameters': action.parameters
                }
            )
        
        except asyncio.TimeoutError:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"动作执行超时: {action.id}")
            
            return ExecutionResult(
                action_id=action.id,
                status=ExecutionStatus.TIMEOUT,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                output=None,
                error="执行超时"
            )
        
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"动作执行失败: {action.id}, 错误: {e}")
            
            return ExecutionResult(
                action_id=action.id,
                status=ExecutionStatus.FAILED,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                output=None,
                error=str(e)
            )
    
    async def _execute_via_node(self, action) -> Any:
        """通过节点执行动作"""
        node_id = action.node_id
        
        if node_id not in self.node_registry:
            raise ValueError(f"节点未注册: {node_id}")
        
        node = self.node_registry[node_id]
        
        # 调用节点的执行方法
        if hasattr(node, 'execute'):
            result = await node.execute(action.command, action.parameters)
        elif hasattr(node, 'process'):
            result = await node.process(action.parameters)
        else:
            raise ValueError(f"节点 {node_id} 没有 execute 或 process 方法")
        
        return result
    
    async def _execute_via_device(self, action) -> Any:
        """通过设备控制器执行动作"""
        device_id = action.device_id
        
        if device_id not in self.device_controllers:
            # 尝试动态加载设备控制器
            controller = await self._load_device_controller(device_id)
            if controller:
                self.device_controllers[device_id] = controller
            else:
                raise ValueError(f"设备控制器未注册: {device_id}")
        
        controller = self.device_controllers[device_id]
        
        # 根据命令类型调用相应的方法
        command = action.command
        parameters = action.parameters
        
        # 设备控制命令映射
        if command == "device_control":
            # 通用设备控制
            if hasattr(controller, 'execute_command'):
                result = await controller.execute_command(parameters)
            else:
                result = await self._execute_device_command(controller, parameters)
        else:
            # 特定命令
            if hasattr(controller, command):
                method = getattr(controller, command)
                result = await method(**parameters)
            else:
                raise ValueError(f"设备控制器 {device_id} 不支持命令: {command}")
        
        return result
    
    async def _execute_command(self, action) -> Any:
        """直接执行命令"""
        command = action.command
        parameters = action.parameters
        
        # 命令执行逻辑
        logger.info(f"直接执行命令: {command}")
        
        # 这里可以添加更多的命令类型
        if command == "wait":
            duration = parameters.get("duration", 1)
            await asyncio.sleep(duration)
            return {"status": "completed", "duration": duration}
        
        elif command == "log":
            message = parameters.get("message", "")
            logger.info(f"日志: {message}")
            return {"status": "logged", "message": message}
        
        else:
            logger.warning(f"未知命令: {command}")
            return {"status": "unknown", "command": command}
    
    async def _load_device_controller(self, device_id: str) -> Optional[Any]:
        """动态加载设备控制器"""
        logger.info(f"尝试动态加载设备控制器: {device_id}")
        
        try:
            # 根据设备 ID 加载相应的控制器
            if "mavlink" in device_id.lower() or "drone" in device_id.lower():
                from nodes.Node_43_MAVLink.mavlink_controller import MAVLinkController
                controller = MAVLinkController()
                logger.info(f"加载 MAVLink 控制器: {device_id}")
                return controller
            
            elif "octoprint" in device_id.lower() or "printer" in device_id.lower():
                from nodes.Node_49_OctoPrint.octoprint_controller import OctoPrintController
                controller = OctoPrintController()
                logger.info(f"加载 OctoPrint 控制器: {device_id}")
                return controller
            
            else:
                logger.warning(f"未知设备类型: {device_id}")
                return None
        
        except Exception as e:
            logger.error(f"加载设备控制器失败: {device_id}, 错误: {e}")
            return None
    
    async def _execute_device_command(self, controller, parameters: Dict) -> Any:
        """执行设备命令"""
        # 从参数中提取子任务描述
        description = parameters.get("description", "")
        subtask_id = parameters.get("subtask_id", "")
        
        logger.info(f"执行设备命令: {description}")
        
        # 根据描述推断具体操作
        description_lower = description.lower()
        
        # 无人机操作
        if "起飞" in description or "takeoff" in description_lower:
            if hasattr(controller, 'takeoff'):
                altitude = parameters.get("altitude", 10)
                return await controller.takeoff(altitude)
        
        elif "降落" in description or "land" in description_lower:
            if hasattr(controller, 'land'):
                return await controller.land()
        
        elif "拍照" in description or "photo" in description_lower or "capture" in description_lower:
            if hasattr(controller, 'capture_image'):
                return await controller.capture_image()
        
        # 3D 打印机操作
        elif "打印" in description or "print" in description_lower:
            if hasattr(controller, 'start_print'):
                file_path = parameters.get("file_path", "")
                return await controller.start_print(file_path)
        
        # 通用执行
        elif hasattr(controller, 'execute'):
            return await controller.execute(description, parameters)
        
        else:
            logger.warning(f"无法执行设备命令: {description}")
            return {"status": "not_implemented", "description": description}
    
    async def _update_world_model(self, world_model, action, output):
        """更新世界模型"""
        try:
            device_id = action.device_id
            
            # 更新设备状态
            if hasattr(world_model, 'update_entity_state'):
                world_model.update_entity_state(device_id, {
                    'last_action': action.command,
                    'last_update': time.time(),
                    'output': output
                })
            
            logger.debug(f"更新世界模型: {device_id}")
        
        except Exception as e:
            logger.warning(f"更新世界模型失败: {e}")
    
    def get_execution_summary(self, context: ExecutionContext) -> Dict:
        """获取执行摘要"""
        total_duration = sum(r.duration for r in context.results)
        success_count = sum(1 for r in context.results if r.status == ExecutionStatus.SUCCESS)
        failed_count = sum(1 for r in context.results if r.status == ExecutionStatus.FAILED)
        
        return {
            'plan_id': context.plan_id,
            'goal': context.goal_description,
            'total_actions': context.total_actions,
            'executed_actions': len(context.results),
            'success_count': success_count,
            'failed_count': failed_count,
            'success_rate': success_count / len(context.results) if context.results else 0,
            'total_duration': total_duration,
            'average_duration': total_duration / len(context.results) if context.results else 0,
            'start_time': context.start_time,
            'end_time': context.results[-1].end_time if context.results else context.start_time
        }
    
    def get_execution_history(self, limit: int = 10) -> List[Dict]:
        """获取执行历史"""
        history = []
        for context in self.execution_history[-limit:]:
            summary = self.get_execution_summary(context)
            history.append(summary)
        return history
