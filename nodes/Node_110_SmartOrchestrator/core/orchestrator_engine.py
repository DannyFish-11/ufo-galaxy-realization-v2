"""
Node_110_SmartOrchestrator - 智能任务编排引擎

功能：
1. 任务理解 - 调用 Node_01 理解自然语言任务
2. 能力匹配 - 查询 Node_103 匹配最适合的节点
3. 动态编排 - 根据 Node_67 的健康数据动态调整
4. 执行监控 - 通过 Node_02 执行并监控任务
"""

import asyncio
import json
import logging
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    OPTIMIZING = "optimizing"


class NodeCapability:
    """节点能力描述"""
    def __init__(self, node_id: str, capabilities: List[str], health_score: float):
        self.node_id = node_id
        self.capabilities = capabilities
        self.health_score = health_score
        self.load = 0.0


class ExecutionPlan:
    """执行计划"""
    def __init__(self, task_id: str, steps: List[Dict[str, Any]]):
        self.task_id = task_id
        self.steps = steps
        self.current_step = 0
        self.created_at = datetime.now()
        self.updated_at = datetime.now()


class SmartOrchestrator:
    """智能任务编排引擎"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.node_01_url = config.get("node_01_url", "http://localhost:8001")
        self.node_02_url = config.get("node_02_url", "http://localhost:8002")
        self.node_67_url = config.get("node_67_url", "http://localhost:8067")
        self.node_103_url = config.get("node_103_url", "http://localhost:8103")
        
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.execution_plans: Dict[str, ExecutionPlan] = {}
        self.node_capabilities: Dict[str, NodeCapability] = {}
        
        # 性能统计
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "avg_execution_time": 0.0,
            "optimization_count": 0
        }
        
        logger.info("SmartOrchestrator initialized")
    
    async def orchestrate_task(self, task_description: str, user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        编排任务的主入口
        
        Args:
            task_description: 任务描述（自然语言）
            user_context: 用户上下文（可选）
        
        Returns:
            任务信息和执行计划
        """
        task_id = f"task_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        try:
            # 创建任务记录
            self.tasks[task_id] = {
                "id": task_id,
                "description": task_description,
                "status": TaskStatus.ANALYZING.value,
                "created_at": datetime.now().isoformat(),
                "user_context": user_context or {}
            }
            
            self.stats["total_tasks"] += 1
            
            # 步骤 1: 任务理解（调用 Node_01）
            logger.info(f"[{task_id}] Step 1: Analyzing task with Node_01")
            task_analysis = await self._analyze_task(task_description, user_context)
            
            # 步骤 2: 能力匹配（查询 Node_67 和 Node_103）
            logger.info(f"[{task_id}] Step 2: Matching capabilities")
            self.tasks[task_id]["status"] = TaskStatus.PLANNING.value
            await self._update_node_capabilities()
            matched_nodes = await self._match_capabilities(task_analysis)
            
            # 步骤 3: 生成执行计划
            logger.info(f"[{task_id}] Step 3: Generating execution plan")
            execution_plan = await self._generate_execution_plan(
                task_id, task_analysis, matched_nodes
            )
            self.execution_plans[task_id] = execution_plan
            
            # 步骤 4: 执行任务（通过 Node_02）
            logger.info(f"[{task_id}] Step 4: Executing task via Node_02")
            self.tasks[task_id]["status"] = TaskStatus.EXECUTING.value
            execution_result = await self._execute_plan(execution_plan)
            
            # 步骤 5: 更新任务状态
            if execution_result["success"]:
                self.tasks[task_id]["status"] = TaskStatus.COMPLETED.value
                self.stats["completed_tasks"] += 1
            else:
                self.tasks[task_id]["status"] = TaskStatus.FAILED.value
                self.stats["failed_tasks"] += 1
            
            self.tasks[task_id]["result"] = execution_result
            self.tasks[task_id]["completed_at"] = datetime.now().isoformat()
            
            # 步骤 6: 存储编排知识（调用 Node_103）
            await self._store_orchestration_knowledge(task_id, task_analysis, execution_result)
            
            return {
                "task_id": task_id,
                "status": self.tasks[task_id]["status"],
                "execution_plan": {
                    "steps": execution_plan.steps,
                    "total_steps": len(execution_plan.steps)
                },
                "result": execution_result
            }
            
        except Exception as e:
            logger.error(f"[{task_id}] Orchestration failed: {e}", exc_info=True)
            self.tasks[task_id]["status"] = TaskStatus.FAILED.value
            self.tasks[task_id]["error"] = str(e)
            self.stats["failed_tasks"] += 1
            raise
    
    async def _analyze_task(self, task_description: str, user_context: Optional[Dict]) -> Dict[str, Any]:
        """
        调用 Node_01 (OneAPI) 分析任务
        
        Returns:
            任务分析结果，包括：
            - intent: 任务意图
            - entities: 实体识别
            - required_capabilities: 需要的能力
            - subtasks: 子任务列表
        """
        try:
            # 构造分析提示词
            analysis_prompt = f"""
分析以下任务，提取关键信息：

任务描述：{task_description}

请以 JSON 格式返回：
{{
    "intent": "任务意图",
    "entities": ["实体1", "实体2"],
    "required_capabilities": ["能力1", "能力2"],
    "subtasks": [
        {{"description": "子任务1", "priority": 1}},
        {{"description": "子任务2", "priority": 2}}
    ],
    "estimated_complexity": "low/medium/high"
}}
"""
            
            # 调用 Node_01
            response = requests.post(
                f"{self.node_01_url}/api/v1/chat",
                json={
                    "messages": [
                        {"role": "system", "content": "你是一个任务分析专家，擅长分解复杂任务。"},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    "model": "gpt-4",
                    "temperature": 0.3
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # 解析 JSON
                try:
                    analysis = json.loads(content)
                    logger.info(f"Task analysis completed: {analysis}")
                    return analysis
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON from Node_01, using fallback")
                    return self._fallback_task_analysis(task_description)
            else:
                logger.error(f"Node_01 returned error: {response.status_code}")
                return self._fallback_task_analysis(task_description)
                
        except Exception as e:
            logger.error(f"Failed to analyze task with Node_01: {e}")
            return self._fallback_task_analysis(task_description)
    
    def _fallback_task_analysis(self, task_description: str) -> Dict[str, Any]:
        """当 Node_01 不可用时的后备分析"""
        return {
            "intent": "general_task",
            "entities": [],
            "required_capabilities": ["general"],
            "subtasks": [{"description": task_description, "priority": 1}],
            "estimated_complexity": "medium"
        }
    
    async def _update_node_capabilities(self):
        """
        更新节点能力信息（调用 Node_67 获取健康状态）
        """
        try:
            response = requests.get(
                f"{self.node_67_url}/api/v1/health",
                timeout=10
            )
            
            if response.status_code == 200:
                health_data = response.json()
                
                # 更新节点能力
                for node_id, health_info in health_data.get("nodes", {}).items():
                    health_score = health_info.get("health_score", 0.5)
                    capabilities = health_info.get("capabilities", ["general"])
                    
                    self.node_capabilities[node_id] = NodeCapability(
                        node_id=node_id,
                        capabilities=capabilities,
                        health_score=health_score
                    )
                
                logger.info(f"Updated capabilities for {len(self.node_capabilities)} nodes")
            else:
                logger.warning(f"Node_67 returned error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to update node capabilities: {e}")
    
    async def _match_capabilities(self, task_analysis: Dict[str, Any]) -> List[str]:
        """
        匹配最适合的节点
        
        Returns:
            匹配的节点 ID 列表
        """
        required_capabilities = task_analysis.get("required_capabilities", [])
        matched_nodes = []
        
        for node_id, node_cap in self.node_capabilities.items():
            # 检查能力匹配
            match_score = 0
            for req_cap in required_capabilities:
                if req_cap in node_cap.capabilities:
                    match_score += 1
            
            # 考虑健康分数
            if match_score > 0 and node_cap.health_score > 0.5:
                matched_nodes.append({
                    "node_id": node_id,
                    "match_score": match_score,
                    "health_score": node_cap.health_score
                })
        
        # 按匹配分数和健康分数排序
        matched_nodes.sort(
            key=lambda x: (x["match_score"], x["health_score"]),
            reverse=True
        )
        
        logger.info(f"Matched {len(matched_nodes)} nodes for task")
        return [n["node_id"] for n in matched_nodes[:5]]  # 返回前5个最匹配的节点
    
    async def _generate_execution_plan(
        self,
        task_id: str,
        task_analysis: Dict[str, Any],
        matched_nodes: List[str]
    ) -> ExecutionPlan:
        """
        生成执行计划
        """
        steps = []
        
        for i, subtask in enumerate(task_analysis.get("subtasks", [])):
            # 为每个子任务分配节点
            assigned_node = matched_nodes[i % len(matched_nodes)] if matched_nodes else "Node_02_Tasker"
            
            steps.append({
                "step_id": i + 1,
                "description": subtask["description"],
                "assigned_node": assigned_node,
                "priority": subtask.get("priority", 1),
                "status": "pending"
            })
        
        return ExecutionPlan(task_id=task_id, steps=steps)
    
    async def _execute_plan(self, execution_plan: ExecutionPlan) -> Dict[str, Any]:
        """
        执行计划（通过 Node_02 Tasker）
        """
        try:
            # 调用 Node_02 执行任务
            response = requests.post(
                f"{self.node_02_url}/api/v1/tasks",
                json={
                    "task_id": execution_plan.task_id,
                    "steps": execution_plan.steps
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "task_id": execution_plan.task_id,
                    "steps_completed": len(execution_plan.steps),
                    "result": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Node_02 returned error: {response.status_code}"
                }
                
        except Exception as e:
            logger.error(f"Failed to execute plan: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _store_orchestration_knowledge(
        self,
        task_id: str,
        task_analysis: Dict[str, Any],
        execution_result: Dict[str, Any]
    ):
        """
        存储编排知识到 Node_103 (KnowledgeGraph)
        """
        try:
            knowledge_entry = {
                "task_id": task_id,
                "intent": task_analysis.get("intent"),
                "capabilities_used": task_analysis.get("required_capabilities"),
                "success": execution_result.get("success"),
                "timestamp": datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{self.node_103_url}/api/v1/knowledge/add",
                json=knowledge_entry,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Stored orchestration knowledge for task {task_id}")
            else:
                logger.warning(f"Failed to store knowledge: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to store orchestration knowledge: {e}")
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        return self.tasks.get(task_id)
    
    async def optimize_execution_plan(self, task_id: str) -> Dict[str, Any]:
        """
        优化执行计划（基于历史数据和当前节点状态）
        """
        if task_id not in self.execution_plans:
            raise ValueError(f"Task {task_id} not found")
        
        plan = self.execution_plans[task_id]
        
        # 更新节点能力
        await self._update_node_capabilities()
        
        # 重新分配节点
        optimized_steps = []
        for step in plan.steps:
            # 找到最健康的节点
            best_node = max(
                self.node_capabilities.values(),
                key=lambda x: x.health_score
            )
            
            optimized_step = step.copy()
            optimized_step["assigned_node"] = best_node.node_id
            optimized_steps.append(optimized_step)
        
        plan.steps = optimized_steps
        plan.updated_at = datetime.now()
        
        self.stats["optimization_count"] += 1
        
        return {
            "task_id": task_id,
            "optimized": True,
            "steps": optimized_steps
        }
    
    def get_system_capabilities(self) -> Dict[str, Any]:
        """获取系统能力概览"""
        return {
            "total_nodes": len(self.node_capabilities),
            "healthy_nodes": sum(
                1 for n in self.node_capabilities.values()
                if n.health_score > 0.7
            ),
            "capabilities": list(set(
                cap
                for node in self.node_capabilities.values()
                for cap in node.capabilities
            )),
            "stats": self.stats
        }
