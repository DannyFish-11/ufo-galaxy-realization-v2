"""
Windows 输入模拟模块

使用 SendInput API 模拟鼠标和键盘操作
"""

import logging
import time
from typing import Tuple, List
import win32api
import win32con
import win32gui
from ctypes import windll, Structure, c_long, c_ulong, sizeof, byref

logger = logging.getLogger(__name__)


# 定义 SendInput 所需的结构体
class MOUSEINPUT(Structure):
    _fields_ = [
        ("dx", c_long),
        ("dy", c_long),
        ("mouseData", c_ulong),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", c_ulong)
    ]


class KEYBDINPUT(Structure):
    _fields_ = [
        ("wVk", c_ulong),
        ("wScan", c_ulong),
        ("dwFlags", c_ulong),
        ("time", c_ulong),
        ("dwExtraInfo", c_ulong)
    ]


class HARDWAREINPUT(Structure):
    _fields_ = [
        ("uMsg", c_ulong),
        ("wParamL", c_ulong),
        ("wParamH", c_ulong)
    ]


class INPUT(Structure):
    class _INPUT(Structure):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT)
        ]
    
    _fields_ = [
        ("type", c_ulong),
        ("union", _INPUT)
    ]


# 常量
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


class InputSimulator:
    """Windows 输入模拟器"""
    
    # 虚拟键码映射
    VK_CODE = {
        'backspace': 0x08,
        'tab': 0x09,
        'enter': 0x0D,
        'shift': 0x10,
        'ctrl': 0x11,
        'alt': 0x12,
        'pause': 0x13,
        'caps_lock': 0x14,
        'esc': 0x1B,
        'space': 0x20,
        'page_up': 0x21,
        'page_down': 0x22,
        'end': 0x23,
        'home': 0x24,
        'left': 0x25,
        'up': 0x26,
        'right': 0x27,
        'down': 0x28,
        'print_screen': 0x2C,
        'insert': 0x2D,
        'delete': 0x2E,
        'win': 0x5B,
        'f1': 0x70,
        'f2': 0x71,
        'f3': 0x72,
        'f4': 0x73,
        'f5': 0x74,
        'f6': 0x75,
        'f7': 0x76,
        'f8': 0x77,
        'f9': 0x78,
        'f10': 0x79,
        'f11': 0x7A,
        'f12': 0x7B,
    }
    
    def __init__(self):
        """初始化输入模拟器"""
        self.user32 = windll.user32
        logger.info("输入模拟器初始化成功")
    
    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        """
        移动鼠标
        
        Args:
            x: X 坐标
            y: Y 坐标
            absolute: 是否使用绝对坐标
            
        Returns:
            bool: 是否成功
        """
        try:
            if absolute:
                # 转换为绝对坐标 (0-65535)
                screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                abs_x = int(x * 65535 / screen_width)
                abs_y = int(y * 65535 / screen_height)
                
                mouse_input = MOUSEINPUT(
                    dx=abs_x,
                    dy=abs_y,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                    time=0,
                    dwExtraInfo=0
                )
            else:
                # 相对移动
                mouse_input = MOUSEINPUT(
                    dx=x,
                    dy=y,
                    mouseData=0,
                    dwFlags=MOUSEEVENTF_MOVE,
                    time=0,
                    dwExtraInfo=0
                )
            
            input_struct = INPUT(type=INPUT_MOUSE)
            input_struct.union.mi = mouse_input
            
            result = self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
            
            if result:
                logger.debug(f"移动鼠标到 ({x}, {y})")
                return True
            else:
                logger.error("移动鼠标失败")
                return False
        except Exception as e:
            logger.error(f"移动鼠标异常: {e}")
            return False
    
    def click(self, x: int = None, y: int = None, button: str = 'left', double: bool = False) -> bool:
        """
        点击鼠标
        
        Args:
            x: X 坐标，如果为 None 则在当前位置点击
            y: Y 坐标
            button: 按钮类型 ('left', 'right', 'middle')
            double: 是否双击
            
        Returns:
            bool: 是否成功
        """
        try:
            # 如果指定了坐标，先移动鼠标
            if x is not None and y is not None:
                self.move_mouse(x, y)
                time.sleep(0.05)  # 短暂延迟
            
            # 确定按钮标志
            if button == 'left':
                down_flag = MOUSEEVENTF_LEFTDOWN
                up_flag = MOUSEEVENTF_LEFTUP
            elif button == 'right':
                down_flag = MOUSEEVENTF_RIGHTDOWN
                up_flag = MOUSEEVENTF_RIGHTUP
            elif button == 'middle':
                down_flag = MOUSEEVENTF_MIDDLEDOWN
                up_flag = MOUSEEVENTF_MIDDLEUP
            else:
                logger.error(f"不支持的按钮类型: {button}")
                return False
            
            # 按下
            self._send_mouse_event(down_flag)
            time.sleep(0.05)
            
            # 释放
            self._send_mouse_event(up_flag)
            
            # 如果是双击，再点击一次
            if double:
                time.sleep(0.05)
                self._send_mouse_event(down_flag)
                time.sleep(0.05)
                self._send_mouse_event(up_flag)
            
            logger.debug(f"点击鼠标 ({button}, double={double})")
            return True
        except Exception as e:
            logger.error(f"点击鼠标异常: {e}")
            return False
    
    def scroll(self, amount: int) -> bool:
        """
        滚动鼠标滚轮
        
        Args:
            amount: 滚动量，正数向上，负数向下
            
        Returns:
            bool: 是否成功
        """
        try:
            mouse_input = MOUSEINPUT(
                dx=0,
                dy=0,
                mouseData=amount,
                dwFlags=MOUSEEVENTF_WHEEL,
                time=0,
                dwExtraInfo=0
            )
            
            input_struct = INPUT(type=INPUT_MOUSE)
            input_struct.union.mi = mouse_input
            
            result = self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
            
            if result:
                logger.debug(f"滚动鼠标滚轮: {amount}")
                return True
            else:
                logger.error("滚动鼠标滚轮失败")
                return False
        except Exception as e:
            logger.error(f"滚动鼠标滚轮异常: {e}")
            return False
    
    def press_key(self, key: str) -> bool:
        """
        按下并释放按键
        
        Args:
            key: 按键名称或字符
            
        Returns:
            bool: 是否成功
        """
        try:
            # 按下
            self._key_down(key)
            time.sleep(0.05)
            
            # 释放
            self._key_up(key)
            
            logger.debug(f"按下按键: {key}")
            return True
        except Exception as e:
            logger.error(f"按下按键异常: {e}")
            return False
    
    def press_keys(self, keys: List[str]) -> bool:
        """
        按下组合键
        
        Args:
            keys: 按键列表，例如 ['ctrl', 'c']
            
        Returns:
            bool: 是否成功
        """
        try:
            # 按下所有键
            for key in keys:
                self._key_down(key)
                time.sleep(0.05)
            
            # 释放所有键（逆序）
            for key in reversed(keys):
                self._key_up(key)
                time.sleep(0.05)
            
            logger.debug(f"按下组合键: {'+'.join(keys)}")
            return True
        except Exception as e:
            logger.error(f"按下组合键异常: {e}")
            return False
    
    def type_text(self, text: str, interval: float = 0.05) -> bool:
        """
        输入文本
        
        Args:
            text: 要输入的文本
            interval: 每个字符之间的间隔（秒）
            
        Returns:
            bool: 是否成功
        """
        try:
            for char in text:
                # 使用 Unicode 输入
                self._type_unicode_char(char)
                time.sleep(interval)
            
            logger.debug(f"输入文本: {text[:20]}...")
            return True
        except Exception as e:
            logger.error(f"输入文本异常: {e}")
            return False
    
    def _send_mouse_event(self, flags: int):
        """发送鼠标事件"""
        mouse_input = MOUSEINPUT(
            dx=0,
            dy=0,
            mouseData=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0
        )
        
        input_struct = INPUT(type=INPUT_MOUSE)
        input_struct.union.mi = mouse_input
        
        self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
    
    def _key_down(self, key: str):
        """按下按键"""
        vk_code = self._get_vk_code(key)
        
        kb_input = KEYBDINPUT(
            wVk=vk_code,
            wScan=0,
            dwFlags=0,
            time=0,
            dwExtraInfo=0
        )
        
        input_struct = INPUT(type=INPUT_KEYBOARD)
        input_struct.union.ki = kb_input
        
        self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
    
    def _key_up(self, key: str):
        """释放按键"""
        vk_code = self._get_vk_code(key)
        
        kb_input = KEYBDINPUT(
            wVk=vk_code,
            wScan=0,
            dwFlags=KEYEVENTF_KEYUP,
            time=0,
            dwExtraInfo=0
        )
        
        input_struct = INPUT(type=INPUT_KEYBOARD)
        input_struct.union.ki = kb_input
        
        self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
    
    def _type_unicode_char(self, char: str):
        """输入 Unicode 字符"""
        # 按下
        kb_input = KEYBDINPUT(
            wVk=0,
            wScan=ord(char),
            dwFlags=KEYEVENTF_UNICODE,
            time=0,
            dwExtraInfo=0
        )
        
        input_struct = INPUT(type=INPUT_KEYBOARD)
        input_struct.union.ki = kb_input
        
        self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
        
        # 释放
        kb_input.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        input_struct.union.ki = kb_input
        
        self.user32.SendInput(1, byref(input_struct), sizeof(INPUT))
    
    def _get_vk_code(self, key: str) -> int:
        """获取虚拟键码"""
        # 如果是特殊键
        if key.lower() in self.VK_CODE:
            return self.VK_CODE[key.lower()]
        
        # 如果是单个字符
        if len(key) == 1:
            return win32api.VkKeyScan(key)
        
        # 默认返回 0
        logger.warning(f"未知的按键: {key}")
        return 0


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    try:
        simulator = InputSimulator()
        
        print("3 秒后开始测试...")
        time.sleep(3)
        
        # 测试鼠标移动和点击
        print("移动鼠标到屏幕中心并点击...")
        screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        simulator.click(screen_width // 2, screen_height // 2)
        
        time.sleep(1)
        
        # 测试键盘输入
        print("输入文本...")
        simulator.type_text("Hello, World!")
        
        time.sleep(1)
        
        # 测试组合键
        print("按下 Ctrl+A...")
        simulator.press_keys(['ctrl', 'a'])
        
        print("测试完成！")
    
    except Exception as e:
        print(f"测试失败: {e}")
