"""
Galaxy Fusion - Android Granular Adapter
功能: 将 AIP v3.0 消息转化为 Node 33 (ADB) / Node 34 (Scrcpy) 可执行的颗粒级指令。
支持完整的设备控制命令集: click, swipe, input, keyevent, screenshot, shell, app_launch等。

**v3-only contract**
--------------------
This adapter accepts only AIP v3.0 (or later) :class:`AIPMessage` objects.
Legacy AIP v1/v2 messages **must** be normalised to v3 by
:func:`galaxy_gateway.protocol.compat.parse_message_compat` *before* being
passed to :meth:`AndroidGranularAdapter.dispatch_aip_message`.  Passing a
pre-v3 message directly raises :class:`AIPAdapterVersionError`.
"""
import logging
import base64
from typing import Dict, Any, Optional, List
from .protocol.aip_v3 import AIPMessage, MessageType

logger = logging.getLogger("AndroidGranularAdapter")


class AIPAdapterVersionError(ValueError):
    """Raised when an AIPMessage with version < 3.0 is passed directly to
    :class:`AndroidGranularAdapter`.

    Legacy messages must be normalised to v3 via
    :func:`galaxy_gateway.protocol.compat.parse_message_compat` first.
    """


def _require_v3(message: AIPMessage) -> None:
    """Assert that *message* carries AIP version >= 3.0.

    :raises AIPAdapterVersionError: when ``message.version`` is absent,
        empty, or below "3.x".
    """
    version = getattr(message, "version", None) or ""
    if not version.startswith("3"):
        raise AIPAdapterVersionError(
            f"AndroidGranularAdapter is v3-only: received version={version!r}. "
            "Normalise legacy messages with parse_message_compat() before "
            "passing them to the adapter."
        )


class AndroidGranularAdapter:
    """AIP v3-only adapter that dispatches :class:`AIPMessage` objects to
    concrete Android ADB/Scrcpy operations.

    **Contract**: all messages received by this adapter must already be
    AIP v3.0 or later.  Legacy AIP v1/v2 payloads must pass through
    :func:`galaxy_gateway.protocol.compat.parse_message_compat` (or
    :func:`~galaxy_gateway.protocol.compat.parse_message_strict`) before
    reaching this class.  The adapter itself performs no legacy parsing or
    fallback; an :class:`AIPAdapterVersionError` is raised for any message
    whose ``version`` field does not start with ``"3"``.
    """

    def __init__(self, adb_executor: Any):
        self.adb = adb_executor
        self._command_handlers = {
            "click": self._handle_click,
            "tap": self._handle_click,
            "swipe": self._handle_swipe,
            "type": self._handle_type,
            "input_text": self._handle_type,
            "keyevent": self._handle_keyevent,
            "key_event": self._handle_keyevent,
            "screenshot": self._handle_screenshot,
            "screen_capture": self._handle_screenshot,
            "shell": self._handle_shell,
            "app_launch": self._handle_app_launch,
            "open_app": self._handle_app_launch,
            "install_apk": self._handle_install_apk,
            "list_packages": self._handle_list_packages,
            "device_info": self._handle_device_info,
            "scroll": self._handle_scroll,
            "long_press": self._handle_long_press,
            "back": self._handle_back,
            "home": self._handle_home,
            "recent_apps": self._handle_recent_apps,
            "wake_screen": self._handle_wake_screen,
            "lock_screen": self._handle_lock_screen,
            "volume_up": self._handle_volume_up,
            "volume_down": self._handle_volume_down,
            "set_clipboard": self._handle_set_clipboard,
            "get_clipboard": self._handle_get_clipboard,
        }
        logger.info("Android Granular Adapter Initialized with %d commands.", len(self._command_handlers))

    async def dispatch_aip_message(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """Dispatch an AIP v3 message to the corresponding Android operation.

        :param device_id: Target Android device identifier.
        :param message: An :class:`AIPMessage` that **must** carry
            ``version="3.x"``.  Legacy messages must be normalised by
            :func:`galaxy_gateway.protocol.compat.parse_message_compat`
            before being passed here.
        :raises AIPAdapterVersionError: when *message.version* is not a v3
            version string.
        """
        # v3-only enforcement: reject pre-v3 messages at the adapter surface.
        _require_v3(message)

        # v3: message.type holds the unified message type
        msg_type = message.type

        # 处理命令消息
        if msg_type in (MessageType.COMMAND, MessageType.COMMAND_BATCH):
            return await self._dispatch_control(device_id, message)

        # 处理 GUI / 扩展消息 (type is the action, not a separate extended_type field)
        return await self._dispatch_extended(device_id, message, msg_type.value)

    async def _dispatch_control(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """分发控制命令"""
        # v3: payload is a plain dict
        data = message.payload or {}
        command = data.get("command", message.type.value)
        params = data.get("params", {})

        handler = self._command_handlers.get(command)
        if handler:
            try:
                result = await handler(device_id, params)
                return self._success_response(message, result)
            except Exception as e:
                logger.error(f"Command '{command}' failed on {device_id}: {e}")
                return self._error_response(message, str(e))
        else:
            logger.warning(f"Unknown command: {command}")
            return self._error_response(message, f"Unknown command: {command}")

    async def _dispatch_extended(self, device_id: str, message: AIPMessage, ext_type: str) -> Optional[AIPMessage]:
        """分发扩展类型消息"""
        # v3: payload is a plain dict
        data = message.payload or {}

        ext_handlers = {
            MessageType.GUI_CLICK.value: self._handle_gui_click,
            MessageType.GUI_SWIPE.value: self._handle_gui_swipe,
            MessageType.GUI_INPUT.value: self._handle_gui_input,
            MessageType.GUI_SCREENSHOT.value: self._handle_screenshot,
            MessageType.GUI_ELEMENT_QUERY.value: self._handle_element_query,
            MessageType.COMMAND.value: self._dispatch_control,
        }

        handler = ext_handlers.get(ext_type)
        if handler:
            try:
                if handler == self._dispatch_control:
                    return await handler(device_id, message)
                result = await handler(device_id, data)
                return self._success_response(message, result)
            except Exception as e:
                logger.error(f"Extended command '{ext_type}' failed: {e}")
                return self._error_response(message, str(e))

        return self._error_response(message, f"Unknown extended type: {ext_type}")

    # ========================= 命令处理器 =========================

    async def _handle_click(self, device_id: str, params: Dict) -> Dict:
        """处理点击操作"""
        x, y = params.get("x", 0), params.get("y", 0)
        await self.adb.shell(f"input tap {x} {y}", device_id)
        return {"status": "success", "action": "click", "x": x, "y": y}

    async def _handle_swipe(self, device_id: str, params: Dict) -> Dict:
        """处理滑动操作"""
        x1 = params.get("start_x", params.get("x1", 0))
        y1 = params.get("start_y", params.get("y1", 0))
        x2 = params.get("end_x", params.get("x2", 0))
        y2 = params.get("end_y", params.get("y2", 0))
        duration = params.get("duration", 300)
        await self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {duration}", device_id)
        return {"status": "success", "action": "swipe", "from": [x1, y1], "to": [x2, y2]}

    async def _handle_type(self, device_id: str, params: Dict) -> Dict:
        """处理文本输入"""
        text = params.get("text", "")
        # 转义特殊字符
        escaped = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>").replace("'", "\\'").replace('"', '\\"')
        await self.adb.shell(f"input text '{escaped}'", device_id)
        return {"status": "success", "action": "type", "text_length": len(text)}

    async def _handle_keyevent(self, device_id: str, params: Dict) -> Dict:
        """处理按键事件"""
        key = params.get("key", params.get("keycode", ""))
        key_map = {
            "home": "3", "back": "4", "call": "5", "endcall": "6",
            "volume_up": "24", "volume_down": "25", "power": "26",
            "camera": "27", "enter": "66", "delete": "67", "backspace": "67",
            "tab": "61", "space": "62", "menu": "82", "search": "84",
            "recent_apps": "187", "app_switch": "187",
            "notification": "83", "settings": "176",
            "media_play_pause": "85", "media_stop": "86",
            "media_next": "87", "media_previous": "88",
            "mute": "164", "brightness_up": "221", "brightness_down": "220",
        }
        keycode = key_map.get(str(key).lower(), str(key))
        await self.adb.shell(f"input keyevent {keycode}", device_id)
        return {"status": "success", "action": "keyevent", "key": keycode}

    async def _handle_screenshot(self, device_id: str, params: Dict) -> Dict:
        """处理截图操作"""
        result = await self.adb.shell("screencap -p /sdcard/screenshot.png", device_id)
        # 拉取截图文件
        pull_result = await self.adb.pull("/sdcard/screenshot.png", "/tmp/screenshot.png", device_id)
        # 读取并转为base64
        try:
            with open("/tmp/screenshot.png", "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            return {"status": "success", "action": "screenshot", "image_base64": image_data}
        except FileNotFoundError:
            return {"status": "success", "action": "screenshot", "note": "screenshot saved on device"}

    async def _handle_shell(self, device_id: str, params: Dict) -> Dict:
        """处理Shell命令"""
        command = params.get("command", "")
        # 安全检查 - 禁止危险命令
        dangerous = ["rm -rf /", "dd if=/dev/zero", "mkfs", "format"]
        if any(d in command.lower() for d in dangerous):
            return {"status": "error", "action": "shell", "error": "Dangerous command blocked"}
        result = await self.adb.shell(command, device_id)
        return {"status": "success", "action": "shell", "output": str(result)}

    async def _handle_app_launch(self, device_id: str, params: Dict) -> Dict:
        """处理应用启动"""
        package = params.get("package", params.get("app", ""))
        # 常见应用包名映射
        app_map = {
            "微信": "com.tencent.mm", "wechat": "com.tencent.mm",
            "微博": "com.sina.weibo", "weibo": "com.sina.weibo",
            "抖音": "com.ss.android.ugc.aweme", "tiktok": "com.ss.android.ugc.aweme",
            "支付宝": "com.eg.android.AlipayGphone", "alipay": "com.eg.android.AlipayGphone",
            "设置": "com.android.settings", "settings": "com.android.settings",
            "相机": "com.android.camera", "camera": "com.android.camera",
            "浏览器": "com.android.browser", "browser": "com.android.browser",
            "chrome": "com.android.chrome",
            "地图": "com.autonavi.minimap", "maps": "com.google.android.apps.maps",
            "淘宝": "com.taobao.taobao", "京东": "com.jingdong.app.mall",
            "qq": "com.tencent.mobileqq", "QQ": "com.tencent.mobileqq",
            "bilibili": "tv.danmaku.bili", "b站": "tv.danmaku.bili",
        }
        resolved_package = app_map.get(package, package)
        await self.adb.shell(
            f"monkey -p {resolved_package} -c android.intent.category.LAUNCHER 1",
            device_id
        )
        return {"status": "success", "action": "app_launch", "package": resolved_package}

    async def _handle_install_apk(self, device_id: str, params: Dict) -> Dict:
        """处理APK安装"""
        apk_path = params.get("path", "")
        result = await self.adb.install(apk_path, device_id)
        return {"status": "success", "action": "install_apk", "path": apk_path, "result": str(result)}

    async def _handle_list_packages(self, device_id: str, params: Dict) -> Dict:
        """处理列出已安装应用（安全：Python 侧过滤，不使用 shell 管道）"""
        filter_str = params.get("filter", "")
        result = await self.adb.shell("pm list packages", device_id)
        packages = [line.replace("package:", "").strip() for line in str(result).split("\n") if line.strip()]
        if filter_str:
            packages = [p for p in packages if filter_str in p]
        return {"status": "success", "action": "list_packages", "packages": packages}

    async def _handle_device_info(self, device_id: str, params: Dict) -> Dict:
        """获取设备信息"""
        model = await self.adb.shell("getprop ro.product.model", device_id)
        android_ver = await self.adb.shell("getprop ro.build.version.release", device_id)
        screen_size = await self.adb.shell("wm size", device_id)
        battery = await self.adb.shell("dumpsys battery | grep level", device_id)
        return {
            "status": "success",
            "action": "device_info",
            "model": str(model).strip(),
            "android_version": str(android_ver).strip(),
            "screen_size": str(screen_size).strip(),
            "battery": str(battery).strip(),
        }

    async def _handle_scroll(self, device_id: str, params: Dict) -> Dict:
        """处理滚动操作"""
        direction = params.get("direction", "down")
        amount = params.get("amount", 500)
        screen_w, screen_h = 540, 960  # 默认值
        cx, cy = screen_w // 2, screen_h // 2
        scroll_map = {
            "down": (cx, cy + amount // 2, cx, cy - amount // 2),
            "up": (cx, cy - amount // 2, cx, cy + amount // 2),
            "left": (cx + amount // 2, cy, cx - amount // 2, cy),
            "right": (cx - amount // 2, cy, cx + amount // 2, cy),
        }
        x1, y1, x2, y2 = scroll_map.get(direction, scroll_map["down"])
        await self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} 300", device_id)
        return {"status": "success", "action": "scroll", "direction": direction}

    async def _handle_long_press(self, device_id: str, params: Dict) -> Dict:
        """处理长按操作"""
        x, y = params.get("x", 0), params.get("y", 0)
        duration = params.get("duration", 1000)
        await self.adb.shell(f"input swipe {x} {y} {x} {y} {duration}", device_id)
        return {"status": "success", "action": "long_press", "x": x, "y": y, "duration": duration}

    async def _handle_back(self, device_id: str, params: Dict) -> Dict:
        """处理返回键"""
        await self.adb.shell("input keyevent 4", device_id)
        return {"status": "success", "action": "back"}

    async def _handle_home(self, device_id: str, params: Dict) -> Dict:
        """处理Home键"""
        await self.adb.shell("input keyevent 3", device_id)
        return {"status": "success", "action": "home"}

    async def _handle_recent_apps(self, device_id: str, params: Dict) -> Dict:
        """处理最近应用"""
        await self.adb.shell("input keyevent 187", device_id)
        return {"status": "success", "action": "recent_apps"}

    async def _handle_wake_screen(self, device_id: str, params: Dict) -> Dict:
        """唤醒屏幕"""
        await self.adb.shell("input keyevent 224", device_id)
        return {"status": "success", "action": "wake_screen"}

    async def _handle_lock_screen(self, device_id: str, params: Dict) -> Dict:
        """锁定屏幕"""
        await self.adb.shell("input keyevent 223", device_id)
        return {"status": "success", "action": "lock_screen"}

    async def _handle_volume_up(self, device_id: str, params: Dict) -> Dict:
        """音量增加"""
        await self.adb.shell("input keyevent 24", device_id)
        return {"status": "success", "action": "volume_up"}

    async def _handle_volume_down(self, device_id: str, params: Dict) -> Dict:
        """音量减少"""
        await self.adb.shell("input keyevent 25", device_id)
        return {"status": "success", "action": "volume_down"}

    async def _handle_set_clipboard(self, device_id: str, params: Dict) -> Dict:
        """设置剪贴板"""
        content = params.get("content", "")
        # Android 10+ 可用 service call clipboard
        await self.adb.shell(f"am broadcast -a clipper.set -e text '{content}'", device_id)
        return {"status": "success", "action": "set_clipboard", "content_length": len(content)}

    async def _handle_get_clipboard(self, device_id: str, params: Dict) -> Dict:
        """获取剪贴板"""
        result = await self.adb.shell("am broadcast -a clipper.get", device_id)
        return {"status": "success", "action": "get_clipboard", "clipboard": str(result).strip()}

    # ========================= GUI扩展处理 =========================

    async def _handle_gui_click(self, device_id: str, data: Dict) -> Dict:
        """处理GUI点击扩展消息"""
        return await self._handle_click(device_id, data)

    async def _handle_gui_swipe(self, device_id: str, data: Dict) -> Dict:
        """处理GUI滑动扩展消息"""
        return await self._handle_swipe(device_id, data)

    async def _handle_gui_input(self, device_id: str, data: Dict) -> Dict:
        """处理GUI输入扩展消息"""
        return await self._handle_type(device_id, data)

    async def _handle_element_query(self, device_id: str, data: Dict) -> Dict:
        """处理元素查询"""
        query = data.get("query", "")
        query_type = data.get("query_type", "text")
        # 使用 uiautomator dump 获取UI树
        await self.adb.shell("uiautomator dump /sdcard/ui_dump.xml", device_id)
        result = await self.adb.shell("cat /sdcard/ui_dump.xml", device_id)
        # 简单的文本搜索
        found = query.lower() in str(result).lower() if result else False
        return {
            "status": "success",
            "action": "element_query",
            "query": query,
            "query_type": query_type,
            "found": found,
        }

    # ========================= 辅助方法 =========================

    def _success_response(self, original: AIPMessage, result: Dict) -> AIPMessage:
        """创建成功响应 (v3 AIPMessage)"""
        return AIPMessage(
            type=MessageType.COMMAND_RESULT,
            device_id=original.device_id,
            payload={"success": True, **result},
            correlation_id=original.message_id,
        )

    def _error_response(self, original: AIPMessage, error: str) -> AIPMessage:
        """创建错误响应 (v3 AIPMessage)"""
        return AIPMessage(
            type=MessageType.ERROR,
            device_id=original.device_id,
            payload={"success": False, "error": error},
            correlation_id=original.message_id,
        )

    def get_supported_commands(self) -> List[str]:
        """返回所有支持的命令列表"""
        return list(self._command_handlers.keys())
