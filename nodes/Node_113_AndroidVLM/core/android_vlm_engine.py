"""
Node 113: AndroidVLM - Android GUI 理解引擎

功能：
1. 调用 Android 无障碍服务截图
2. 使用 VLM（Gemini/Qwen）分析截图
3. 智能查找元素
4. 生成操作建议

依赖节点：
- Node_90_MultimodalVision: VLM 分析
- Node_33 (Android): 截图和操作

版本：1.0.0
日期：2026-01-24
作者：Manus AI
"""

import os
import sys
import json
import asyncio
import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime

class AndroidVLMEngine:
    def __init__(self):
        # 节点地址
        self.node_90_url = os.getenv("NODE_90_MULTIMODAL_VISION_URL", "http://localhost:8090")
        self.android_agent_url = os.getenv("ANDROID_AGENT_URL", "http://192.168.1.100:8033")
        
        # VLM 提供商
        self.vlm_provider = os.getenv("VLM_PROVIDER", "auto")  # auto, gemini, qwen
        
        # 缓存
        self.last_screenshot = None
        self.last_screenshot_time = None
        self.screenshot_cache_ttl = 2  # 秒
        
    async def _call_node(self, url: str, endpoint: str, data: dict, timeout: float = 30.0) -> dict:
        """调用其他节点"""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{url}{endpoint}", json=data)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def capture_android_screen(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        截取 Android 屏幕
        
        Args:
            use_cache: 是否使用缓存（避免频繁截图）
        
        Returns:
            {
                "success": bool,
                "image": str (base64),
                "width": int,
                "height": int,
                "timestamp": int
            }
        """
        # 检查缓存
        if use_cache and self.last_screenshot:
            time_diff = datetime.now().timestamp() - self.last_screenshot_time
            if time_diff < self.screenshot_cache_ttl:
                return {
                    "success": True,
                    "cached": True,
                    **self.last_screenshot
                }
        
        # 调用 Android Agent 截图
        result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {"action": "screenshot"}
        )
        
        if result.get("success"):
            self.last_screenshot = result
            self.last_screenshot_time = datetime.now().timestamp()
        
        return result
    
    async def analyze_screen(
        self,
        query: str,
        image_base64: Optional[str] = None,
        provider: str = "auto"
    ) -> Dict[str, Any]:
        """
        使用 VLM 分析屏幕
        
        Args:
            query: 分析查询
            image_base64: 图片 Base64（如果为 None，自动截图）
            provider: VLM 提供商（auto, gemini, qwen）
        
        Returns:
            {
                "success": bool,
                "analysis": str,
                "provider": str,
                "model": str
            }
        """
        # 如果没有提供图片，自动截图
        if not image_base64:
            screenshot_result = await self.capture_android_screen()
            if not screenshot_result.get("success"):
                return screenshot_result
            image_base64 = screenshot_result["image"]
        
        # 调用 Node_90 分析
        result = await self._call_node(
            self.node_90_url,
            "/analyze_screen",
            {
                "query": query,
                "image_base64": image_base64,
                "provider": provider if provider != "auto" else self.vlm_provider
            }
        )
        
        return result
    
    async def find_element_with_vlm(
        self,
        description: str,
        image_base64: Optional[str] = None,
        confidence: float = 0.8
    ) -> Dict[str, Any]:
        """
        使用 VLM 查找元素
        
        Args:
            description: 元素描述
            image_base64: 图片 Base64（如果为 None，自动截图）
            confidence: 置信度阈值
        
        Returns:
            {
                "success": bool,
                "found": bool,
                "element": str,
                "position": {"x": int, "y": int, "width": int, "height": int},
                "confidence": float,
                "description": str
            }
        """
        # 如果没有提供图片，自动截图
        if not image_base64:
            screenshot_result = await self.capture_android_screen()
            if not screenshot_result.get("success"):
                return screenshot_result
            image_base64 = screenshot_result["image"]
        
        # 调用 Node_90 查找元素
        result = await self._call_node(
            self.node_90_url,
            "/find_element",
            {
                "description": description,
                "image_base64": image_base64,
                "method": "llm",
                "confidence": confidence
            }
        )
        
        return result
    
    async def smart_click(
        self,
        description: str,
        confidence: float = 0.8
    ) -> Dict[str, Any]:
        """
        智能点击（截图 -> VLM 查找 -> 点击）
        
        Args:
            description: 元素描述
            confidence: 置信度阈值
        
        Returns:
            {
                "success": bool,
                "clicked": bool,
                "element": str,
                "position": {"x": int, "y": int}
            }
        """
        # 1. 查找元素
        find_result = await self.find_element_with_vlm(description, confidence=confidence)
        
        if not find_result.get("success"):
            return find_result
        
        if not find_result.get("found"):
            return {
                "success": True,
                "clicked": False,
                "reason": "Element not found"
            }
        
        # 2. 点击元素
        position = find_result["position"]
        click_result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {
                "action": "click",
                "x": position["x"],
                "y": position["y"]
            }
        )
        
        if click_result.get("success"):
            return {
                "success": True,
                "clicked": True,
                "element": find_result["element"],
                "position": position,
                "confidence": find_result["confidence"]
            }
        else:
            return click_result
    
    async def generate_action_plan(
        self,
        task_description: str,
        max_steps: int = 10
    ) -> Dict[str, Any]:
        """
        生成操作计划（使用 VLM 分析当前界面并生成步骤）
        
        Args:
            task_description: 任务描述
            max_steps: 最大步骤数
        
        Returns:
            {
                "success": bool,
                "steps": [
                    {
                        "step": int,
                        "action": str,
                        "target": str,
                        "description": str
                    }
                ]
            }
        """
        # 1. 截图
        screenshot_result = await self.capture_android_screen()
        if not screenshot_result.get("success"):
            return screenshot_result
        
        # 2. 分析界面并生成计划
        query = f"""请分析这个 Android 界面，并为以下任务生成操作步骤：

任务：{task_description}

请以 JSON 格式返回（不要使用 markdown 代码块）：
{{
  "steps": [
    {{
      "step": 1,
      "action": "click" / "swipe" / "input" / "wait",
      "target": "目标元素描述",
      "description": "步骤描述"
    }}
  ]
}}

注意：
1. 最多 {max_steps} 步
2. 每一步都要基于当前界面的实际内容
3. 如果当前界面无法完成任务，请说明原因
"""
        
        analysis_result = await self.analyze_screen(
            query=query,
            image_base64=screenshot_result["image"]
        )
        
        if not analysis_result.get("success"):
            return analysis_result
        
        # 3. 解析 JSON
        try:
            analysis_text = analysis_result["analysis"]
            
            # 清理响应
            if analysis_text.startswith("```json"):
                analysis_text = analysis_text[7:]
            if analysis_text.startswith("```"):
                analysis_text = analysis_text[3:]
            if analysis_text.endswith("```"):
                analysis_text = analysis_text[:-3]
            analysis_text = analysis_text.strip()
            
            plan = json.loads(analysis_text)
            
            return {
                "success": True,
                "steps": plan.get("steps", []),
                "provider": analysis_result.get("provider"),
                "model": analysis_result.get("model")
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to parse action plan: {str(e)}",
                "raw_response": analysis_result.get("analysis")
            }
    
    async def execute_action_plan(
        self,
        steps: List[Dict[str, Any]],
        verify_each_step: bool = True
    ) -> Dict[str, Any]:
        """
        执行操作计划
        
        Args:
            steps: 步骤列表
            verify_each_step: 是否在每步后验证结果
        
        Returns:
            {
                "success": bool,
                "completed_steps": int,
                "failed_step": int,
                "results": [...]
            }
        """
        results = []
        
        for i, step in enumerate(steps):
            step_num = i + 1
            action = step.get("action")
            target = step.get("target")
            
            # 执行步骤
            if action == "click":
                result = await self.smart_click(target)
            elif action == "swipe":
                # TODO: 实现智能滑动
                result = {"success": False, "error": "Swipe not implemented yet"}
            elif action == "input":
                # TODO: 实现智能输入
                result = {"success": False, "error": "Input not implemented yet"}
            elif action == "wait":
                # 等待
                await asyncio.sleep(1)
                result = {"success": True, "action": "wait"}
            else:
                result = {"success": False, "error": f"Unknown action: {action}"}
            
            results.append({
                "step": step_num,
                "action": action,
                "target": target,
                "result": result
            })
            
            # 如果失败，停止执行
            if not result.get("success"):
                return {
                    "success": False,
                    "completed_steps": step_num - 1,
                    "failed_step": step_num,
                    "results": results
                }
            
            # 验证步骤（可选）
            if verify_each_step and action != "wait":
                await asyncio.sleep(0.5)  # 等待界面稳定
                # TODO: 使用 VLM 验证步骤是否成功
        
        return {
            "success": True,
            "completed_steps": len(steps),
            "results": results
        }
    
    async def smart_task_execution(
        self,
        task_description: str,
        max_steps: int = 10
    ) -> Dict[str, Any]:
        """
        智能任务执行（生成计划 -> 执行计划）
        
        Args:
            task_description: 任务描述
            max_steps: 最大步骤数
        
        Returns:
            {
                "success": bool,
                "plan": {...},
                "execution": {...}
            }
        """
        # 1. 生成计划
        plan_result = await self.generate_action_plan(task_description, max_steps)
        
        if not plan_result.get("success"):
            return plan_result
        
        # 2. 执行计划
        execution_result = await self.execute_action_plan(plan_result["steps"])
        
        return {
            "success": execution_result.get("success"),
            "plan": plan_result,
            "execution": execution_result
        }
