"""
UFO³ Galaxy - 复杂任务分解和跨设备协同模块

功能：
1. 复杂任务分解 - 将复杂任务分解为多个子任务
2. 跨设备协同 - 管理跨设备的数据传递和协同
3. 数据流管理 - 管理任务间的数据流转
4. 智能规划 - 根据设备能力智能规划任务

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# ============================================================================
# 复杂任务类型
# ============================================================================

class ComplexTaskType(Enum):
    """复杂任务类型"""
    FILE_TRANSFER = "file_transfer"           # 文件传输
    CROSS_DEVICE_WORKFLOW = "cross_device_workflow"  # 跨设备工作流
    MULTI_STEP_OPERATION = "multi_step_operation"    # 多步操作
    CONDITIONAL_TASK = "conditional_task"     # 条件任务
    LOOP_TASK = "loop_task"                   # 循环任务

@dataclass
class DataFlow:
    """数据流"""
    from_task_id: str
    to_task_id: str
    data_key: str  # 数据键名
    transform: Optional[str]  # 数据转换函数（可选）

# ============================================================================
# 任务分解器
# ============================================================================

class TaskDecomposer:
    """任务分解器 - 将复杂任务分解为多个子任务"""
    
    def __init__(self, device_registry):
        """
        初始化任务分解器
        
        Args:
            device_registry: 设备注册表
        """
        self.device_registry = device_registry
    
    def decompose_file_transfer(
        self,
        source_device_id: str,
        target_device_id: str,
        file_path: str,
        task_id_prefix: str = "task"
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        分解文件传输任务
        
        Args:
            source_device_id: 源设备 ID
            target_device_id: 目标设备 ID
            file_path: 文件路径
            task_id_prefix: 任务 ID 前缀
        
        Returns:
            (任务列表, 数据流列表)
        """
        from enhanced_nlu_v2 import Task, IntentType
        
        tasks = []
        data_flows = []
        
        # 任务 1: 在源设备上读取文件
        task_1 = Task(
            task_id=f"{task_id_prefix}_1_read",
            device_id=source_device_id,
            intent_type=IntentType.FILE_OPERATION,
            action="read_file",
            target=file_path,
            parameters={"file_path": file_path},
            depends_on=[],
            confidence=0.95,
            estimated_duration=2.0
        )
        tasks.append(task_1)
        
        # 任务 2: 在目标设备上写入文件
        task_2 = Task(
            task_id=f"{task_id_prefix}_2_write",
            device_id=target_device_id,
            intent_type=IntentType.FILE_OPERATION,
            action="write_file",
            target=file_path,
            parameters={"file_path": file_path},
            depends_on=[task_1.task_id],
            confidence=0.95,
            estimated_duration=2.0
        )
        tasks.append(task_2)
        
        # 数据流: 任务 1 的输出 -> 任务 2 的输入
        data_flow = DataFlow(
            from_task_id=task_1.task_id,
            to_task_id=task_2.task_id,
            data_key="file_content",
            transform=None
        )
        data_flows.append(data_flow)
        
        return tasks, data_flows
    
    def decompose_send_and_open(
        self,
        source_device_id: str,
        target_device_id: str,
        file_path: str,
        app_to_open: str,
        task_id_prefix: str = "task"
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        分解"发送并打开"任务
        例如："把手机上的照片发到电脑，然后用 PS 打开"
        
        Args:
            source_device_id: 源设备 ID
            target_device_id: 目标设备 ID
            file_path: 文件路径
            app_to_open: 要打开的应用
            task_id_prefix: 任务 ID 前缀
        
        Returns:
            (任务列表, 数据流列表)
        """
        from enhanced_nlu_v2 import Task, IntentType
        
        tasks = []
        data_flows = []
        
        # 步骤 1: 传输文件
        transfer_tasks, transfer_flows = self.decompose_file_transfer(
            source_device_id, target_device_id, file_path, task_id_prefix
        )
        tasks.extend(transfer_tasks)
        data_flows.extend(transfer_flows)
        
        # 步骤 2: 在目标设备上用指定应用打开文件
        task_3 = Task(
            task_id=f"{task_id_prefix}_3_open",
            device_id=target_device_id,
            intent_type=IntentType.APP_OPERATION,
            action="open_file_with_app",
            target=app_to_open,
            parameters={
                "file_path": file_path,
                "app": app_to_open
            },
            depends_on=[transfer_tasks[-1].task_id],  # 依赖传输完成
            confidence=0.90,
            estimated_duration=3.0
        )
        tasks.append(task_3)
        
        return tasks, data_flows
    
    def decompose_multi_device_command(
        self,
        commands: List[Dict[str, Any]],
        task_id_prefix: str = "task"
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        分解多设备命令
        例如："在手机 A 上打开微信，在平板上播放音乐，在电脑上打开 Chrome"
        
        Args:
            commands: 命令列表，每个命令包含 device_id, action, target
            task_id_prefix: 任务 ID 前缀
        
        Returns:
            (任务列表, 数据流列表)
        """
        from enhanced_nlu_v2 import Task, IntentType
        
        tasks = []
        data_flows = []  # 并行任务，没有数据流
        
        for i, command in enumerate(commands):
            task = Task(
                task_id=f"{task_id_prefix}_{i+1}",
                device_id=command["device_id"],
                intent_type=IntentType.APP_CONTROL,
                action=command["action"],
                target=command["target"],
                parameters=command.get("parameters", {}),
                depends_on=[],  # 并行执行，没有依赖
                confidence=command.get("confidence", 0.90),
                estimated_duration=command.get("estimated_duration", 2.0)
            )
            tasks.append(task)
        
        return tasks, data_flows
    
    def decompose_search_and_open(
        self,
        device_id: str,
        browser: str,
        search_keyword: str,
        task_id_prefix: str = "task"
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        分解"搜索并打开"任务
        例如："在电脑上打开 Chrome 并搜索 Python 教程"
        
        Args:
            device_id: 设备 ID
            browser: 浏览器名称
            search_keyword: 搜索关键词
            task_id_prefix: 任务 ID 前缀
        
        Returns:
            (任务列表, 数据流列表)
        """
        from enhanced_nlu_v2 import Task, IntentType
        
        tasks = []
        data_flows = []
        
        # 任务 1: 打开浏览器
        task_1 = Task(
            task_id=f"{task_id_prefix}_1_open_browser",
            device_id=device_id,
            intent_type=IntentType.APP_CONTROL,
            action="open",
            target=browser,
            parameters={},
            depends_on=[],
            confidence=0.95,
            estimated_duration=2.0
        )
        tasks.append(task_1)
        
        # 任务 2: 搜索
        task_2 = Task(
            task_id=f"{task_id_prefix}_2_search",
            device_id=device_id,
            intent_type=IntentType.APP_OPERATION,
            action="search",
            target=browser,
            parameters={"keyword": search_keyword},
            depends_on=[task_1.task_id],
            confidence=0.90,
            estimated_duration=1.0
        )
        tasks.append(task_2)
        
        return tasks, data_flows
    
    def decompose_conditional_task(
        self,
        condition_task: Any,
        true_tasks: List[Any],
        false_tasks: List[Any],
        task_id_prefix: str = "task"
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        分解条件任务
        例如："如果手机 A 在线，就在手机 A 上打开微信，否则在手机 B 上打开"
        
        Args:
            condition_task: 条件判断任务
            true_tasks: 条件为真时执行的任务
            false_tasks: 条件为假时执行的任务
            task_id_prefix: 任务 ID 前缀
        
        Returns:
            (任务列表, 数据流列表)
        """
        # 这个功能需要运行时支持条件判断
        # 这里只是示例框架
        tasks = [condition_task]
        data_flows = []
        
        # 标记条件分支
        for task in true_tasks:
            task.parameters["condition"] = "true"
            task.depends_on.append(condition_task.task_id)
            tasks.append(task)
        
        for task in false_tasks:
            task.parameters["condition"] = "false"
            task.depends_on.append(condition_task.task_id)
            tasks.append(task)
        
        return tasks, data_flows

# ============================================================================
# 跨设备协同管理器
# ============================================================================

class CrossDeviceCoordinator:
    """跨设备协同管理器"""
    
    def __init__(self, device_registry):
        """
        初始化协同管理器
        
        Args:
            device_registry: 设备注册表
        """
        self.device_registry = device_registry
        self.decomposer = TaskDecomposer(device_registry)
    
    def plan_cross_device_task(
        self,
        task_description: str,
        involved_devices: List[str]
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        规划跨设备任务
        
        Args:
            task_description: 任务描述
            involved_devices: 涉及的设备列表
        
        Returns:
            (任务列表, 数据流列表)
        """
        # 这里可以使用 LLM 来理解任务描述并规划
        # 目前返回空列表
        return [], []
    
    def optimize_task_placement(
        self,
        tasks: List[Any]
    ) -> List[Any]:
        """
        优化任务放置 - 根据设备能力和负载智能分配任务
        
        Args:
            tasks: 任务列表
        
        Returns:
            优化后的任务列表
        """
        optimized_tasks = []
        
        for task in tasks:
            # 检查目标设备是否支持该任务
            device = self.device_registry.get_device(task.device_id)
            
            if not device:
                # 设备不存在，尝试找替代设备
                alternative = self._find_alternative_device(task)
                if alternative:
                    task.device_id = alternative.device_id
                    task.parameters["original_device"] = device
            
            elif task.target and task.target not in device.capabilities:
                # 设备不支持该应用，尝试找替代设备
                alternative = self._find_alternative_device(task)
                if alternative:
                    task.device_id = alternative.device_id
                    task.parameters["original_device"] = device.device_id
            
            optimized_tasks.append(task)
        
        return optimized_tasks
    
    def _find_alternative_device(self, task: Any):
        """查找替代设备"""
        from enhanced_nlu_v2 import DeviceStatus
        
        # 查找支持该应用的在线设备
        for device in self.device_registry.get_online_devices():
            if task.target and task.target in device.capabilities:
                return device
        
        return None

# ============================================================================
# 智能任务规划器
# ============================================================================

class IntelligentTaskPlanner:
    """智能任务规划器 - 使用 LLM 进行智能规划"""
    
    def __init__(self, device_registry, llm_client):
        """
        初始化智能规划器
        
        Args:
            device_registry: 设备注册表
            llm_client: LLM 客户端
        """
        self.device_registry = device_registry
        self.llm_client = llm_client
        self.decomposer = TaskDecomposer(device_registry)
    
    async def plan_complex_task(
        self,
        user_input: str,
        context: Any = None
    ) -> tuple[List[Any], List[DataFlow]]:
        """
        规划复杂任务
        
        Args:
            user_input: 用户输入
            context: 上下文
        
        Returns:
            (任务列表, 数据流列表)
        """
        # 构建设备信息
        devices_info = []
        for device in self.device_registry.get_online_devices():
            devices_info.append({
                "device_id": device.device_id,
                "device_name": device.device_name,
                "device_type": device.device_type.value,
                "capabilities": device.capabilities
            })
        
        # 构建 Prompt
        system_prompt = """你是 UFO³ Galaxy 的任务规划专家。你的任务是将用户的复杂指令分解为多个可执行的子任务。

请严格按照以下 JSON 格式输出：
{
  "tasks": [
    {
      "task_id": "task_1",
      "device_id": "设备ID",
      "intent_type": "意图类型",
      "action": "动作",
      "target": "目标",
      "parameters": {},
      "depends_on": [],
      "confidence": 0.95,
      "estimated_duration": 2.0
    }
  ],
  "data_flows": [
    {
      "from_task_id": "task_1",
      "to_task_id": "task_2",
      "data_key": "数据键名",
      "transform": null
    }
  ],
  "explanation": "任务分解的解释"
}

注意：
1. 识别任务之间的依赖关系
2. 识别需要跨设备传输的数据
3. 合理估计每个任务的执行时间
4. 确保任务顺序符合逻辑
"""
        
        user_prompt = f"""可用设备：
{json.dumps(devices_info, ensure_ascii=False, indent=2)}

用户输入："{user_input}"

请将这个复杂任务分解为多个子任务，并输出 JSON 格式的结果。"""
        
        # 调用 LLM
        try:
            response = await self.llm_client.generate(user_prompt, system_prompt)
            result_data = json.loads(response)
            
            # 解析任务
            from enhanced_nlu_v2 import Task, IntentType
            
            tasks = []
            for task_data in result_data.get("tasks", []):
                task = Task(
                    task_id=task_data["task_id"],
                    device_id=task_data["device_id"],
                    intent_type=IntentType(task_data["intent_type"]),
                    action=task_data["action"],
                    target=task_data.get("target"),
                    parameters=task_data.get("parameters", {}),
                    depends_on=task_data.get("depends_on", []),
                    confidence=task_data.get("confidence", 0.8),
                    estimated_duration=task_data.get("estimated_duration", 2.0)
                )
                tasks.append(task)
            
            # 解析数据流
            data_flows = []
            for flow_data in result_data.get("data_flows", []):
                flow = DataFlow(
                    from_task_id=flow_data["from_task_id"],
                    to_task_id=flow_data["to_task_id"],
                    data_key=flow_data["data_key"],
                    transform=flow_data.get("transform")
                )
                data_flows.append(flow)
            
            return tasks, data_flows
        
        except Exception as e:
            print(f"LLM planning error: {e}")
            return [], []

# ============================================================================
# 使用示例
# ============================================================================

async def main():
    """测试示例"""
    from enhanced_nlu_v2 import DeviceRegistry, LLMClient
    
    # 初始化组件
    device_registry = DeviceRegistry()
    llm_client = LLMClient(provider="ollama")
    
    # 初始化任务分解器
    decomposer = TaskDecomposer(device_registry)
    
    print("="*80)
    print("UFO³ Galaxy - 复杂任务分解测试")
    print("="*80)
    
    # 测试 1: 文件传输
    print("\n测试 1: 文件传输")
    print("-"*80)
    tasks, flows = decomposer.decompose_file_transfer(
        source_device_id="phone_a",
        target_device_id="pc",
        file_path="/sdcard/photo.jpg"
    )
    print(f"任务数: {len(tasks)}")
    print(f"数据流: {len(flows)}")
    for task in tasks:
        print(f"  - {task.task_id}: {task.action} on {task.device_id}")
    
    # 测试 2: 发送并打开
    print("\n测试 2: 发送并打开")
    print("-"*80)
    tasks, flows = decomposer.decompose_send_and_open(
        source_device_id="phone_a",
        target_device_id="pc",
        file_path="/sdcard/photo.jpg",
        app_to_open="photoshop"
    )
    print(f"任务数: {len(tasks)}")
    print(f"数据流: {len(flows)}")
    for task in tasks:
        print(f"  - {task.task_id}: {task.action} on {task.device_id}")
        if task.depends_on:
            print(f"    依赖: {task.depends_on}")
    
    # 测试 3: 多设备命令
    print("\n测试 3: 多设备命令")
    print("-"*80)
    commands = [
        {"device_id": "phone_b", "action": "open", "target": "wechat"},
        {"device_id": "tablet", "action": "play", "target": "music"},
        {"device_id": "pc", "action": "open", "target": "chrome"}
    ]
    tasks, flows = decomposer.decompose_multi_device_command(commands)
    print(f"任务数: {len(tasks)}")
    for task in tasks:
        print(f"  - {task.task_id}: {task.action} {task.target} on {task.device_id}")
    
    # 测试 4: 智能规划（使用 LLM）
    print("\n测试 4: 智能规划")
    print("-"*80)
    planner = IntelligentTaskPlanner(device_registry, llm_client)
    tasks, flows = await planner.plan_complex_task(
        "把手机 A 上的照片发到电脑，然后用 PS 打开"
    )
    print(f"任务数: {len(tasks)}")
    print(f"数据流: {len(flows)}")
    for task in tasks:
        print(f"  - {task.task_id}: {task.action} on {task.device_id}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
