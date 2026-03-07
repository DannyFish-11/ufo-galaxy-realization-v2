"""
Windows 本地 MCP Server
=======================

将 windows_client/autonomy/ 的本地能力暴露为标准 MCP JSON-RPC 工具，
使大模型（ReAct Agent）可以直接调用 Windows UI 自动化能力。

支持的工具:
  - get_screen_state   获取前台窗口 UI 树
  - click              鼠标点击
  - type               键盘输入文本
  - press_key          按单个键
  - press_keys         按组合键
  - scroll             滚动鼠标滚轮
  - find_and_click     查找 UI 元素并点击
  - find_and_type      查找 UI 元素并输入文本
  - screenshot         截取屏幕截图（返回 base64）

启动方式:
    python windows_client/windows_mcp_server.py

协议:
    标准 MCP JSON-RPC 2.0 over stdio
    兼容 core/mcp_loader.py 的 MCPLoader

Author: Galaxy Team
Version: 1.0.0
"""

import json
import sys
import logging
import base64
import io
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("windows-mcp-server")


# ============================================================================
# 工具定义
# ============================================================================

TOOLS = [
    {
        "name": "get_screen_state",
        "description": "获取当前前台窗口的 UI 树结构，返回可操作的界面元素层级。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "click",
        "description": "在屏幕指定坐标执行鼠标点击。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "点击位置 X 坐标（像素）"},
                "y": {"type": "integer", "description": "点击位置 Y 坐标（像素）"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "鼠标按键，默认 left",
                    "default": "left",
                },
                "double": {
                    "type": "boolean",
                    "description": "是否双击，默认 false",
                    "default": False,
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type",
        "description": "向当前焦点输入框键入文本。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
                "interval": {
                    "type": "number",
                    "description": "每个字符之间的间隔（秒），默认 0.05",
                    "default": 0.05,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": "按下单个键，支持 enter / escape / tab / backspace / delete / up / down / left / right / win / f1-f12 等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "键名，例如 'enter'、'escape'、'f5'"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "press_keys",
        "description": "按下组合键，例如 ['ctrl', 'c'] 表示复制。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "键名列表，例如 ['ctrl', 'c'] 或 ['win', 'r']",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "scroll",
        "description": "在当前鼠标位置滚动鼠标滚轮。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "滚动量，正数向上滚，负数向下滚，默认 120",
                    "default": 120,
                },
            },
            "required": [],
        },
    },
    {
        "name": "find_and_click",
        "description": "根据 UI 元素名称或 AutomationId 查找控件并点击它。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "元素名称（Name 属性）"},
                "automation_id": {"type": "string", "description": "AutomationId 属性"},
            },
        },
    },
    {
        "name": "find_and_type",
        "description": "根据 UI 元素名称或 AutomationId 查找输入框，并输入指定文本。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "元素名称（Name 属性）"},
                "automation_id": {"type": "string", "description": "AutomationId 属性"},
                "text": {"type": "string", "description": "要输入的文本"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "screenshot",
        "description": "截取当前屏幕截图，返回 base64 编码的 PNG 图像。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ============================================================================
# 自动化管理器（懒加载，仅 Windows 可用）
# ============================================================================

_autonomy_manager = None


def _get_manager():
    """懒加载 WindowsAutonomyManager（仅 Windows 平台）"""
    global _autonomy_manager
    if _autonomy_manager is None:
        try:
            import sys
            import os
            # 确保 windows_client 目录在 sys.path
            _client_dir = os.path.dirname(os.path.abspath(__file__))
            _root_dir = os.path.dirname(_client_dir)
            for p in [_client_dir, _root_dir]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from windows_client.autonomy.autonomy_manager import WindowsAutonomyManager
            _autonomy_manager = WindowsAutonomyManager()
            logger.info("WindowsAutonomyManager 初始化成功")
        except Exception as e:
            logger.warning(f"WindowsAutonomyManager 初始化失败（非 Windows 环境）: {e}")
    return _autonomy_manager


# ============================================================================
# 工具执行
# ============================================================================

def _take_screenshot() -> Dict[str, Any]:
    """截屏并返回 base64 PNG"""
    try:
        import PIL.ImageGrab as ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"success": True, "image_base64": b64, "format": "png"}
    except ImportError:
        pass
    try:
        import pyautogui
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"success": True, "image_base64": b64, "format": "png"}
    except Exception as e:
        return {"success": False, "error": f"截屏失败: {e}"}


def _execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """执行工具并返回结果"""
    if name == "screenshot":
        return _take_screenshot()

    manager = _get_manager()
    if manager is None:
        return {"success": False, "error": "Windows 自动化管理器不可用（请在 Windows 上运行）"}

    if name == "get_screen_state":
        return manager.get_screen_state()

    # 将扁平参数转换为 execute_action 期望的格式
    action_map = {
        "click": {"type": "click", "params": arguments},
        "type": {"type": "type", "params": arguments},
        "press_key": {"type": "press_key", "params": arguments},
        "press_keys": {"type": "press_keys", "params": arguments},
        "scroll": {"type": "scroll", "params": arguments},
        "find_and_click": {"type": "find_and_click", "params": arguments},
        "find_and_type": {"type": "find_and_type", "params": arguments},
    }

    if name not in action_map:
        return {"success": False, "error": f"未知工具: {name}"}

    return manager.execute_action(action_map[name])


# ============================================================================
# MCP JSON-RPC 处理器
# ============================================================================

_request_id_counter = 0


def _handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理 MCP JSON-RPC 请求，返回响应（通知类消息返回 None）"""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    # 通知消息（无 id）无需回复
    if req_id is None and method.startswith("notifications/"):
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "windows-local-mcp", "version": "1.0.0"},
        })

    if method == "tools/list":
        return ok({"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            result = _execute_tool(tool_name, arguments)
            # MCP 规范: result.content 是 list of content blocks
            content_text = json.dumps(result, ensure_ascii=False)
            return ok({
                "content": [{"type": "text", "text": content_text}],
                "isError": not result.get("success", True),
            })
        except Exception as e:
            logger.exception(f"工具执行异常: {tool_name}")
            return err(-32603, str(e))

    if method == "resources/list":
        return ok({"resources": []})

    if method == "prompts/list":
        return ok({"prompts": []})

    # 未知方法
    return err(-32601, f"Method not found: {method}")


# ============================================================================
# 主循环 — stdio JSON-RPC
# ============================================================================

def main():
    """MCP Server 主循环 — 从 stdin 读取请求，向 stdout 写入响应"""
    logger.info("Windows MCP Server 启动（等待 JSON-RPC 请求）")

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            print(json.dumps(err_resp, ensure_ascii=False), flush=True)
            continue

        response = _handle_request(request)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
