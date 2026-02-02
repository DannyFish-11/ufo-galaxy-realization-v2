"""
GalaxyOrchestrator - UFO Galaxy 统一调度器
核心调度模块，串联端到端流程
"""

import asyncio
import json
import time
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import uuid

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(Enum):
    """节点状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    MAINTENANCE = "maintenance"


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    request: str
    intent: Dict[str, Any] = field(default_factory=dict)
    subtasks: List[Dict] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    target_device: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Node:
    """节点数据类"""
    node_id: str
    node_type: str
    capabilities: List[str]
    status: NodeStatus = NodeStatus.ONLINE
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_task: Optional[str] = None


class AIGateway:
    """AI 网关 - 处理意图理解和任务分解"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_endpoint = config.get("model_endpoint", "http://localhost:8000")
        self.api_key = config.get("api_key", "")

    async def understand_intent(self, request: str, context: Dict = None) -> Dict[str, Any]:
        """理解用户意图"""
        logger.info(f"理解意图: {request}")

        # 模拟意图理解（实际应调用 LLM API）
        intent = {
            "original_request": request,
            "intent_type": self._classify_intent(request),
            "entities": self._extract_entities(request),
            "confidence": 0.95,
            "timestamp": time.time()
        }

        if context:
            intent["context"] = context

        return intent

    def _classify_intent(self, request: str) -> str:
        """分类意图类型"""
        request_lower = request.lower()
        if any(word in request_lower for word in ["查询", "搜索", "find", "search"]):
            return "query"
        elif any(word in request_lower for word in ["控制", "打开", "关闭", "control"]):
            return "control"
        elif any(word in request_lower for word in ["分析", "统计", "analyze"]):
            return "analysis"
        elif any(word in request_lower for word in ["创建", "生成", "create", "generate"]):
            return "creation"
        return "general"

    def _extract_entities(self, request: str) -> List[Dict]:
        """提取实体"""
        entities = []
        # 简单实体提取（实际应使用 NER 模型）
        return entities

    async def decompose_task(self, intent: Dict[str, Any]) -> List[Dict]:
        """分解任务为子任务"""
        logger.info(f"分解任务: {intent.get('intent_type')}")

        intent_type = intent.get("intent_type", "general")

        # 根据意图类型分解任务
        subtasks = []

        if intent_type == "query":
            subtasks = [
                {"type": "parse_query", "priority": 1},
                {"type": "fetch_data", "priority": 2},
                {"type": "format_result", "priority": 3}
            ]
        elif intent_type == "control":
            subtasks = [
                {"type": "validate_command", "priority": 1},
                {"type": "execute_control", "priority": 2},
                {"type": "confirm_result", "priority": 3}
            ]
        elif intent_type == "analysis":
            subtasks = [
                {"type": "collect_data", "priority": 1},
                {"type": "process_analysis", "priority": 2},
                {"type": "generate_report", "priority": 3}
            ]
        else:
            subtasks = [
                {"type": "process_general", "priority": 1}
            ]

        # 添加任务ID和依赖关系
        for i, subtask in enumerate(subtasks):
            subtask["subtask_id"] = f"subtask_{uuid.uuid4().hex[:8]}"
            subtask["dependencies"] = [subtasks[j]["subtask_id"] for j in range(i)] if i > 0 else []
            subtask["status"] = "pending"

        return subtasks


class DeviceManager:
    """设备管理器 - 管理设备生命周期"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.devices: Dict[str, Dict] = {}
        self.device_handlers: Dict[str, Callable] = {}

    def register_device(self, device_id: str, device_info: Dict):
        """注册设备"""
        self.devices[device_id] = {
            "device_id": device_id,
            "device_type": device_info.get("type", "unknown"),
            "capabilities": device_info.get("capabilities", []),
            "status": "online",
            "registered_at": time.time(),
            **device_info
        }
        logger.info(f"设备已注册: {device_id}")

    def unregister_device(self, device_id: str):
        """注销设备"""
        if device_id in self.devices:
            del self.devices[device_id]
            logger.info(f"设备已注销: {device_id}")

    def get_device(self, device_id: str) -> Optional[Dict]:
        """获取设备信息"""
        return self.devices.get(device_id)

    def list_devices(self, device_type: str = None) -> List[Dict]:
        """列出所有设备"""
        devices = list(self.devices.values())
        if device_type:
            devices = [d for d in devices if d.get("device_type") == device_type]
        return devices

    def find_device_for_task(self, task: Dict) -> Optional[str]:
        """为任务找到合适的设备"""
        task_type = task.get("type", "")

        for device_id, device in self.devices.items():
            if device.get("status") != "online":
                continue
            capabilities = device.get("capabilities", [])
            if task_type in capabilities or "*" in capabilities:
                return device_id

        return None

    async def execute_on_device(self, device_id: str, command: Dict) -> Dict:
        """在设备上执行命令"""
        device = self.devices.get(device_id)
        if not device:
            return {"success": False, "error": f"设备不存在: {device_id}"}

        # 模拟设备执行（实际应调用设备API）
        logger.info(f"在设备 {device_id} 上执行: {command}")

        # 模拟执行延迟
        await asyncio.sleep(0.1)

        return {
            "success": True,
            "device_id": device_id,
            "command": command,
            "result": f"Executed on {device_id}",
            "timestamp": time.time()
        }


class GalaxyOrchestrator:
    """UFO Galaxy 统一调度器 - 串联端到端流程"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化调度器

        Args:
            config: 配置字典，包含AI网关、设备管理等配置
        """
        self.config = config

        # 初始化AI网关
        self.gateway = AIGateway(config.get("ai_gateway", {}))

        # 节点注册表
        self.node_registry: Dict[str, Node] = {}

        # 设备管理器
        self.device_manager = DeviceManager(config.get("device_manager", {}))

        # 任务队列
        self.task_queue: List[Task] = []

        # 任务历史
        self.task_history: Dict[str, Task] = {}

        # 运行状态
        self.is_running = False

        # 统计信息
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "start_time": None
        }

        logger.info("GalaxyOrchestrator 初始化完成")

    async def start(self):
        """启动调度器"""
        self.is_running = True
        self.stats["start_time"] = time.time()
        logger.info("GalaxyOrchestrator 已启动")

        # 启动后台任务
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._task_processor_loop())

    async def stop(self):
        """停止调度器"""
        self.is_running = False
        logger.info("GalaxyOrchestrator 已停止")

    async def process_request(self, request: str, context: Dict = None) -> Dict:
        """
        处理用户请求的主入口

        Args:
            request: 用户请求（自然语言或结构化指令）
            context: 上下文信息

        Returns:
            处理结果字典
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        logger.info(f"[{task_id}] 开始处理请求: {request}")

        # 创建任务
        task = Task(
            task_id=task_id,
            request=request,
            context=context or {}
        )
        self.task_queue.append(task)
        self.task_history[task_id] = task
        self.stats["total_tasks"] += 1

        try:
            # 1. 意图理解
            logger.info(f"[{task_id}] 步骤1: 意图理解")
            intent = await self.gateway.understand_intent(request, context)
            task.intent = intent

            # 2. 任务分解
            logger.info(f"[{task_id}] 步骤2: 任务分解")
            subtasks = await self.gateway.decompose_task(intent)
            task.subtasks = subtasks

            # 3. 节点调度与执行
            logger.info(f"[{task_id}] 步骤3: 节点调度")
            results = await self._execute_subtasks(task)

            # 4. 结果聚合
            logger.info(f"[{task_id}] 步骤4: 结果聚合")
            final_result = self._aggregate_results(results, intent)
            task.result = final_result
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            self.stats["completed_tasks"] += 1

            logger.info(f"[{task_id}] 请求处理完成")

            return {
                "success": True,
                "task_id": task_id,
                "intent": intent,
                "result": final_result,
                "execution_time": task.completed_at - task.created_at
            }

        except Exception as e:
            logger.error(f"[{task_id}] 处理失败: {str(e)}")
            task.status = TaskStatus.FAILED
            task.result = {"error": str(e)}
            self.stats["failed_tasks"] += 1

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }

    async def _execute_subtasks(self, task: Task) -> List[Dict]:
        """执行子任务"""
        results = []

        # 按优先级排序
        sorted_subtasks = sorted(task.subtasks, key=lambda x: x.get("priority", 99))

        for subtask in sorted_subtasks:
            subtask_id = subtask.get("subtask_id")
            logger.info(f"执行子任务: {subtask_id}")

            # 检查依赖
            dependencies = subtask.get("dependencies", [])
            for dep_id in dependencies:
                dep_result = next((r for r in results if r.get("subtask_id") == dep_id), None)
                if not dep_result or not dep_result.get("success"):
                    results.append({
                        "subtask_id": subtask_id,
                        "success": False,
                        "error": f"依赖任务失败: {dep_id}"
                    })
                    continue

            # 找到合适的设备
            device_id = self.device_manager.find_device_for_task(subtask)

            if device_id:
                # 在设备上执行
                result = await self.device_manager.execute_on_device(device_id, subtask)
            else:
                # 本地执行
                result = await self._execute_locally(subtask)

            result["subtask_id"] = subtask_id
            results.append(result)
            subtask["status"] = "completed" if result.get("success") else "failed"

        return results

    async def _execute_locally(self, subtask: Dict) -> Dict:
        """本地执行任务"""
        task_type = subtask.get("type", "")

        # 本地任务处理器
        handlers = {
            "parse_query": self._handle_parse_query,
            "format_result": self._handle_format_result,
            "validate_command": self._handle_validate_command,
            "confirm_result": self._handle_confirm_result,
            "process_general": self._handle_process_general
        }

        handler = handlers.get(task_type, self._handle_default)
        return await handler(subtask)

    async def _handle_parse_query(self, subtask: Dict) -> Dict:
        """处理查询解析"""
        return {"success": True, "data": {"parsed": True}}

    async def _handle_format_result(self, subtask: Dict) -> Dict:
        """处理结果格式化"""
        return {"success": True, "data": {"formatted": True}}

    async def _handle_validate_command(self, subtask: Dict) -> Dict:
        """处理命令验证"""
        return {"success": True, "data": {"validated": True}}

    async def _handle_confirm_result(self, subtask: Dict) -> Dict:
        """处理结果确认"""
        return {"success": True, "data": {"confirmed": True}}

    async def _handle_process_general(self, subtask: Dict) -> Dict:
        """处理通用任务"""
        return {"success": True, "data": {"processed": True}}

    async def _handle_default(self, subtask: Dict) -> Dict:
        """默认处理器"""
        return {"success": True, "data": {"handled": True}}

    def _aggregate_results(self, results: List[Dict], intent: Dict) -> Dict:
        """聚合子任务结果"""
        success_count = sum(1 for r in results if r.get("success"))
        total_count = len(results)

        return {
            "intent_type": intent.get("intent_type"),
            "subtask_results": results,
            "summary": {
                "total_subtasks": total_count,
                "successful": success_count,
                "failed": total_count - success_count
            },
            "output": self._generate_output(results, intent)
        }

    def _generate_output(self, results: List[Dict], intent: Dict) -> str:
        """生成最终输出"""
        intent_type = intent.get("intent_type", "general")

        outputs = {
            "query": "查询结果已生成",
            "control": "控制命令已执行",
            "analysis": "分析报告已生成",
            "creation": "创建任务已完成",
            "general": "请求已处理"
        }

        return outputs.get(intent_type, "处理完成")

    async def execute_task(self, task: Dict, target_device: str = None) -> Dict:
        """
        执行单个任务

        Args:
            task: 任务字典
            target_device: 目标设备ID（可选）

        Returns:
            执行结果
        """
        if target_device:
            return await self.device_manager.execute_on_device(target_device, task)
        else:
            device_id = self.device_manager.find_device_for_task(task)
            if device_id:
                return await self.device_manager.execute_on_device(device_id, task)
            else:
                return await self._execute_locally(task)

    def register_node(self, node_id: str, node_info: Dict):
        """
        注册节点

        Args:
            node_id: 节点ID
            node_info: 节点信息
        """
        node = Node(
            node_id=node_id,
            node_type=node_info.get("type", "generic"),
            capabilities=node_info.get("capabilities", []),
            metadata=node_info.get("metadata", {})
        )
        self.node_registry[node_id] = node
        logger.info(f"节点已注册: {node_id}")

    def unregister_node(self, node_id: str):
        """注销节点"""
        if node_id in self.node_registry:
            del self.node_registry[node_id]
            logger.info(f"节点已注销: {node_id}")

    def update_node_status(self, node_id: str, status: NodeStatus):
        """更新节点状态"""
        if node_id in self.node_registry:
            self.node_registry[node_id].status = status
            self.node_registry[node_id].last_heartbeat = time.time()

    def get_system_status(self) -> Dict:
        """
        获取系统状态

        Returns:
            系统状态字典
        """
        uptime = 0
        if self.stats["start_time"]:
            uptime = time.time() - self.stats["start_time"]

        return {
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "nodes": {
                "total": len(self.node_registry),
                "online": sum(1 for n in self.node_registry.values() if n.status == NodeStatus.ONLINE),
                "busy": sum(1 for n in self.node_registry.values() if n.status == NodeStatus.BUSY)
            },
            "devices": {
                "total": len(self.device_manager.devices),
                "online": sum(1 for d in self.device_manager.devices.values() if d.get("status") == "online")
            },
            "tasks": {
                "total": self.stats["total_tasks"],
                "completed": self.stats["completed_tasks"],
                "failed": self.stats["failed_tasks"],
                "pending": len(self.task_queue)
            },
            "timestamp": time.time()
        }

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        task = self.task_history.get(task_id)
        if task:
            return {
                "task_id": task.task_id,
                "status": task.status.value,
                "request": task.request,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
                "result": task.result
            }
        return None

    async def _heartbeat_loop(self):
        """心跳循环 - 检查节点健康状态"""
        while self.is_running:
            try:
                current_time = time.time()
                timeout = 60  # 60秒超时

                for node_id, node in list(self.node_registry.items()):
                    if current_time - node.last_heartbeat > timeout:
                        if node.status != NodeStatus.OFFLINE:
                            logger.warning(f"节点超时: {node_id}")
                            node.status = NodeStatus.OFFLINE

                await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"心跳循环错误: {e}")
                await asyncio.sleep(10)

    async def _task_processor_loop(self):
        """任务处理循环"""
        while self.is_running:
            try:
                # 处理队列中的任务
                if self.task_queue:
                    # 任务已在process_request中处理
                    pass

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"任务处理循环错误: {e}")
                await asyncio.sleep(1)


# 便捷函数
async def create_orchestrator(config: Dict[str, Any] = None) -> GalaxyOrchestrator:
    """创建并启动调度器"""
    config = config or {}
    orchestrator = GalaxyOrchestrator(config)
    await orchestrator.start()
    return orchestrator


# 示例用法
if __name__ == "__main__":
    async def main():
        # 创建调度器
        config = {
            "ai_gateway": {
                "model_endpoint": "http://localhost:8000",
                "api_key": "test-key"
            },
            "device_manager": {}
        }

        orchestrator = await create_orchestrator(config)

        # 注册节点
        orchestrator.register_node("node_1", {
            "type": "compute",
            "capabilities": ["fetch_data", "process_analysis"],
            "metadata": {"region": "us-east"}
        })

        # 注册设备
        orchestrator.device_manager.register_device("device_1", {
            "type": "sensor",
            "capabilities": ["fetch_data", "execute_control"]
        })

        # 处理请求
        result = await orchestrator.process_request("查询今天的天气")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # 获取系统状态
        status = orchestrator.get_system_status()
        print("\n系统状态:")
        print(json.dumps(status, indent=2, ensure_ascii=False))

        # 停止调度器
        await orchestrator.stop()

    asyncio.run(main())
