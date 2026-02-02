"""
UFO³ Galaxy - 增强版 NLU 引擎 v2.0

功能：
1. 多设备精确识别（手机 A、手机 B、平板、电脑）
2. LLM 驱动的意图识别（支持复杂场景）
3. 复杂任务分解和依赖管理
4. 上下文管理和多轮对话
5. 主动澄清机制
6. 混合策略（规则 + LLM）

作者：Manus AI
日期：2026-01-22
版本：2.0
"""

import json
import re
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
import aiohttp
from datetime import datetime

# ============================================================================
# 数据结构定义
# ============================================================================

class DeviceType(Enum):
    """设备类型"""
    ANDROID = "android"
    WINDOWS = "windows"
    IOS = "ios"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"

class DeviceStatus(Enum):
    """设备状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    UNKNOWN = "unknown"

@dataclass
class Device:
    """设备信息"""
    device_id: str          # 设备唯一 ID
    device_name: str        # 设备名称（如"手机A"、"平板"）
    device_type: DeviceType # 设备类型
    status: DeviceStatus    # 设备状态
    aliases: List[str]      # 设备别名
    capabilities: List[str] # 设备能力（如"wechat", "browser"）
    ip_address: str         # IP 地址
    last_seen: datetime     # 最后在线时间

class IntentType(Enum):
    """意图类型"""
    APP_CONTROL = "app_control"              # 应用控制（打开、关闭）
    APP_OPERATION = "app_operation"          # 应用操作（发消息、搜索）
    FILE_OPERATION = "file_operation"        # 文件操作
    DEVICE_CONTROL = "device_control"        # 设备控制
    INFORMATION_QUERY = "information_query"  # 信息查询
    CROSS_DEVICE_TASK = "cross_device_task"  # 跨设备任务
    MEDIA_GENERATION = "media_generation"    # 媒体生成
    VISUAL_ANALYSIS = "visual_analysis"      # 视觉分析（新增）
    SYSTEM_COMMAND = "system_command"        # 系统命令
    UNKNOWN = "unknown"

@dataclass
class Task:
    """单个任务"""
    task_id: str                    # 任务 ID
    device_id: str                  # 目标设备 ID
    intent_type: IntentType         # 意图类型
    action: str                     # 动作（如"open_app"）
    target: Optional[str]           # 目标对象（如"wechat"）
    parameters: Dict[str, Any]      # 参数
    depends_on: List[str]           # 依赖的任务 ID
    confidence: float               # 置信度
    estimated_duration: float       # 预计执行时间（秒）

@dataclass
class NLUResult:
    """NLU 解析结果"""
    success: bool                   # 是否成功解析
    tasks: List[Task]               # 任务列表
    confidence: float               # 总体置信度
    clarifications: List[str]       # 需要澄清的问题
    context_used: bool              # 是否使用了上下文
    processing_time: float          # 处理时间（秒）
    method: str                     # 使用的方法（"rule" 或 "llm"）

# ============================================================================
# 设备注册表
# ============================================================================

class DeviceRegistry:
    """设备注册表 - 管理所有设备信息"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self._load_default_devices()
    
    def _load_default_devices(self):
        """加载默认设备（示例）"""
        # 这些设备会在实际运行时从 Galaxy Gateway 动态加载
        default_devices = [
            Device(
                device_id="phone_a",
                device_name="手机A",
                device_type=DeviceType.ANDROID,
                status=DeviceStatus.ONLINE,
                aliases=["手机A", "我的手机", "主手机", "phone a"],
                capabilities=["wechat", "qq", "browser", "camera"],
                ip_address="192.168.1.100",
                last_seen=datetime.now()
            ),
            Device(
                device_id="phone_b",
                device_name="手机B",
                device_type=DeviceType.ANDROID,
                status=DeviceStatus.ONLINE,
                aliases=["手机B", "工作手机", "备用手机", "phone b"],
                capabilities=["wechat", "qq", "browser", "camera"],
                ip_address="192.168.1.101",
                last_seen=datetime.now()
            ),
            Device(
                device_id="tablet",
                device_name="平板",
                device_type=DeviceType.ANDROID,
                status=DeviceStatus.ONLINE,
                aliases=["平板", "iPad", "平板电脑", "tablet"],
                capabilities=["wechat", "qq", "browser", "youtube"],
                ip_address="192.168.1.102",
                last_seen=datetime.now()
            ),
            Device(
                device_id="pc",
                device_name="电脑",
                device_type=DeviceType.WINDOWS,
                status=DeviceStatus.ONLINE,
                aliases=["电脑", "PC", "台式机", "主机", "computer"],
                capabilities=["chrome", "edge", "notepad", "vscode", "photoshop"],
                ip_address="192.168.1.10",
                last_seen=datetime.now()
            )
        ]
        
        for device in default_devices:
            self.devices[device.device_id] = device
    
    def register_device(self, device: Device):
        """注册设备"""
        self.devices[device.device_id] = device
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def find_device_by_name(self, name: str) -> Optional[Device]:
        """通过名称或别名查找设备"""
        name_lower = name.lower().strip()
        
        for device in self.devices.values():
            # 检查设备名称
            if device.device_name.lower() == name_lower:
                return device
            
            # 检查别名
            for alias in device.aliases:
                if alias.lower() == name_lower:
                    return device
        
        return None
    
    def get_online_devices(self) -> List[Device]:
        """获取所有在线设备"""
        return [d for d in self.devices.values() if d.status == DeviceStatus.ONLINE]
    
    def update_device_status(self, device_id: str, status: DeviceStatus):
        """更新设备状态"""
        if device_id in self.devices:
            self.devices[device_id].status = status
            self.devices[device_id].last_seen = datetime.now()

# ============================================================================
# 上下文管理器
# ============================================================================

@dataclass
class ConversationContext:
    """会话上下文"""
    session_id: str
    user_id: str
    history: List[Dict[str, Any]]  # 历史对话
    last_devices: List[str]        # 最近提到的设备
    last_apps: List[str]           # 最近提到的应用
    last_action: Optional[str]     # 最近的动作
    created_at: datetime
    updated_at: datetime

class ContextManager:
    """上下文管理器"""
    
    def __init__(self):
        self.contexts: Dict[str, ConversationContext] = {}
    
    def get_or_create_context(self, session_id: str, user_id: str) -> ConversationContext:
        """获取或创建上下文"""
        if session_id not in self.contexts:
            self.contexts[session_id] = ConversationContext(
                session_id=session_id,
                user_id=user_id,
                history=[],
                last_devices=[],
                last_apps=[],
                last_action=None,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
        return self.contexts[session_id]
    
    def update_context(self, session_id: str, user_input: str, nlu_result: NLUResult):
        """更新上下文"""
        if session_id in self.contexts:
            context = self.contexts[session_id]
            
            # 添加到历史
            context.history.append({
                "timestamp": datetime.now().isoformat(),
                "user_input": user_input,
                "tasks": [asdict(task) for task in nlu_result.tasks]
            })
            
            # 更新最近的设备和应用
            for task in nlu_result.tasks:
                if task.device_id not in context.last_devices:
                    context.last_devices.append(task.device_id)
                if task.target and task.target not in context.last_apps:
                    context.last_apps.append(task.target)
                context.last_action = task.action
            
            # 只保留最近 10 条历史
            if len(context.history) > 10:
                context.history = context.history[-10:]
            
            # 只保留最近 5 个设备和应用
            context.last_devices = context.last_devices[-5:]
            context.last_apps = context.last_apps[-5:]
            
            context.updated_at = datetime.now()

# ============================================================================
# LLM 客户端
# ============================================================================

class LLMClient:
    """LLM 客户端 - 支持多个 LLM 提供商"""
    
    def __init__(self, provider: str = "ollama", api_base: str = None, api_key: str = None):
        """
        初始化 LLM 客户端
        
        Args:
            provider: LLM 提供商（"ollama", "groq", "deepseek", "openrouter"）
            api_base: API 基础 URL
            api_key: API 密钥
        """
        self.provider = provider
        self.api_base = api_base or self._get_default_api_base(provider)
        self.api_key = api_key or os.getenv(self._get_api_key_env(provider))
        self.model = self._get_default_model(provider)
    
    def _get_default_api_base(self, provider: str) -> str:
        """获取默认 API 基础 URL"""
        defaults = {
            "ollama": "http://localhost:11434",
            "groq": "https://api.groq.com/openai/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "openrouter": "https://openrouter.ai/api/v1"
        }
        return defaults.get(provider, "http://localhost:11434")
    
    def _get_api_key_env(self, provider: str) -> str:
        """获取 API 密钥环境变量名"""
        env_names = {
            "groq": "GROQ_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY"
        }
        return env_names.get(provider, "")
    
    def _get_default_model(self, provider: str) -> str:
        """获取默认模型"""
        models = {
            "ollama": "qwen2.5:7b",
            "groq": "llama-3.3-70b-versatile",
            "deepseek": "deepseek-coder", # 文本/代码生成模型
            "openrouter": "deepseek/deepseek-chat"
        }
        return models.get(provider, "qwen2.5:7b")

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """
        生成文本
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
        
        Returns:
            生成的文本
        """
        if self.provider == "ollama":
            return await self._generate_ollama(prompt, system_prompt)
        else:
            return await self._generate_openai_compatible(prompt, system_prompt)
    
    async def _generate_ollama(self, prompt: str, system_prompt: str = None) -> str:
        """使用 Ollama 生成"""
        url = f"{self.api_base}/api/generate"
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json"  # 要求 JSON 输出
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("response", "")
                    else:
                        print(f"Ollama API error: {response.status}")
                        return ""
            except Exception as e:
                print(f"Ollama API exception: {e}")
                return ""
    
    async def _generate_openai_compatible(self, prompt: str, system_prompt: str = None) -> str:
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"}  # 要求 JSON 输出
        }
        
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        async with aiohttp.ClientSession() as session:
            try:
                # 修复：url 变量未定义，需要从 self.api_base 构建
                url = f"{self.api_base}/chat/completions"
                
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    else:
                        print(f"LLM API error: {response.status}")
                        print(f"Error details: {await response.text()}")
                        return ""
            except Exception as e:
                print(f"LLM API exception: {e}")
                return ""

class VLMClient(LLMClient):
    """VLM 客户端 - 专用于多模态任务"""
    
    def __init__(self, provider: str = "openrouter", api_base: str = None, api_key: str = None):
        super().__init__(provider, api_base, api_key)
        self.model = self._get_default_vlm_model(provider)
        
    def _get_default_vlm_model(self, provider: str) -> str:
        """获取默认 VLM 模型"""
        vlm_models = {
            "openrouter": "qwen/qwen3-vl-32b-instruct" # 使用 Qwen3-VL
        }
        return vlm_models.get(provider, "qwen/qwen3-vl-32b-instruct")
        
    # VLMClient 不再需要 generate 方法，因为 VLM 逻辑已封装在 qwen_vl_api.py 中
    # 这里的 VLMClient 仅用于 NLU 引擎的初始化和模型名称的定义
    pass

# ============================================================================
# 增强版 NLU 引擎
# ============================================================================

class EnhancedNLUEngineV2:
    """增强版 NLU 引擎 v2.0"""
    
    def __init__(
        self,
        device_registry: DeviceRegistry,
        llm_client: LLMClient,
        vlm_client: Optional[VLMClient] = None, # 新增 VLM 客户端
        use_llm: bool = True,
        confidence_threshold: float = 0.7
    ):
        """
        初始化 NLU 引擎
        
        Args:
            device_registry: 设备注册表
            llm_client: LLM 客户端
            use_llm: 是否使用 LLM（False 则只用规则）
            confidence_threshold: 置信度阈值（低于此值会要求澄清）
        """
        self.device_registry = device_registry
        self.llm_client = llm_client
        self.vlm_client = vlm_client # 保存 VLM 客户端
        self.use_llm = use_llm
        self.confidence_threshold = confidence_threshold
        self.context_manager = ContextManager()
        
        # 应用名称映射
        self.app_map = {
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
            "代码编辑器": "vscode",
            "ps": "photoshop",
            "photoshop": "photoshop",
            "youtube": "youtube",
            "音乐": "music",
            "music": "music"
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
            "播放": "play",
            "play": "play",
            "搜索": "search",
            "search": "search"
        }
    
    async def understand(self, user_input: str) -> NLUResult:
        """
        理解用户输入并转换为结构化任务列表
        """
        start_time = datetime.now()
        session_id = "default_session" # 默认会话 ID
        
        # 获取当前上下文
        context = self.context_manager.get_or_create_context(session_id, "default_user")
        
        # 1. VLM 意图规则匹配 (VLM Intent Rule Matching)
        # 检查是否为 VLM 任务，如果是，则直接生成 VLM 任务结构
        vlm_keywords = ["分析屏幕", "看一眼", "这个图表", "这张图片", "总结一下"]
        is_vlm_intent = any(keyword in user_input for keyword in vlm_keywords)
        
        if is_vlm_intent:
            # 尝试提取设备
            devices = self._extract_devices(user_input)
            target_device = devices[0] if devices else self.device_registry.get_device("pc") # 默认电脑
            
            if target_device and target_device.device_type in [DeviceType.WINDOWS, DeviceType.ANDROID, DeviceType.IOS]:
                task = Task(
                    task_id="task_1",
                    device_id=target_device.device_id,
                    intent_type=IntentType.VISUAL_ANALYSIS,
                    action="vlm_analyze",
                    target="screenshot",
                    parameters={"image_path": "/home/ubuntu/Downloads/temp_screenshot.png", "prompt": user_input},
                    depends_on=[], # 修复：添加缺失的 depends_on 参数
                    confidence=0.95,
                    estimated_duration=5.0
                )
                result = NLUResult(
                    success=True,
                    tasks=[task],
                    confidence=0.95,
                    clarifications=[], # 修复：添加缺失的 clarifications 参数
                    context_used=False, # 修复：添加缺失的 context_used 参数
                    processing_time=(datetime.now() - start_time).total_seconds(),
                    method="vlm_rule"
                )
                self.context_manager.update_context(session_id, user_input, result)
                return result
        
        # 2. 规则匹配 (Rule-based Matching)
        # 优先使用规则匹配，速度快，准确率高
        rule_result = self._understand_with_rules(user_input, context)
        
        if rule_result.success and rule_result.confidence >= self.confidence_threshold:
            processing_time = (datetime.now() - start_time).total_seconds()
            rule_result.processing_time = processing_time
            rule_result.method = "rule"
            
            # 更新上下文
            self.context_manager.update_context(session_id, user_input, rule_result)
            
            return rule_result
        
        # 3. LLM 理解 (LLM-based Understanding)
        if self.use_llm:
            llm_result = await self._understand_with_llm(user_input, context)
            processing_time = (datetime.now() - start_time).total_seconds()
            llm_result.processing_time = processing_time
            llm_result.method = "llm"
            
            # 更新上下文
            self.context_manager.update_context(session_id, user_input, llm_result)
            
            return llm_result
        else:
            # 不使用 LLM，返回规则结果
            processing_time = (datetime.now() - start_time).total_seconds()
            rule_result.processing_time = processing_time
            rule_result.method = "rule"
            
            # 更新上下文
            self.context_manager.update_context(session_id, user_input, rule_result)
            
            return rule_result
    
    def _understand_with_rules(
        self,
        user_input: str,
        context: ConversationContext
    ) -> NLUResult:
        """使用规则进行意图识别"""
        user_input_lower = user_input.lower()
        tasks = []
        clarifications = []
        
        # 提取设备名称
        devices = self._extract_devices(user_input)
        
        # 如果没有明确指定设备，尝试从上下文推断
        if not devices and context.last_devices:
            devices = [self.device_registry.get_device(context.last_devices[-1])]
        
        # 如果还是没有设备，要求澄清
        if not devices:
            clarifications.append("请指定要操作的设备（手机A、手机B、平板、电脑）")
            return NLUResult(
                success=False,
                tasks=[],
                confidence=0.3,
                clarifications=clarifications,
                context_used=False,
                processing_time=0.0,
                method="rule"
            )
        
        # 提取应用和动作
        app = self._extract_app(user_input)
        action = self._extract_action(user_input)
        
        # 如果没有明确的应用，尝试从上下文推断
        if not app and context.last_apps:
            app = context.last_apps[-1]
        
        # 为每个设备创建任务
        for device in devices:
            if app:
                task = Task(
                    task_id=f"task_{len(tasks)+1}",
                    device_id=device.device_id,
                    intent_type=IntentType.APP_CONTROL,
                    action=action or "open",
                    target=app,
                    parameters={},
                    depends_on=[],
                    confidence=0.8,
                    estimated_duration=2.0
                )
                tasks.append(task)
        
        confidence = 0.8 if tasks else 0.3
        
        return NLUResult(
            success=len(tasks) > 0,
            tasks=tasks,
            confidence=confidence,
            clarifications=clarifications,
            context_used=len(context.history) > 0,
            processing_time=0.0,
            method="rule"
        )
    
    def _extract_devices(self, user_input: str) -> List[Device]:
        """从用户输入中提取设备"""
        devices = []
        user_input_lower = user_input.lower()
        
        # 遍历所有设备，查找匹配
        for device in self.device_registry.devices.values():
            # 检查设备名称
            if device.device_name.lower() in user_input_lower:
                devices.append(device)
                continue
            
            # 检查别名
            for alias in device.aliases:
                if alias.lower() in user_input_lower:
                    devices.append(device)
                    break
        
        return devices
    
    def _extract_app(self, user_input: str) -> Optional[str]:
        """从用户输入中提取应用"""
        user_input_lower = user_input.lower()
        
        for app_name, app_id in self.app_map.items():
            if app_name.lower() in user_input_lower:
                return app_id
        
        return None
    
    def _extract_action(self, user_input: str) -> Optional[str]:
        """从用户输入中提取动作"""
        user_input_lower = user_input.lower()
        
        for action_name, action_id in self.action_map.items():
            if action_name.lower() in user_input_lower:
                return action_id
        
        return None
    
    async def _understand_with_llm(
        self,
        user_input: str,
        context: ConversationContext
    ) -> NLUResult:
        """使用 LLM 进行意图识别"""
        
        # 构建设备列表
        devices_info = []
        for device in self.device_registry.get_online_devices():
            devices_info.append({
                "device_id": device.device_id,
                "device_name": device.device_name,
                "device_type": device.device_type.value,
                "status": device.status.value,
                "aliases": device.aliases,
                "capabilities": device.capabilities
            })
        
        # 构建上下文信息
        context_info = {
            "last_devices": context.last_devices,
            "last_apps": context.last_apps,
            "last_action": context.last_action
        }
        
        # 构建 Prompt
        system_prompt = """你是 UFO³ Galaxy 的自然语言理解引擎。你的任务是理解用户的指令，并将其转换为结构化的任务列表。

**特别注意：**
如果用户指令中包含“分析屏幕”、“看一眼”、“这个图表”、“这张图片”等明显的视觉分析意图，并且目标设备是“电脑”或“平板”等可以进行截图的设备，请将意图类型设置为 `visual_analysis`，动作设置为 `vlm_analyze`，目标设置为 `screenshot`，并在 `parameters` 中包含 `image_path`（一个占位符，例如 `/home/ubuntu/Downloads/temp_screenshot.png`）和 `prompt`（用户对图像的提问）。

请严格按照以下 JSON 格式输出：
{
  "success": true/false,
  "tasks": [
    {
      "task_id": "task_1",
      "device_id": "设备ID",
      "intent_type": "意图类型",
      "action": "动作",
      "target": "目标应用或对象",
      "parameters": {},
      "depends_on": [],
      "confidence": 0.0-1.0,
      "estimated_duration": 秒数
    }
  ],
  "confidence": 0.0-1.0,
  "clarifications": ["需要澄清的问题"],
  "context_used": true/false
}

意图类型包括：app_control, app_operation, file_operation, device_control, information_query, cross_device_task, media_generation, visual_analysis, system_command

注意：
1. 如果用户指令不明确，设置 success=false 并在 clarifications 中提出问题
2. 如果涉及多个设备，创建多个任务
3. 如果任务有依赖关系，使用 depends_on 字段
4. 置信度要准确反映理解的确定程度
"""

        user_prompt = f"""可用设备：
{json.dumps(devices_info, ensure_ascii=False, indent=2)}

上下文信息：
{json.dumps(context_info, ensure_ascii=False, indent=2)}

用户输入："{user_input}"

请分析用户的意图并输出 JSON 格式的结果。"""
        
        # 调用 LLM
        try:
            response = await self.llm_client.generate(user_prompt, system_prompt)
            
            # 解析 JSON 响应
            result_data = json.loads(response)
            
            # 构建 Task 对象
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
            
            return NLUResult(
                success=result_data.get("success", True),
                tasks=tasks,
                confidence=result_data.get("confidence", 0.8),
                clarifications=result_data.get("clarifications", []),
                context_used=result_data.get("context_used", False),
                processing_time=0.0,
                method="llm"
            )
        
        except Exception as e:
            print(f"LLM understanding error: {e}")
            # LLM 失败，回退到规则
            return self._understand_with_rules(user_input, context)

# ============================================================================
# 使用示例
# ============================================================================

async def main():
    """测试示例"""
    
    # 初始化组件
    device_registry = DeviceRegistry()
    llm_client = LLMClient(provider="ollama")  # 使用本地 Ollama
    vlm_client = VLMClient(provider="openrouter") # 新增 VLM 客户端
    nlu_engine = EnhancedNLUEngineV2(
        device_registry=device_registry,
        llm_client=llm_client,
        vlm_client=vlm_client, # 传入 VLM 客户端
        use_llm=True
    )
    
    # 测试用例
    test_inputs = [
        "在手机B上打开微信",
        "在平板上播放音乐",
        "在手机A上打开微信，在平板上播放YouTube",
        "把手机上的照片发到电脑",
        "在电脑上打开Chrome并搜索Python教程",
        "分析电脑屏幕上的内容，告诉我这个图表是关于什么的", # 新增 VLM 测试用例
        "帮我看看手机A上微信的聊天记录，总结一下最近的讨论点" # 跨设备 VLM 测试用例
        "打开微信",  # 没有指定设备
        "关闭它",    # 需要上下文
    ]
    
    print("="*80)
    print("UFO³ Galaxy - 增强版 NLU 引擎 v2.0 测试")
    print("="*80)
    
    for user_input in test_inputs:
        print(f"\n{'='*80}")
        print(f"用户输入: {user_input}")
        print(f"{'='*80}")
        
        # 理解用户输入
        result = await nlu_engine.understand(user_input)
        
        print(f"\n解析结果:")
        print(f"  成功: {result.success}")
        print(f"  置信度: {result.confidence:.2f}")
        print(f"  方法: {result.method}")
        print(f"  处理时间: {result.processing_time:.3f}秒")
        print(f"  使用上下文: {result.context_used}")
        
        if result.tasks:
            print(f"\n任务列表 ({len(result.tasks)} 个):")
            for task in result.tasks:
                print(f"  - 任务 {task.task_id}:")
                print(f"      设备: {task.device_id}")
                print(f"      意图: {task.intent_type.value}")
                print(f"      动作: {task.action}")
                print(f"      目标: {task.target}")
                print(f"      置信度: {task.confidence:.2f}")
                if task.depends_on:
                    print(f"      依赖: {task.depends_on}")
        
        if result.clarifications:
            print(f"\n需要澄清:")
            for clarification in result.clarifications:
                print(f"  - {clarification}")

if __name__ == "__main__":
    asyncio.run(main())
