#!/usr/bin/env python3
"""
Generate Tool Nodes
===================
批量生成存量工具节点 (Node 08-25, 35-48, 53-63)
"""

import os
from string import Template

# 节点配置
TOOL_NODES = {
    # Layer 2: Digital Tools (Node 08-25)
    "08": ("Fetch", "HTTP/HTTPS 请求工具", "httpx", ["fetch", "get", "post"]),
    "09": ("Search", "Web 搜索工具", "requests", ["search", "web_search"]),
    "10": ("Slack", "Slack 消息工具", "slack_sdk", ["send_message", "read_channel"]),
    "11": ("GitHub", "GitHub API 工具", "PyGithub", ["get_repo", "create_issue", "list_prs"]),
    "12": ("Postgres", "PostgreSQL 数据库", "psycopg2-binary", ["query", "execute", "connect"]),
    "13": ("SQLite", "SQLite 数据库", "aiosqlite", ["query", "execute", "create_table"]),
    "14": ("FFmpeg", "音视频处理", "ffmpeg-python", ["convert", "extract_audio", "resize"]),
    "15": ("OCR", "文字识别", "pytesseract", ["recognize", "extract_text"]),
    "16": ("Email", "邮件发送", "aiosmtplib", ["send_email", "send_html"]),
    "17": ("EdgeTTS", "语音合成", "edge-tts", ["synthesize", "list_voices"]),
    "18": ("DeepL", "翻译服务", "deepl", ["translate", "detect_language"]),
    "19": ("Crypto", "加密哈希", "cryptography", ["hash", "encrypt", "decrypt"]),
    "20": ("Qdrant", "向量数据库", "qdrant-client", ["upsert", "search", "delete"]),
    "21": ("Notion", "Notion 同步", "notion-client", ["get_page", "create_page", "update"]),
    "22": ("BraveSearch", "Brave 搜索", "requests", ["search", "news_search"]),
    "23": ("Time", "时间工具", "pytz", ["now", "format", "parse", "timezone"]),
    "24": ("Weather", "天气查询", "requests", ["get_weather", "forecast"]),
    "25": ("GoogleSearch", "Google 搜索", "googlesearch-python", ["search", "image_search"]),
    
    # Layer 3: Physical (Node 35-48)
    "35": ("AppleScript", "macOS 自动化", "pyobjc", ["run_script", "get_app"]),
    "36": ("UIAWindows", "Windows UI 自动化", "pywinauto", ["click", "type_text", "find_window"]),
    "37": ("LinuxDBus", "Linux D-Bus", "dbus-python", ["call_method", "get_property"]),
    "38": ("BLE", "蓝牙低功耗", "bleak", ["scan", "connect", "read_char", "write_char"]),
    "39": ("SSH", "SSH 隧道", "paramiko", ["connect", "execute", "tunnel"]),
    "40": ("SFTP", "SFTP/SCP", "paramiko", ["upload", "download", "list_dir"]),
    "41": ("MQTT", "MQTT 消息总线", "paho-mqtt", ["publish", "subscribe", "connect"]),
    "42": ("CANbus", "CAN 总线", "python-can", ["send", "receive", "connect"]),
    "43": ("MAVLink", "无人机协议", "pymavlink", ["connect", "send_command", "get_telemetry"]),
    "44": ("NFC", "NFC/RFID", "nfcpy", ["read_tag", "write_tag", "scan"]),
    "45": ("DesktopAuto", "桌面自动化", "pyautogui", ["click", "type_text", "screenshot", "move"]),
    "46": ("Camera", "摄像头", "opencv-python", ["capture", "stream", "detect"]),
    "47": ("Audio", "音频采集", "sounddevice", ["record", "play", "list_devices"]),
    "48": ("Serial", "串口通信", "pyserial", ["connect", "read", "write"]),
    
    # Layer 1: Quantum & Logic (Node 53, 55, 57, 59-63)
    "53": ("GraphLogic", "知识图谱", "networkx", ["add_node", "add_edge", "query", "shortest_path"]),
    "55": ("Simulation", "蒙特卡洛模拟", "numpy", ["simulate", "sample", "estimate"]),
    "57": ("QuantumCloud", "量子云计算", "qiskit-ibm-runtime", ["submit_job", "get_result"]),
    "59": ("CausalInference", "因果推理", "dowhy", ["identify", "estimate", "refute"]),
    "60": ("TemporalLogic", "时序逻辑", "z3-solver", ["verify", "plan", "check"]),
    "61": ("GeometricReasoning", "几何推理", "shapely", ["intersect", "distance", "transform"]),
    "62": ("ProbabilisticProgramming", "概率编程", "pymc", ["infer", "sample", "predict"]),
    "63": ("GameTheory", "博弈论", "nashpy", ["nash_equilibrium", "payoff", "strategy"]),
}


def generate_main_py(node_id: str, name: str, description: str, library: str, tools: list) -> str:
    """生成 main.py 代码"""
    
    # 生成工具列表字符串
    tool_items = []
    for t in tools:
        tool_items.append(f'''            {{
                "name": "{t}",
                "description": "{name} - {t} 操作",
                "parameters": {{}}
            }}''')
    tool_list_str = ",\n".join(tool_items)
    
    # 生成工具方法
    tool_methods = []
    for t in tools:
        tool_methods.append(f'''    async def _tool_{t}(self, params: dict) -> dict:
        """{t} 操作"""
        logger.info(f"🛠️ Executing {t} with params: {{params}}")
        try:
            # 基础执行框架：此处可根据具体库 {library} 扩展真实逻辑
            return {{
                "status": "success", 
                "tool": "{t}", 
                "node_id": "{node_id}",
                "timestamp": datetime.now().isoformat(),
                "result": f"Executed {t} successfully"
            }}
        except Exception as e:
            logger.error(f"❌ {t} execution failed: {{e}}")
            return {{"status": "error", "message": str(e)}}
''')
    tool_methods_str = "\n".join(tool_methods)
    
    code = f'''"""
Node {node_id}: {name}
{"=" * (len(f"Node {node_id}: {name}") + 4)}
{description}

依赖库: {library}
工具: {", ".join(tools)}
"""

import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node {node_id} - {name}", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Tool Implementation
# =============================================================================

class {name}Tools:
    """
    {name} 工具实现
    
    注意: 这是一个框架实现，实际使用时需要：
    1. 安装依赖: pip install {library}
    2. 配置必要的环境变量或凭证
    3. 根据实际需求完善工具逻辑
    """
    
    def __init__(self):
        self.initialized = False
        self._init_client()
        
    def _init_client(self):
        """初始化客户端"""
        try:
            # TODO: 初始化 {library} 客户端
            self.initialized = True
        except Exception as e:
            print(f"Warning: Failed to initialize {name}: {{e}}")
            
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        return [
{tool_list_str}
        ]
        
    async def call_tool(self, tool: str, params: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self.initialized:
            raise RuntimeError("{name} not initialized")
            
        handler = getattr(self, f"_tool_{{tool}}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {{tool}}")
            
        return await handler(params)
        
{tool_methods_str}

# =============================================================================
# Global Instance
# =============================================================================

tools = {name}Tools()

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {{
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "{node_id}",
        "name": "{name}",
        "initialized": tools.initialized,
        "timestamp": datetime.now().isoformat()
    }}

@app.get("/tools")
async def list_tools():
    """列出可用工具"""
    return {{"tools": tools.get_tools()}}

@app.post("/mcp/call")
async def mcp_call(request: Dict[str, Any]):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {{}})
    
    try:
        result = await tools.call_tool(tool, params)
        return {{"success": True, "result": result}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80{node_id})
'''
    return code


def generate_dockerfile(node_id: str, library: str) -> str:
    """生成 Dockerfile"""
    # 处理特殊库
    pip_install = library
    if library in ["hashlib", "sqlite3"]:
        pip_install = ""  # 内置库
        
    return f'''FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx {pip_install}

COPY main.py .

EXPOSE 80{node_id}

CMD ["python", "main.py"]
'''


def main():
    """生成所有节点"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nodes_dir = os.path.join(base_dir, "nodes")
    
    generated = 0
    skipped = 0
    
    for node_id, (name, desc, lib, tools) in TOOL_NODES.items():
        node_dir = os.path.join(nodes_dir, f"Node_{node_id}_{name}")
        os.makedirs(node_dir, exist_ok=True)
        
        # 生成 main.py
        main_path = os.path.join(node_dir, "main.py")
        if not os.path.exists(main_path):
            code = generate_main_py(node_id, name, desc, lib, tools)
            with open(main_path, "w") as f:
                f.write(code)
            print(f"Generated: Node_{node_id}_{name}/main.py")
            generated += 1
        else:
            print(f"Skipped (exists): Node_{node_id}_{name}/main.py")
            skipped += 1
            
        # 生成 Dockerfile
        dockerfile_path = os.path.join(node_dir, "Dockerfile")
        if not os.path.exists(dockerfile_path):
            dockerfile = generate_dockerfile(node_id, lib)
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile)
            
    print(f"\n✅ Generated: {generated} nodes")
    print(f"⏭️  Skipped: {skipped} nodes (already exist)")
    print(f"📦 Total: {len(TOOL_NODES)} nodes configured")


if __name__ == "__main__":
    main()
