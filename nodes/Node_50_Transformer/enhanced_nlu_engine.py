"""
增强版 NLU 引擎

功能：
1. 意图识别 - 理解用户的真实意图
2. 实体提取 - 提取关键信息（软件名、文件名、参数等）
3. 任务规划 - 将复杂任务分解为多个步骤
4. 设备路由 - 智能选择执行设备
5. 软件操作 - 生成软件操作指令

作者：Manus AI
日期：2025-01-20
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

class IntentType(Enum):
    """意图类型"""
    SOFTWARE_OPERATION = "software_operation"  # 操作软件
    FILE_OPERATION = "file_operation"          # 文件操作
    DEVICE_CONTROL = "device_control"          # 设备控制
    INFORMATION_QUERY = "information_query"    # 信息查询
    MEDIA_GENERATION = "media_generation"      # 媒体生成
    CROSS_DEVICE_TASK = "cross_device_task"    # 跨设备任务
    UNKNOWN = "unknown"

class TargetDevice(Enum):
    """目标设备"""
    WINDOWS = "windows"
    ANDROID = "android"
    CLOUD = "cloud"
    PRINTER_3D = "3d_printer"
    AUTO = "auto"  # 自动选择

@dataclass
class Intent:
    """意图对象"""
    type: IntentType
    action: str  # 具体动作，如 "open", "close", "send"
    target: Optional[str]  # 目标对象，如软件名、文件名
    parameters: Dict[str, Any]  # 参数
    device: TargetDevice  # 目标设备
    confidence: float  # 置信度

@dataclass
class TaskStep:
    """任务步骤"""
    step_id: int
    device: TargetDevice
    action: str
    parameters: Dict[str, Any]
    depends_on: List[int]  # 依赖的步骤 ID

class EnhancedNLUEngine:
    """增强版 NLU 引擎"""
    
    def __init__(self, use_ai_model: bool = True, oneapi_url: str = None):
        """
        初始化 NLU 引擎
        
        Args:
            use_ai_model: 是否使用 AI 模型（通过 OneAPI）
            oneapi_url: OneAPI 的 URL
        """
        self.use_ai_model = use_ai_model
        self.oneapi_url = oneapi_url
        
        # 软件名称映射（支持中英文）
        self.software_map = {
            "微信": "wechat",
            "wechat": "wechat",
            "qq": "qq",
            "浏览器": "browser",
            "browser": "browser",
            "chrome": "chrome",
            "edge": "edge",
            "记事本": "notepad",
            "notepad": "notepad",
            "word": "word",
            "excel": "excel",
            "ppt": "powerpoint",
            "powerpoint": "powerpoint",
            "vscode": "vscode",
            "代码编辑器": "vscode"
        }
        
        # 动作映射
        self.action_map = {
            "打开": "open",
            "open": "open",
            "启动": "open",
            "关闭": "close",
            "close": "close",
            "发送": "send",
            "send": "send",
            "查询": "query",
            "query": "query",
            "搜索": "search",
            "search": "search",
            "生成": "generate",
            "generate": "generate",
            "创建": "create",
            "create": "create"
        }
    
    def understand(self, user_input: str) -> Intent:
        """
        理解用户输入
        
        Args:
            user_input: 用户的自然语言输入
        
        Returns:
            Intent 对象
        """
        # 如果启用 AI 模型，使用 AI 进行理解
        if self.use_ai_model and self.oneapi_url:
            return self._understand_with_ai(user_input)
        else:
            return self._understand_with_rules(user_input)
    
    def _understand_with_rules(self, user_input: str) -> Intent:
        """使用规则进行意图识别"""
        user_input_lower = user_input.lower()
        
        # 1. 识别软件操作
        for software_name, software_id in self.software_map.items():
            if software_name in user_input_lower:
                # 识别动作
                action = "open"  # 默认动作
                for action_name, action_id in self.action_map.items():
                    if action_name in user_input_lower:
                        action = action_id
                        break
                
                # 提取参数
                parameters = {}
                
                # 如果是发送消息
                if action == "send":
                    # 提取消息内容
                    match = re.search(r'[说发送]"([^"]+)"', user_input)
                    if match:
                        parameters["message"] = match.group(1)
                
                # 如果是搜索
                if action == "search":
                    # 提取搜索关键词
                    match = re.search(r'搜索"([^"]+)"', user_input)
                    if match:
                        parameters["keyword"] = match.group(1)
                
                # 判断设备
                device = TargetDevice.AUTO
                if "手机" in user_input or "android" in user_input_lower:
                    device = TargetDevice.ANDROID
                elif "电脑" in user_input or "windows" in user_input_lower or "pc" in user_input_lower:
                    device = TargetDevice.WINDOWS
                
                return Intent(
                    type=IntentType.SOFTWARE_OPERATION,
                    action=action,
                    target=software_id,
                    parameters=parameters,
                    device=device,
                    confidence=0.8
                )
        
        # 2. 识别媒体生成
        if "生成" in user_input or "generate" in user_input_lower:
            if "视频" in user_input or "video" in user_input_lower:
                # 提取提示词
                prompt = user_input
                # 尝试提取引号内的内容
                match = re.search(r'"([^"]+)"', user_input)
                if match:
                    prompt = match.group(1)
                
                return Intent(
                    type=IntentType.MEDIA_GENERATION,
                    action="generate_video",
                    target="pixverse",
                    parameters={"prompt": prompt},
                    device=TargetDevice.WINDOWS,  # PixVerse 在 Windows 上
                    confidence=0.9
                )
        
        # 3. 识别设备控制
        if "3d" in user_input_lower or "打印" in user_input:
            return Intent(
                type=IntentType.DEVICE_CONTROL,
                action="print_3d",
                target="bambulab",
                parameters={"file": user_input},
                device=TargetDevice.PRINTER_3D,
                confidence=0.85
            )
        
        # 4. 识别信息查询
        if "查询" in user_input or "query" in user_input_lower or "获取" in user_input:
            if "位置" in user_input or "location" in user_input_lower:
                return Intent(
                    type=IntentType.INFORMATION_QUERY,
                    action="get_location",
                    target="gps",
                    parameters={},
                    device=TargetDevice.ANDROID,
                    confidence=0.9
                )
            elif "状态" in user_input or "status" in user_input_lower:
                return Intent(
                    type=IntentType.INFORMATION_QUERY,
                    action="get_status",
                    target="device",
                    parameters={},
                    device=TargetDevice.AUTO,
                    confidence=0.85
                )
        
        # 5. 识别跨设备任务
        if ("发送" in user_input or "send" in user_input_lower) and ("到" in user_input or "to" in user_input_lower):
            return Intent(
                type=IntentType.CROSS_DEVICE_TASK,
                action="transfer",
                target="file",
                parameters={"content": user_input},
                device=TargetDevice.AUTO,
                confidence=0.75
            )
        
        # 默认：未知意图
        return Intent(
            type=IntentType.UNKNOWN,
            action="unknown",
            target=None,
            parameters={"raw_input": user_input},
            device=TargetDevice.AUTO,
            confidence=0.3
        )
    
    def _understand_with_ai(self, user_input: str) -> Intent:
        """使用 AI 模型进行意图识别（通过 OneAPI）"""
        # TODO: 实现 AI 模型调用
        # 这里可以调用 OneAPI 来使用更强大的 LLM 进行意图识别
        return self._understand_with_rules(user_input)
    
    def plan_task(self, intent: Intent) -> List[TaskStep]:
        """
        任务规划 - 将意图分解为多个可执行的步骤
        
        Args:
            intent: 意图对象
        
        Returns:
            任务步骤列表
        """
        steps = []
        
        if intent.type == IntentType.SOFTWARE_OPERATION:
            # 简单任务，只需一步
            steps.append(TaskStep(
                step_id=1,
                device=intent.device,
                action=f"{intent.action}_{intent.target}",
                parameters=intent.parameters,
                depends_on=[]
            ))
        
        elif intent.type == IntentType.MEDIA_GENERATION:
            # 视频生成任务
            steps.append(TaskStep(
                step_id=1,
                device=TargetDevice.WINDOWS,
                action="generate_video",
                parameters={"prompt": intent.parameters.get("prompt")},
                depends_on=[]
            ))
        
        elif intent.type == IntentType.CROSS_DEVICE_TASK:
            # 跨设备任务，需要多步
            # 步骤 1：在源设备获取内容
            steps.append(TaskStep(
                step_id=1,
                device=TargetDevice.ANDROID,  # 假设从手机获取
                action="get_content",
                parameters={},
                depends_on=[]
            ))
            
            # 步骤 2：传输到目标设备
            steps.append(TaskStep(
                step_id=2,
                device=TargetDevice.WINDOWS,  # 假设传输到电脑
                action="receive_content",
                parameters={},
                depends_on=[1]
            ))
        
        elif intent.type == IntentType.INFORMATION_QUERY:
            # 信息查询任务
            steps.append(TaskStep(
                step_id=1,
                device=intent.device,
                action=intent.action,
                parameters=intent.parameters,
                depends_on=[]
            ))
        
        return steps
    
    def generate_software_command(self, software_id: str, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成软件操作命令
        
        Args:
            software_id: 软件 ID
            action: 动作
            parameters: 参数
        
        Returns:
            软件操作命令（符合微软 UFO 的格式）
        """
        command = {
            "type": "ui_automation",
            "software": software_id,
            "action": action,
            "parameters": parameters
        }
        
        # 根据不同软件生成具体的操作步骤
        if software_id == "wechat":
            if action == "open":
                command["steps"] = [
                    {"type": "click", "target": "wechat_icon"},
                    {"type": "wait", "duration": 2}
                ]
            elif action == "send":
                command["steps"] = [
                    {"type": "click", "target": "search_box"},
                    {"type": "input", "text": parameters.get("contact", "")},
                    {"type": "click", "target": "first_result"},
                    {"type": "input", "text": parameters.get("message", "")},
                    {"type": "press_key", "key": "Enter"}
                ]
        
        elif software_id == "browser":
            if action == "open":
                command["steps"] = [
                    {"type": "click", "target": "browser_icon"}
                ]
            elif action == "search":
                command["steps"] = [
                    {"type": "click", "target": "address_bar"},
                    {"type": "input", "text": parameters.get("keyword", "")},
                    {"type": "press_key", "key": "Enter"}
                ]
        
        return command

# 使用示例
if __name__ == "__main__":
    engine = EnhancedNLUEngine(use_ai_model=False)
    
    # 测试各种输入
    test_inputs = [
        "打开微信",
        "在电脑上打开浏览器",
        "用手机获取当前位置",
        "生成一个关于猫弹钢琴的视频",
        "在浏览器中搜索Python教程",
        "打开 VSCode",
        "把手机上的照片发送到电脑"
    ]
    
    print("="*60)
    print("增强版 NLU 引擎测试")
    print("="*60)
    
    for user_input in test_inputs:
        print(f"\n用户输入: {user_input}")
        
        # 意图识别
        intent = engine.understand(user_input)
        print(f"意图类型: {intent.type.value}")
        print(f"动作: {intent.action}")
        print(f"目标: {intent.target}")
        print(f"参数: {intent.parameters}")
        print(f"设备: {intent.device.value}")
        print(f"置信度: {intent.confidence}")
        
        # 任务规划
        steps = engine.plan_task(intent)
        if steps:
            print(f"\n任务步骤 ({len(steps)} 步):")
            for step in steps:
                print(f"  步骤 {step.step_id}: {step.action} on {step.device.value}")
                if step.depends_on:
                    print(f"    依赖: {step.depends_on}")
