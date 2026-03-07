"""
Node 113: AndroidVLM - Android GUI 理解引擎

功能：
1. 调用 Android 无障碍服务截图
2. 使用 VLM（Gemini/Qwen/Claude/GPT-4V）分析截图
3. 智能查找元素
4. 生成操作建议
5. 长按 / 双击操作
6. 步骤验证机制
7. 错误恢复机制
8. 多 VLM 支持（Gemini、Qwen、Claude、GPT-4V）

依赖节点：
- Node_90_MultimodalVision: VLM 分析
- Node_33 (Android): 截图和操作

版本：1.1.0
日期：2026-03-07
"""

import os
import sys
import json
import asyncio
import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime

# 支持的 VLM 提供商列表
SUPPORTED_VLM_PROVIDERS = ["auto", "gemini", "qwen", "claude", "gpt4v"]


class AndroidVLMEngine:
    def __init__(self):
        # 节点地址
        self.node_90_url = os.getenv("NODE_90_MULTIMODAL_VISION_URL", "http://localhost:8090")
        self.android_agent_url = os.getenv("ANDROID_AGENT_URL", "http://192.168.1.100:8033")
        
        # VLM 提供商（支持 auto, gemini, qwen, claude, gpt4v）
        self.vlm_provider = os.getenv("VLM_PROVIDER", "auto")

        # Claude / GPT-4V 直连配置（当 Node_90 不可用时的后备）
        self.claude_api_key = os.getenv("CLAUDE_API_KEY", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        # 错误恢复：最大重试次数和重试间隔（秒）
        self.max_retries = int(os.getenv("VLM_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("VLM_RETRY_DELAY", "1.0"))

        # 缓存
        self.last_screenshot = None
        self.last_screenshot_time = None
        self.screenshot_cache_ttl = 2  # 秒
        
    async def _call_node(self, url: str, endpoint: str, data: dict, timeout: float = 30.0) -> dict:
        """调用其他节点（带重试 / 错误恢复）"""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{url}{endpoint}", json=data)
                    response.raise_for_status()
                    return response.json()
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)
        return {"success": False, "error": str(last_error), "retries": self.max_retries}
    
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
        使用 VLM 分析屏幕（支持 Gemini / Qwen / Claude / GPT-4V）
        
        Args:
            query: 分析查询
            image_base64: 图片 Base64（如果为 None，自动截图）
            provider: VLM 提供商（auto, gemini, qwen, claude, gpt4v）
        
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

        resolved_provider = provider if provider != "auto" else self.vlm_provider

        # Claude 直连（绕过 Node_90）
        if resolved_provider == "claude" and self.claude_api_key:
            return await self._analyze_with_claude(query, image_base64)

        # GPT-4V 直连（绕过 Node_90）
        if resolved_provider == "gpt4v" and self.openai_api_key:
            return await self._analyze_with_gpt4v(query, image_base64)

        # 默认：调用 Node_90 分析（支持 gemini / qwen）
        result = await self._call_node(
            self.node_90_url,
            "/analyze_screen",
            {
                "query": query,
                "image_base64": image_base64,
                "provider": resolved_provider
            }
        )
        
        return result

    async def _analyze_with_claude(self, query: str, image_base64: str) -> Dict[str, Any]:
        """使用 Claude (claude-3-5-sonnet) 直接分析截图"""
        try:
            headers = {
                "x-api-key": self.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64
                                }
                            },
                            {"type": "text", "text": query}
                        ]
                    }
                ]
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload
                )
                resp.raise_for_status()
            data = resp.json()
            analysis = data["content"][0]["text"]
            return {"success": True, "analysis": analysis, "provider": "claude", "model": data.get("model", "claude-3-5-sonnet")}
        except Exception as e:
            return {"success": False, "error": str(e), "provider": "claude"}

    async def _analyze_with_gpt4v(self, query: str, image_base64: str) -> Dict[str, Any]:
        """使用 GPT-4V (gpt-4o) 直接分析截图"""
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            },
                            {"type": "text", "text": query}
                        ]
                    }
                ],
                "max_tokens": 1024
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                resp.raise_for_status()
            data = resp.json()
            analysis = data["choices"][0]["message"]["content"]
            return {"success": True, "analysis": analysis, "provider": "gpt4v", "model": data.get("model", "gpt-4o")}
        except Exception as e:
            return {"success": False, "error": str(e), "provider": "gpt4v"}
    
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

    async def long_press(
        self,
        description: str,
        duration_ms: int = 1000,
        confidence: float = 0.8
    ) -> Dict[str, Any]:
        """
        长按操作（截图 -> VLM 查找 -> 长按）

        Args:
            description: 元素描述
            duration_ms: 长按持续时间（毫秒，默认 1000ms）
            confidence: 置信度阈值

        Returns:
            {"success": bool, "long_pressed": bool, "element": str, "position": {...}}
        """
        find_result = await self.find_element_with_vlm(description, confidence=confidence)

        if not find_result.get("success"):
            return find_result

        if not find_result.get("found"):
            return {"success": True, "long_pressed": False, "reason": "Element not found"}

        position = find_result["position"]
        result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {
                "action": "long_press",
                "x": position["x"],
                "y": position["y"],
                "duration": duration_ms
            }
        )

        if result.get("success"):
            return {
                "success": True,
                "long_pressed": True,
                "element": find_result["element"],
                "position": position,
                "duration_ms": duration_ms,
                "confidence": find_result["confidence"]
            }
        return result

    async def double_click(
        self,
        description: str,
        interval_ms: int = 100,
        confidence: float = 0.8
    ) -> Dict[str, Any]:
        """
        双击操作（截图 -> VLM 查找 -> 双击）

        Args:
            description: 元素描述
            interval_ms: 两次点击的间隔（毫秒，默认 100ms）
            confidence: 置信度阈值

        Returns:
            {"success": bool, "double_clicked": bool, "element": str, "position": {...}}
        """
        find_result = await self.find_element_with_vlm(description, confidence=confidence)

        if not find_result.get("success"):
            return find_result

        if not find_result.get("found"):
            return {"success": True, "double_clicked": False, "reason": "Element not found"}

        position = find_result["position"]
        result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {
                "action": "double_click",
                "x": position["x"],
                "y": position["y"],
                "interval": interval_ms
            }
        )

        if result.get("success"):
            return {
                "success": True,
                "double_clicked": True,
                "element": find_result["element"],
                "position": position,
                "confidence": find_result["confidence"]
            }
        return result

    async def execute_with_recovery(
        self,
        action_fn,
        *args,
        max_retries: int = 3,
        recovery_wait: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        带错误恢复的操作执行器

        Args:
            action_fn: 要执行的异步动作函数
            *args: 传递给 action_fn 的位置参数
            max_retries: 最大重试次数
            recovery_wait: 每次重试前等待时间（秒）
            **kwargs: 传递给 action_fn 的关键字参数

        Returns:
            action_fn 的返回值，或最后一次失败的错误信息
        """
        last_result = None
        for attempt in range(1, max_retries + 1):
            last_result = await action_fn(*args, **kwargs)
            if last_result.get("success"):
                return last_result
            if attempt < max_retries:
                await asyncio.sleep(recovery_wait)
                # 重新截图以刷新视图缓存
                self.last_screenshot = None
        last_result["recovery_attempts"] = max_retries
        return last_result
    
    async def smart_swipe(
        self,
        direction: str = "up",
        target: Optional[str] = None,
        distance: int = 500,
        duration_ms: int = 300
    ) -> Dict[str, Any]:
        """
        智能滑动

        Args:
            direction: 滑动方向 (up, down, left, right)
            target: 可选的元素描述，如果提供则从该元素位置开始滑动
            distance: 滑动距离（像素）
            duration_ms: 滑动持续时间（毫秒）

        Returns:
            {"success": bool, "action": "swipe", "direction": str}
        """
        # 确定起始坐标
        start_x, start_y = 540, 960  # 默认屏幕中心

        if target:
            find_result = await self.find_element_with_vlm(target)
            if find_result.get("found"):
                pos = find_result["position"]
                start_x = pos["x"]
                start_y = pos["y"]

        # 计算终点坐标
        direction_map = {
            "up":    (start_x, start_y, start_x, start_y - distance),
            "down":  (start_x, start_y, start_x, start_y + distance),
            "left":  (start_x, start_y, start_x - distance, start_y),
            "right": (start_x, start_y, start_x + distance, start_y),
        }
        sx, sy, ex, ey = direction_map.get(direction, (start_x, start_y, start_x, start_y - distance))

        result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {
                "action": "swipe",
                "start_x": sx, "start_y": sy,
                "end_x": ex, "end_y": ey,
                "duration": duration_ms
            }
        )

        if result.get("success"):
            return {"success": True, "action": "swipe", "direction": direction}
        return result

    async def smart_input(
        self,
        text: str,
        target: Optional[str] = None,
        clear_first: bool = True
    ) -> Dict[str, Any]:
        """
        智能输入文本

        Args:
            text: 要输入的文本
            target: 可选的输入框元素描述，如果提供则先点击该元素
            clear_first: 是否先清空输入框

        Returns:
            {"success": bool, "action": "input", "text": str}
        """
        # 如果指定了目标输入框，先点击它
        if target:
            click_result = await self.smart_click(target)
            if not click_result.get("clicked"):
                return {
                    "success": False,
                    "error": f"Could not click input target: {target}"
                }
            await asyncio.sleep(0.3)

        # 清空已有文本
        if clear_first:
            await self._call_node(
                self.android_agent_url,
                "/node/33",
                {"action": "clear_text"}
            )

        # 输入文本
        result = await self._call_node(
            self.android_agent_url,
            "/node/33",
            {"action": "input_text", "text": text}
        )

        if result.get("success"):
            return {"success": True, "action": "input", "text": text}
        return result

    async def verify_step_success(
        self,
        action: str,
        target: Optional[str] = None,
        expected_outcome: str = ""
    ) -> Dict[str, Any]:
        """
        使用 VLM 验证操作步骤是否成功执行

        Args:
            action: 执行的操作类型
            target: 操作目标
            expected_outcome: 预期的结果描述

        Returns:
            {"verified": bool, "confidence": float, "observation": str}
        """
        query = f"刚才执行了 '{action}' 操作"
        if target:
            query += f"，目标是 '{target}'"
        if expected_outcome:
            query += f"。预期结果：{expected_outcome}"
        query += "。请判断操作是否成功执行，当前界面是否符合预期？回答 JSON: {\"success\": true/false, \"observation\": \"观察描述\"}"

        analysis_result = await self.analyze_screen(query)
        if not analysis_result.get("success"):
            return {"verified": True, "confidence": 0.5, "observation": "无法验证"}

        analysis_text = analysis_result.get("analysis", "")

        # 解析 VLM 的回答
        verified = True
        confidence = 0.7
        observation = analysis_text

        try:
            parsed = json.loads(analysis_text)
            verified = parsed.get("success", True)
            observation = parsed.get("observation", analysis_text)
            confidence = 0.9 if verified else 0.8
        except (json.JSONDecodeError, TypeError):
            # VLM 返回非 JSON，用关键词判断
            negative_keywords = ["失败", "错误", "没有", "未能", "fail", "error", "not"]
            if any(kw in analysis_text.lower() for kw in negative_keywords):
                verified = False
                confidence = 0.6

        return {
            "verified": verified,
            "confidence": confidence,
            "observation": observation
        }

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
      "action": "click" / "long_press" / "double_click" / "swipe" / "input" / "wait",
      "target": "目标元素描述",
      "description": "步骤描述",
      "duration_ms": 1000,
      "interval_ms": 100,
      "text": "（input 时填写）",
      "direction": "up/down/left/right（swipe 时填写）"
    }}
  ]
}}

注意：
1. 最多 {max_steps} 步
2. 每一步都要基于当前界面的实际内容
3. 如果当前界面无法完成任务，请说明原因
4. 支持 long_press（长按）和 double_click（双击）操作
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
        verify_each_step: bool = True,
        use_recovery: bool = True
    ) -> Dict[str, Any]:
        """
        执行操作计划（支持长按、双击、错误恢复）
        
        Args:
            steps: 步骤列表
            verify_each_step: 是否在每步后验证结果
            use_recovery: 是否启用错误恢复（自动重试失败步骤）
        
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
            
            # 执行步骤（支持 long_press / double_click）
            async def _execute_step():
                if action == "click":
                    return await self.smart_click(target)
                elif action == "long_press":
                    return await self.long_press(
                        target,
                        duration_ms=step.get("duration_ms", 1000)
                    )
                elif action == "double_click":
                    return await self.double_click(
                        target,
                        interval_ms=step.get("interval_ms", 100)
                    )
                elif action == "swipe":
                    return await self.smart_swipe(
                        direction=step.get("direction", "up"),
                        target=target
                    )
                elif action == "input":
                    return await self.smart_input(
                        text=step.get("text", ""),
                        target=target
                    )
                elif action == "wait":
                    await asyncio.sleep(step.get("seconds", 1))
                    return {"success": True, "action": "wait"}
                else:
                    return {"success": False, "error": f"Unknown action: {action}"}

            if use_recovery:
                result = await self.execute_with_recovery(_execute_step)
            else:
                result = await _execute_step()
            
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
                verification = await self.verify_step_success(
                    action=action,
                    target=target,
                    expected_outcome=step.get("expected_outcome", "")
                )
                results[-1]["verification"] = verification
        
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
