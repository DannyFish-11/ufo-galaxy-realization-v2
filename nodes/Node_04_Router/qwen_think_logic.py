"""
Node 04: Qwen-Think-Max 驱动的智能路由引擎
利用 Qwen 的深度思考能力进行任务分解和最优路径规划。
"""
import os
import httpx
import json
from typing import List, Dict, Any

QWEN_API_KEY = os.getenv("QWEN_API_KEY", "YOUR_API_KEY")
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

class QwenThinkRouter:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=60.0)

    async def plan_route(self, task_description: str, available_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """利用 Qwen-Think-Max 进行深度思考并生成执行计划"""
        prompt = f"""你是一个 UFO Galaxy 系统的首席架构师。
        当前任务: {task_description}
        可用节点拓扑: {json.dumps(available_nodes, ensure_ascii=False)}

        请使用你的深度思考能力 (Think Max)，将任务分解为最有效的节点执行序列。
        要求返回 JSON 格式:
        {{
            "thought_process": "你的思考过程",
            "execution_plan": [
                {{"node_id": "Node_XX", "action": "具体动作", "params": {{}}}}
            ],
            "estimated_success_rate": 0.95
        }}
        """
        
        payload = {
            "model": "qwen-think-max",
            "messages": [
                {"role": "system", "content": "你是一个精通拓扑路由和多 Agent 协作的专家。"},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(QWEN_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return {"error": str(e), "status": "failed"}

# 导出路由逻辑
router_logic = QwenThinkRouter(QWEN_API_KEY)
