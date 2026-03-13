"""
Windows Client 主程序

整合侧边栏 UI 和自主操纵功能
通过 HTTP 连接 Galaxy 后端 API 实现知识查询、记忆存储、代码执行等功能
F12 全局热键唤醒侧边栏
AI 大模型驱动对话
"""

import sys
import os

# 确保 Python 使用 UTF-8 编码 (修复中文用户名路径问题)
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('PYTHONUTF8', '1')

import logging
import json
import urllib.request
import urllib.error
import threading
from typing import Dict, Any, Optional


def _preflight_checks() -> bool:
    """Windows 客户端启动前置检查

    检测已知的运行时兼容性问题，给出清晰提示。
    返回 True 表示检查全部通过；返回 False 表示发现严重问题（不强制退出，由调用方决定）。
    """
    ok = True

    # --- 1. 检测非 ASCII 用户名/路径 ---
    try:
        home = os.path.expanduser("~")
        home.encode("ascii")
    except UnicodeEncodeError:
        print("⚠️  警告: 用户目录路径包含非 ASCII 字符（如中文用户名）")
        print(f"   当前路径: {home}")
        print("   这可能导致 comtypes / PyQt5 插件加载失败。")
        print("   Galaxy 将尝试自动将 comtypes 缓存重定向到 ASCII 安全路径。")
        print()
        ok = False

    # --- 2. 设置 comtypes 缓存到 ASCII 安全路径（策略 2）---
    if sys.platform == 'win32':
        try:
            from autonomy.comtypes_bootstrap import setup_comtypes_gen_dir
            cache_dir = setup_comtypes_gen_dir()
            if cache_dir:
                logging.getLogger(__name__).info(
                    "comtypes 缓存目录已设置: %s", cache_dir
                )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "comtypes 缓存重定向失败（非严重）: %s", exc
            )

    # --- 3. 设置 QT_PLUGIN_PATH 避免 PyQt5 插件搜索失败 ---
    if sys.platform == 'win32':
        try:
            import PyQt5
            qt_dir = os.path.dirname(PyQt5.__file__)
            plugins_path = os.path.join(qt_dir, "Qt5", "plugins")
            if not os.path.isdir(plugins_path):
                # 兼容不同安装布局
                plugins_path = os.path.join(qt_dir, "plugins")
            if os.path.isdir(plugins_path):
                existing = os.environ.get("QT_PLUGIN_PATH", "")
                if plugins_path not in existing:
                    os.environ["QT_PLUGIN_PATH"] = (
                        plugins_path + os.pathsep + existing if existing else plugins_path
                    )
        except Exception:
            pass  # PyQt5 未安装时跳过，后续 PYQT5_AVAILABLE 检查会处理

    # --- 4. 检测 comtypes 缓存目录可写性 ---
    if sys.platform == 'win32':
        try:
            import tempfile
            test_dir = tempfile.gettempdir()
            test_file = os.path.join(test_dir, ".galaxy_comtypes_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as exc:
            print(f"⚠️  警告: 临时目录不可写 ({exc})")
            print("   comtypes 可能无法生成缓存，建议检查磁盘空间和权限。")
            print()

    return ok

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QThread, pyqtSignal, QTimer
    PYQT5_AVAILABLE = True
except ImportError:
    PYQT5_AVAILABLE = False
    QApplication = None
    QThread = object  # fallback base class
    pyqtSignal = lambda *a: None
    QTimer = None

try:
    from ui.galaxy_client_ui import GalaxyClientUI
except ImportError:
    GalaxyClientUI = None

try:
    from ui.sidebar_ui import SidebarUI  # legacy fallback
except ImportError:
    SidebarUI = None

from autonomy.autonomy_manager import WindowsAutonomyManager
from core.port_config import get_service_port

logger = logging.getLogger(__name__)

# 后端 API 地址（默认本地）
GALAXY_API_BASE = os.environ.get("GALAXY_API_BASE", "http://localhost:8099")
# Dashboard API 地址
DASHBOARD_API_BASE = os.environ.get("DASHBOARD_API_BASE", f"http://localhost:{get_service_port('dashboard')}")


class CommandProcessor(QThread):
    """命令处理线程 - 支持 LLM 对话和本地操作

    返回结构化 JSON 响应（包含 routing, agent_steps, tool_calls），
    ChatPanel 解析并分层渲染。
    """

    response_ready = pyqtSignal(str)

    def __init__(self, autonomy_manager: WindowsAutonomyManager):
        super().__init__()
        self.autonomy_manager = autonomy_manager
        self.command = None
        self._conversation_history: list = []

    def set_command(self, command: str):
        self.command = command

    def run(self):
        if not self.command:
            return
        try:
            result = self._process_command(self.command)
            self.response_ready.emit(result)
        except Exception as e:
            logger.error(f"处理命令失败: {e}")
            self.response_ready.emit(f"错误: {str(e)}")

    def _process_command(self, command: str) -> str:
        """处理命令 - 统一通过 /api/v1/chat 智能分流

        /api/v1/chat 会自动判断:
        - 操作指令 → ReAct Agent 调度 (LLM + tool_call → 节点执行)
        - 纯聊天 → LLM 对话回复

        仅以下纯本地快捷操作保留在客户端:
        """
        command_lower = command.lower()

        # 极少数纯本地快捷操作 (不涉及设备/AI)
        if command_lower in ("截图", "screenshot"):
            return self._handle_screenshot()
        elif command_lower in ("剪贴板", "clipboard"):
            return self._handle_clipboard()
        elif command_lower in ("屏幕状态", "screen state"):
            return self._handle_screen_state()
        else:
            # 所有命令统一走后端智能分流 — 后端会自动判断:
            # - "打开手机微信" → Agent ReAct 调度设备
            # - "打开记事本" → Agent 调度本地 Windows 节点
            # - "今天天气怎么样" → 纯 LLM 对话
            return self._handle_llm_chat(command)

    # ================================================================
    # LLM 对话（核心功能）
    # ================================================================

    def add_to_history(self, role: str, content: str):
        """添加消息到对话历史"""
        self._conversation_history.append({"role": role, "content": content})
        # 保留最近 20 条
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]

    def _handle_llm_chat(self, command: str) -> str:
        """通过后端智能分流 - 自动区分聊天/操作

        返回结构化 JSON 字符串（包含 routing, agent_steps, tool_calls），
        ChatPanel.handle_structured_response() 解析并分层渲染。
        """
        # 策略 1：主系统 /api/v1/chat (自动分流到 ReAct Agent 或纯聊天)
        result = self._call_api(
            "/api/v1/chat",
            {
                "message": command,
                "device_id": "windows_client",
                "history": self._conversation_history[-10:],
            },
            base_url=GALAXY_API_BASE
        )
        reply_text = result.get("response") or result.get("reply") if result else None
        if result and result.get("success") and reply_text:
            # 保存到历史
            self.add_to_history("assistant", reply_text)
            # 确保响应里有 reply 字段（UI 兼容）
            result["reply"] = reply_text
            # 返回完整结构化 JSON
            return json.dumps(result, ensure_ascii=False)

        # 策略 2：Dashboard /api/v1/dashboard/chat
        result = self._call_api(
            "/api/v1/dashboard/chat",
            {"message": command, "session_id": "windows_client"},
            base_url=DASHBOARD_API_BASE
        )
        reply_text = result.get("response") or result.get("reply") if result else None
        if result and result.get("success") and reply_text:
            model = result.get("model", "")
            reply = reply_text
            return f"[{model}] {reply}" if model else reply

        # 策略 3：直接调用 LLM
        result = self._direct_llm_call(command)
        if result:
            return result

        return (f"收到: {command}\n\n"
                f"AI 服务未连接。请确认：\n"
                f"1. 后端服务已启动 ({GALAXY_API_BASE})\n"
                f"2. Dashboard 已启动 ({DASHBOARD_API_BASE})\n"
                f"3. 已在 Dashboard 的 API CONFIG 页配置 API Key")

    def _direct_llm_call(self, message: str) -> Optional[str]:
        """直接调用 LLM API"""
        providers = [
            ("OPENAI_API_KEY", os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"), "gpt-4o-mini"),
            ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
            ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        ]

        for key_name, base_url, model in providers:
            api_key = os.environ.get(key_name, "")
            if not api_key or api_key.startswith("your-") or api_key.startswith("sk-YOUR"):
                continue
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是 Galaxy 智能助手。"},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 2048
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=payload,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    reply = data["choices"][0]["message"]["content"]
                    return f"[{model}] {reply}"
            except Exception as e:
                logger.debug(f"Direct LLM via {key_name} failed: {e}")
        return None

    # ================================================================
    # 本地操作
    # ================================================================

    def _handle_screenshot(self) -> str:
        try:
            import tempfile
            from datetime import datetime
            screen = QApplication.primaryScreen()
            if screen is None:
                return "无法获取屏幕对象"
            screenshot = screen.grabWindow(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_dir = os.path.join(tempfile.gettempdir(), "galaxy_screenshots")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"screenshot_{timestamp}.png")
            screenshot.save(save_path, "PNG")
            return f"截图已保存: {save_path}"
        except Exception as e:
            return f"截图失败: {e}"

    def _handle_clipboard(self) -> str:
        try:
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            return f"剪贴板内容:\n{text}" if text else "剪贴板为空"
        except Exception as e:
            return f"读取剪贴板失败: {e}"

    def _handle_open(self, command: str) -> str:
        if "记事本" in command or "notepad" in command.lower():
            app_name = "notepad"
        elif "计算器" in command or "calculator" in command.lower():
            app_name = "calc"
        else:
            return self._handle_llm_chat(command)

        task = {
            'name': f'打开 {app_name}',
            'actions': [
                {'type': 'press_keys', 'params': {'keys': ['win', 'r']}},
                {'type': 'type', 'params': {'text': app_name}},
                {'type': 'press_key', 'params': {'key': 'enter'}}
            ]
        }
        result = self.autonomy_manager.execute_task(task)
        if result['success']:
            return f"成功打开 {app_name}"
        return f"打开 {app_name} 失败: {result.get('error')}"

    def _handle_click(self, command: str) -> str:
        import re
        coord_match = re.search(r'(\d+)[,\s]+(\d+)', command)
        if coord_match:
            x, y = int(coord_match.group(1)), int(coord_match.group(2))
            result = self.autonomy_manager.execute_action({'type': 'click', 'params': {'x': x, 'y': y}})
            return f"已点击坐标 ({x}, {y})" if result['success'] else f"点击失败: {result.get('error')}"

        name_match = re.search(r'["\']([^"\']+)["\']', command)
        if name_match:
            name = name_match.group(1)
            result = self.autonomy_manager.execute_action({'type': 'click_element', 'params': {'name': name}})
            return f"已点击元素: {name}" if result['success'] else f"点击元素失败: {result.get('error')}"

        return "点击: 指定坐标 (点击 100,200) 或元素 (点击 '确定')"

    def _handle_type(self, command: str) -> str:
        if "输入" in command:
            text = command.split("输入", 1)[1].strip()
        elif "type" in command.lower():
            text = command.lower().split("type", 1)[1].strip()
        else:
            return "无法识别要输入的文本"
        result = self.autonomy_manager.execute_action({'type': 'type', 'params': {'text': text}})
        return f"成功输入: {text}" if result['success'] else f"输入失败: {result.get('error')}"

    def _handle_screen_state(self) -> str:
        state = self.autonomy_manager.get_screen_state()
        if state['success']:
            return f"当前窗口: {state.get('window_name', 'Unknown')}"
        return f"获取屏幕状态失败: {state.get('error')}"

    # ================================================================
    # API 调用
    # ================================================================

    def _call_api(self, path: str, payload: dict = None, method: str = "POST",
                  base_url: str = None) -> Optional[dict]:
        url = f"{base_url or GALAXY_API_BASE}{path}"
        try:
            if method == "GET":
                req = urllib.request.Request(url)
            else:
                data = json.dumps(payload or {}).encode("utf-8")
                req = urllib.request.Request(url, data=data,
                                            headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"API 调用失败 {path}: {e}")
            return None


class GlobalHotkeyThread(threading.Thread):
    """
    全局 F12 热键监听线程
    使用 keyboard 库实现跨窗口全局热键
    """

    def __init__(self, toggle_callback):
        super().__init__()
        self.toggle_callback = toggle_callback
        self.daemon = True
        self._running = True

    def run(self):
        try:
            import keyboard
            keyboard.add_hotkey('f12', self.toggle_callback)
            logger.info("F12 全局热键已注册")
            while self._running:
                try:
                    keyboard.wait(timeout=1)
                except Exception:
                    import time
                    if not self._running:
                        break
                    time.sleep(1)
        except ImportError:
            logger.warning("keyboard 库不可用，F12 热键降级为窗口内快捷键。安装: pip install keyboard")
        except Exception as e:
            logger.error(f"F12 热键注册失败: {e}")

    def stop(self):
        self._running = False


class WindowsClient:
    """Windows Client 主类 - F12 热键 + LLM 对话"""

    def __init__(self):
        self.autonomy_manager = WindowsAutonomyManager()

        self.command_processor = CommandProcessor(self.autonomy_manager)
        self.command_processor.response_ready.connect(self._on_response)

        # OPPO 光场设计客户端 (混合模式: 侧边栏 + 全功能窗口)
        api_base = os.environ.get("DASHBOARD_API_BASE", f"http://localhost:{get_service_port('dashboard')}")
        self.ui = GalaxyClientUI(api_base=api_base, on_command=self._on_command)

        # 全局 F12 热键
        self.hotkey_thread = GlobalHotkeyThread(
            toggle_callback=self._toggle_sidebar_safe
        )
        self.hotkey_thread.start()

        # 加载 .env
        self._load_env()

        logger.info("Windows Client 初始化成功（F12 全局热键已启用）")

    def _load_env(self):
        """加载 .env 到环境变量"""
        from pathlib import Path
        project_root = str(Path(__file__).resolve().parent.parent)
        env_path = os.path.join(project_root, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if k and k not in os.environ:
                                os.environ[k] = v
                logger.info(f"已加载环境变量: {env_path}")
            except Exception as e:
                logger.warning(f"加载 .env 失败: {e}")

    def _toggle_sidebar_safe(self):
        """线程安全地切换侧边栏（从 keyboard 回调跳转到 Qt 主线程）"""
        QTimer.singleShot(0, self.ui.toggle_visibility)

    def _on_command(self, command: str):
        logger.info(f"收到命令: {command}")
        # 添加用户消息到 CommandProcessor 历史
        self.command_processor.add_to_history("user", command)
        self.ui.update_status("处理中", "#ffd60a")
        self.command_processor.set_command(command)
        self.command_processor.start()

    def _on_response(self, response: str):
        logger.info(f"收到响应: {response[:100]}...")
        # ChatPanel 处理结构化 JSON 或纯文本
        self.ui.chat_panel.handle_structured_response(response)
        self.ui.update_status("在线")

    def run(self):
        self.ui.show_sidebar()
        logger.info("Windows Client 启动 - 按 F12 切换侧边栏")

    def stop(self):
        if hasattr(self, 'hotkey_thread'):
            self.hotkey_thread.stop()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    _preflight_checks()

    if not PYQT5_AVAILABLE:
        print("错误: 无法加载 OPPO 光场 UI 模块 — PyQt5 未安装")
        print("请安装依赖: pip install PyQt5 PyQtWebEngine")
        print("如使用 conda: conda install pyqt")
        sys.exit(1)

    if GalaxyClientUI is None:
        print("错误: 无法加载 GalaxyClientUI 模块")
        print("请检查 windows_client/ui/galaxy_client_ui.py 及其依赖")
        sys.exit(1)

    try:
        app = QApplication(sys.argv)
        client = WindowsClient()
        client.run()
        app.aboutToQuit.connect(client.stop)
        sys.exit(app.exec_())
    except Exception as e:
        err_msg = str(e)
        logger.error(f"Windows Client 启动失败: {err_msg}")
        print(f"\n❌ 启动失败: {err_msg}")
        if "comtypes" in err_msg.lower() or "typelib" in err_msg.lower() \
                or "uiautomationclient" in err_msg.lower():
            print("  可能原因: comtypes 缓存与当前 Python 版本不兼容，")
            print("            或缓存路径包含非 ASCII 字符（中文用户名）。")
            print("  Galaxy 已尝试自动修复；如仍失败，请手动清理缓存后重试：")
            print("    cmd.exe:    del /s /q %LOCALAPPDATA%\\Temp\\comtypes_cache")
            print("    PowerShell: Remove-Item -Recurse -Force $env:LOCALAPPDATA\\Temp\\comtypes_cache")
            print("  或设置 GALAXY_COMTYPES_CACHE 环境变量到纯 ASCII 路径：")
            print("    set GALAXY_COMTYPES_CACHE=C:\\galaxy_cache")
            # 输出详细诊断信息到日志
            try:
                from autonomy.comtypes_bootstrap import log_diagnostics
                log_diagnostics()
            except Exception:
                pass
        elif "plugin" in err_msg.lower() or "qt" in err_msg.lower():
            print("  可能原因: PyQt5 插件路径未找到。")
            print("  修复建议: pip install --force-reinstall PyQt5 PyQtWebEngine")
        elif "ascii" in err_msg.lower() or "encode" in err_msg.lower() or "codec" in err_msg.lower():
            print("  可能原因: 路径包含非 ASCII 字符（中文用户名）。")
            print("  修复建议: 使用纯英文用户账户运行，或将项目放在 C:\\galaxy\\ 等 ASCII 路径下。")
            print("  或设置 GALAXY_COMTYPES_CACHE=C:\\galaxy_cache 环境变量。")
        sys.exit(1)


if __name__ == "__main__":
    main()
