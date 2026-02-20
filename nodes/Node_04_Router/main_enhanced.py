"""
Node 04: Enhanced Global Router & Intelligent Tool Discovery
智能工具发现与 AI 驱动路由系统
"""

import os
import sys
import json
import yaml
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import asyncio

app = FastAPI(title="Node 04: Enhanced Global Router")

# ============================================================================
# Configuration
# ============================================================================

ONEAPI_URL = os.getenv("ONEAPI_URL", "http://localhost:3000/v1/chat/completions")
ONEAPI_KEY = os.getenv("ONEAPI_API_KEY", "")
PROTOCOL_PATH = os.getenv("PROTOCOL_PATH", "/app/config/tool_discovery_protocol.yaml")

# ============================================================================
# Models
# ============================================================================

class ToolDiscoveryRequest(BaseModel):
    platform: str = "auto"  # auto, windows, android, linux, macos
    scan_paths: Optional[List[str]] = None

class ToolInvokeRequest(BaseModel):
    task_description: str
    context: Optional[Dict[str, Any]] = {}
    preferred_tools: Optional[List[str]] = []

class ToolExecuteRequest(BaseModel):
    tool_name: str
    action: str
    params: Dict[str, Any]

# ============================================================================
# Tool Registry
# ============================================================================

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict] = {}
        self.protocol: Dict = {}
        self.load_protocol()
        self.discover_tools()
    
    def load_protocol(self):
        """加载工具发现协议"""
        try:
            if os.path.exists(PROTOCOL_PATH):
                with open(PROTOCOL_PATH, 'r', encoding='utf-8') as f:
                    self.protocol = yaml.safe_load(f)
            else:
                self.protocol = self.get_default_protocol()
        except Exception as e:
            print(f"Failed to load protocol: {e}")
            self.protocol = self.get_default_protocol()
    
    def get_default_protocol(self) -> Dict:
        """默认协议"""
        return {
            "version": "1.0",
            "windows_tools": {},
            "android_tools": {},
            "capability_inference_rules": {}
        }
    
    def discover_tools(self):
        """自动发现工具"""
        current_platform = platform.system().lower()
        
        if current_platform == "windows":
            self.discover_windows_tools()
        elif current_platform == "linux":
            # 可能是 PC Linux 或 Android (Termux)
            if self.is_android():
                self.discover_android_tools()
            else:
                self.discover_linux_tools()
        elif current_platform == "darwin":
            self.discover_macos_tools()
        
        # 加载协议中预定义的工具
        self.load_predefined_tools()
    
    def discover_windows_tools(self):
        """发现 Windows 工具"""
        search_paths = [
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            os.path.expanduser("~\\AppData\\Local"),
            os.path.expanduser("~\\AppData\\Roaming")
        ]
        
        for path in search_paths:
            if not os.path.exists(path):
                continue
            
            try:
                for root, dirs, files in os.walk(path):
                    # 限制搜索深度
                    if root.count(os.sep) - path.count(os.sep) > 2:
                        continue
                    
                    for file in files:
                        if file.endswith('.exe'):
                            exe_path = os.path.join(root, file)
                            tool_name = file.replace('.exe', '').lower()
                            
                            # 推断工具能力
                            capabilities = self.infer_capabilities(tool_name, exe_path)
                            
                            self.tools[tool_name] = {
                                "name": file.replace('.exe', ''),
                                "platform": "windows",
                                "type": "executable",
                                "path": exe_path,
                                "capabilities": capabilities,
                                "discovered": True
                            }
            except Exception as e:
                print(f"Error scanning {path}: {e}")
    
    def discover_android_tools(self):
        """发现 Android 工具 (通过 pm list packages)"""
        try:
            result = subprocess.run(
                ["pm", "list", "packages"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            for line in result.stdout.split('\n'):
                if line.startswith('package:'):
                    package = line.replace('package:', '').strip()
                    
                    # 推断 App 能力
                    capabilities = self.infer_capabilities(package, package)
                    
                    self.tools[package] = {
                        "name": package.split('.')[-1],
                        "platform": "android",
                        "type": "app",
                        "path": package,
                        "capabilities": capabilities,
                        "discovered": True
                    }
        except Exception as e:
            print(f"Error discovering Android tools: {e}")
    
    def discover_linux_tools(self):
        """发现 Linux 工具"""
        # 扫描 PATH 中的命令
        path_dirs = os.environ.get('PATH', '').split(':')
        
        for dir_path in path_dirs:
            if not os.path.exists(dir_path):
                continue
            
            try:
                for file in os.listdir(dir_path):
                    file_path = os.path.join(dir_path, file)
                    if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                        capabilities = self.infer_capabilities(file, file_path)
                        
                        self.tools[file] = {
                            "name": file,
                            "platform": "linux",
                            "type": "command",
                            "path": file_path,
                            "capabilities": capabilities,
                            "discovered": True
                        }
            except Exception as e:
                print(f"Error scanning {dir_path}: {e}")
    
    def discover_macos_tools(self):
        """发现 macOS 工具"""
        # 扫描 /Applications
        app_dir = "/Applications"
        if os.path.exists(app_dir):
            for app in os.listdir(app_dir):
                if app.endswith('.app'):
                    app_path = os.path.join(app_dir, app)
                    app_name = app.replace('.app', '').lower()
                    
                    capabilities = self.infer_capabilities(app_name, app_path)
                    
                    self.tools[app_name] = {
                        "name": app.replace('.app', ''),
                        "platform": "macos",
                        "type": "app",
                        "path": app_path,
                        "capabilities": capabilities,
                        "discovered": True
                    }
    
    def load_predefined_tools(self):
        """加载协议中预定义的工具"""
        current_platform = platform.system().lower()
        
        if current_platform == "windows":
            predefined = self.protocol.get("windows_tools", {})
        elif current_platform == "linux":
            if self.is_android():
                predefined = self.protocol.get("android_tools", {})
            else:
                predefined = self.protocol.get("linux_tools", {})
        elif current_platform == "darwin":
            predefined = self.protocol.get("macos_tools", {})
        else:
            predefined = {}
        
        for tool_name, tool_config in predefined.items():
            # 检查工具是否真实存在
            if self.verify_tool_exists(tool_config):
                self.tools[tool_name] = {
                    **tool_config,
                    "discovered": False,
                    "predefined": True
                }
    
    def verify_tool_exists(self, tool_config: Dict) -> bool:
        """验证工具是否存在"""
        path = tool_config.get("path", "")
        
        if tool_config.get("platform") == "android":
            # Android 通过 pm 检查
            try:
                result = subprocess.run(
                    ["pm", "path", path],
                    capture_output=True,
                    timeout=5
                )
                return result.returncode == 0
            except Exception:
                return False
        else:
            # 其他平台检查文件路径
            return os.path.exists(path)
    
    def infer_capabilities(self, name: str, path: str) -> List[str]:
        """推断工具能力"""
        capabilities = []
        
        # 基于名称的推断规则
        name_lower = name.lower()
        
        if any(keyword in name_lower for keyword in ['code', 'edit', 'ide']):
            capabilities.append('code_editing')
        if any(keyword in name_lower for keyword in ['debug']):
            capabilities.append('debugging')
        if any(keyword in name_lower for keyword in ['git']):
            capabilities.append('version_control')
        if any(keyword in name_lower for keyword in ['term', 'shell', 'console']):
            capabilities.append('shell_commands')
        if any(keyword in name_lower for keyword in ['auto', 'macro']):
            capabilities.append('automation')
        if any(keyword in name_lower for keyword in ['photo', 'image', 'picture']):
            capabilities.append('image_processing')
        if any(keyword in name_lower for keyword in ['video', 'media']):
            capabilities.append('video_processing')
        
        # 如果没有推断出任何能力，标记为 unknown
        if not capabilities:
            capabilities.append('unknown')
        
        return capabilities
    
    def is_android(self) -> bool:
        """判断是否在 Android 环境"""
        return os.path.exists('/system/build.prop')
    
    async def ai_infer_tool(self, task_description: str, context: Dict) -> Dict:
        """使用 AI 推断最合适的工具"""
        tools_summary = {
            name: {
                "capabilities": tool["capabilities"],
                "platform": tool["platform"]
            }
            for name, tool in self.tools.items()
        }
        
        prompt = f"""你是一个智能工具路由器。根据用户任务描述，从可用工具中选择最合适的工具。

任务描述: {task_description}

可用工具:
{json.dumps(tools_summary, indent=2, ensure_ascii=False)}

上下文信息:
{json.dumps(context, indent=2, ensure_ascii=False)}

请返回 JSON 格式的响应:
{{
  "selected_tool": "工具名称",
  "reason": "选择理由",
  "action": "具体操作",
  "params": {{"参数名": "参数值"}},
  "alternative_tools": ["备选工具1", "备选工具2"]
}}
"""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    ONEAPI_URL,
                    headers={
                        "Authorization": f"Bearer {ONEAPI_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4",
                        "messages": [
                            {"role": "system", "content": "你是一个智能工具路由助手。"},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result["choices"][0]["message"]["content"]
                    
                    # 尝试解析 JSON
                    try:
                        return json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        # 如果不是纯 JSON，尝试提取
                        import re
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            return json.loads(json_match.group())
                        else:
                            return {"error": "AI response is not valid JSON"}
                else:
                    return {"error": f"OneAPI error: {response.status_code}"}
        except Exception as e:
            return {"error": f"AI inference failed: {str(e)}"}
    
    def execute_tool(self, tool_name: str, action: str, params: Dict) -> Dict:
        """执行工具调用"""
        if tool_name not in self.tools:
            return {"success": False, "error": f"Tool '{tool_name}' not found"}
        
        tool = self.tools[tool_name]
        
        try:
            if tool["platform"] == "windows":
                return self.execute_windows_tool(tool, action, params)
            elif tool["platform"] == "android":
                return self.execute_android_tool(tool, action, params)
            elif tool["platform"] in ["linux", "macos"]:
                return self.execute_unix_tool(tool, action, params)
            else:
                return {"success": False, "error": f"Unsupported platform: {tool['platform']}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def execute_windows_tool(self, tool: Dict, action: str, params: Dict) -> Dict:
        """执行 Windows 工具"""
        path = tool["path"]
        
        # 构建命令
        if action == "open_file" and "file_path" in params:
            cmd = [path, params["file_path"]]
        elif action == "cli" and "args" in params:
            cmd = [path] + params["args"].split()
        else:
            cmd = [path]
        
        # 执行
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    
    def execute_android_tool(self, tool: Dict, action: str, params: Dict) -> Dict:
        """执行 Android 工具"""
        package = tool["path"]
        
        # 通过 Intent 启动
        cmd = ["am", "start", "-n", f"{package}/.MainActivity"]
        
        if "action" in params:
            cmd.extend(["--es", "action", params["action"]])
        if "data" in params:
            cmd.extend(["--es", "data", json.dumps(params["data"])])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        return {
            "success": "Starting" in result.stdout or result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    
    def execute_unix_tool(self, tool: Dict, action: str, params: Dict) -> Dict:
        """执行 Unix/Linux/macOS 工具"""
        path = tool["path"]
        
        if "args" in params:
            cmd = [path] + params["args"].split()
        else:
            cmd = [path]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }

# ============================================================================
# Global Instance
# ============================================================================

registry = ToolRegistry()

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_04_Router_Enhanced",
        "tools_discovered": len(registry.tools),
        "platform": platform.system()
    }

@app.get("/tools")
async def list_tools():
    """列出所有发现的工具"""
    return {
        "total": len(registry.tools),
        "tools": registry.tools
    }

@app.post("/tools/discover")
async def discover_tools(request: ToolDiscoveryRequest):
    """重新扫描工具"""
    registry.discover_tools()
    return {
        "success": True,
        "tools_discovered": len(registry.tools)
    }

@app.post("/tools/invoke")
async def invoke_tool(request: ToolInvokeRequest):
    """AI 驱动的智能工具调用"""
    # 使用 AI 推断最合适的工具
    ai_result = await registry.ai_infer_tool(
        request.task_description,
        request.context
    )
    
    if "error" in ai_result:
        return {
            "success": False,
            "error": ai_result["error"]
        }
    
    # 执行工具
    tool_name = ai_result.get("selected_tool")
    action = ai_result.get("action", "cli")
    params = ai_result.get("params", {})
    
    execution_result = registry.execute_tool(tool_name, action, params)
    
    return {
        "success": execution_result.get("success", False),
        "ai_reasoning": {
            "selected_tool": tool_name,
            "reason": ai_result.get("reason"),
            "alternatives": ai_result.get("alternative_tools", [])
        },
        "execution": execution_result
    }

@app.post("/tools/execute")
async def execute_tool(request: ToolExecuteRequest):
    """直接执行指定工具"""
    result = registry.execute_tool(
        request.tool_name,
        request.action,
        request.params
    )
    return result

# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8004))
    uvicorn.run(app, host="0.0.0.0", port=port)
