"""
Windows UI Automation 封装模块

使用 Windows UI Automation API 实现屏幕元素识别和操作
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import comtypes.client
from comtypes import COMError

logger = logging.getLogger(__name__)


@dataclass
class UIElement:
    """UI 元素数据类"""
    automation_id: str
    name: str
    class_name: str
    control_type: str
    bounding_rect: Dict[str, int]
    is_enabled: bool
    is_offscreen: bool
    value: Optional[str] = None
    children: List['UIElement'] = None
    
    def __post_init__(self):
        if self.children is None:
            self.children = []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'automation_id': self.automation_id,
            'name': self.name,
            'class_name': self.class_name,
            'control_type': self.control_type,
            'bounding_rect': self.bounding_rect,
            'is_enabled': self.is_enabled,
            'is_offscreen': self.is_offscreen,
            'value': self.value,
            'children': [child.to_dict() for child in self.children]
        }


class UIAutomationWrapper:
    """Windows UI Automation 包装类"""
    
    def __init__(self):
        """初始化 UI Automation"""
        try:
            self.uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=comtypes.gen.UIAutomationClient.IUIAutomation
            )
            self.root = self.uia.GetRootElement()
            logger.info("UI Automation 初始化成功")
        except Exception as e:
            logger.error(f"UI Automation 初始化失败: {e}")
            raise
    
    def get_desktop_tree(self, max_depth: int = 3) -> UIElement:
        """
        获取桌面 UI 树
        
        Args:
            max_depth: 最大遍历深度
            
        Returns:
            UIElement: 桌面 UI 树根节点
        """
        try:
            return self._build_element_tree(self.root, max_depth)
        except Exception as e:
            logger.error(f"获取桌面 UI 树失败: {e}")
            raise
    
    def get_foreground_window_tree(self, max_depth: int = 5) -> Optional[UIElement]:
        """
        获取前台窗口的 UI 树
        
        Args:
            max_depth: 最大遍历深度
            
        Returns:
            UIElement: 前台窗口 UI 树，如果没有前台窗口则返回 None
        """
        try:
            # 获取前台窗口
            foreground = self.uia.GetFocusedElement()
            if not foreground:
                logger.warning("没有找到前台窗口")
                return None
            
            # 向上遍历找到顶层窗口
            window = foreground
            while window:
                try:
                    parent = self._get_parent(window)
                    if not parent or parent == self.root:
                        break
                    window = parent
                except (COMError, OSError):
                    break
            
            return self._build_element_tree(window, max_depth)
        except Exception as e:
            logger.error(f"获取前台窗口 UI 树失败: {e}")
            return None
    
    def find_element_by_name(self, name: str, root: Any = None) -> Optional[Any]:
        """
        根据名称查找元素
        
        Args:
            name: 元素名称
            root: 搜索根节点，默认为桌面
            
        Returns:
            找到的元素，如果没找到则返回 None
        """
        try:
            if root is None:
                root = self.root
            
            condition = self.uia.CreatePropertyCondition(
                comtypes.gen.UIAutomationClient.UIA_NamePropertyId,
                name
            )
            element = root.FindFirst(
                comtypes.gen.UIAutomationClient.TreeScope_Descendants,
                condition
            )
            return element
        except Exception as e:
            logger.error(f"查找元素失败: {e}")
            return None
    
    def find_element_by_automation_id(self, automation_id: str, root: Any = None) -> Optional[Any]:
        """
        根据 Automation ID 查找元素
        
        Args:
            automation_id: Automation ID
            root: 搜索根节点，默认为桌面
            
        Returns:
            找到的元素，如果没找到则返回 None
        """
        try:
            if root is None:
                root = self.root
            
            condition = self.uia.CreatePropertyCondition(
                comtypes.gen.UIAutomationClient.UIA_AutomationIdPropertyId,
                automation_id
            )
            element = root.FindFirst(
                comtypes.gen.UIAutomationClient.TreeScope_Descendants,
                condition
            )
            return element
        except Exception as e:
            logger.error(f"查找元素失败: {e}")
            return None
    
    def click_element(self, element: Any) -> bool:
        """
        点击元素
        
        Args:
            element: UI 元素
            
        Returns:
            bool: 是否成功
        """
        try:
            # 尝试使用 Invoke Pattern
            invoke_pattern = element.GetCurrentPattern(
                comtypes.gen.UIAutomationClient.UIA_InvokePatternId
            )
            if invoke_pattern:
                invoke_pattern.Invoke()
                logger.info(f"点击元素成功: {self._get_element_name(element)}")
                return True
            
            # 如果没有 Invoke Pattern，尝试使用鼠标点击
            rect = element.CurrentBoundingRectangle
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2
            
            import win32api
            import win32con
            win32api.SetCursorPos((center_x, center_y))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            
            logger.info(f"点击元素成功 (鼠标): {self._get_element_name(element)}")
            return True
        except Exception as e:
            logger.error(f"点击元素失败: {e}")
            return False
    
    def set_value(self, element: Any, value: str) -> bool:
        """
        设置元素的值（用于输入框等）
        
        Args:
            element: UI 元素
            value: 要设置的值
            
        Returns:
            bool: 是否成功
        """
        try:
            value_pattern = element.GetCurrentPattern(
                comtypes.gen.UIAutomationClient.UIA_ValuePatternId
            )
            if value_pattern:
                value_pattern.SetValue(value)
                logger.info(f"设置元素值成功: {self._get_element_name(element)} = {value}")
                return True
            else:
                logger.warning(f"元素不支持 Value Pattern: {self._get_element_name(element)}")
                return False
        except Exception as e:
            logger.error(f"设置元素值失败: {e}")
            return False
    
    def get_value(self, element: Any) -> Optional[str]:
        """
        获取元素的值
        
        Args:
            element: UI 元素
            
        Returns:
            str: 元素的值，如果获取失败则返回 None
        """
        try:
            value_pattern = element.GetCurrentPattern(
                comtypes.gen.UIAutomationClient.UIA_ValuePatternId
            )
            if value_pattern:
                return value_pattern.CurrentValue
            return None
        except Exception as e:
            logger.error(f"获取元素值失败: {e}")
            return None
    
    def _build_element_tree(self, element: Any, max_depth: int, current_depth: int = 0) -> UIElement:
        """
        递归构建元素树
        
        Args:
            element: UI 元素
            max_depth: 最大深度
            current_depth: 当前深度
            
        Returns:
            UIElement: 元素树节点
        """
        try:
            # 获取元素属性
            automation_id = self._get_property(element, comtypes.gen.UIAutomationClient.UIA_AutomationIdPropertyId, "")
            name = self._get_element_name(element)
            class_name = self._get_property(element, comtypes.gen.UIAutomationClient.UIA_ClassNamePropertyId, "")
            control_type = self._get_control_type_name(element)
            
            rect = element.CurrentBoundingRectangle
            bounding_rect = {
                'left': rect.left,
                'top': rect.top,
                'right': rect.right,
                'bottom': rect.bottom,
                'width': rect.right - rect.left,
                'height': rect.bottom - rect.top
            }
            
            is_enabled = element.CurrentIsEnabled
            is_offscreen = element.CurrentIsOffscreen
            
            # 尝试获取值
            value = self.get_value(element)
            
            # 创建 UI 元素
            ui_element = UIElement(
                automation_id=automation_id,
                name=name,
                class_name=class_name,
                control_type=control_type,
                bounding_rect=bounding_rect,
                is_enabled=is_enabled,
                is_offscreen=is_offscreen,
                value=value,
                children=[]
            )
            
            # 如果还没有达到最大深度，递归获取子元素
            if current_depth < max_depth:
                try:
                    walker = self.uia.ControlViewWalker
                    child = walker.GetFirstChildElement(element)
                    while child:
                        try:
                            child_element = self._build_element_tree(child, max_depth, current_depth + 1)
                            ui_element.children.append(child_element)
                        except (COMError, OSError, Exception):
                            pass
                        try:
                            child = walker.GetNextSiblingElement(child)
                        except (COMError, OSError):
                            break
                except (COMError, OSError):
                    pass
            
            return ui_element
        except Exception as e:
            logger.error(f"构建元素树失败: {e}")
            raise
    
    def _get_element_name(self, element: Any) -> str:
        """获取元素名称"""
        try:
            return element.CurrentName or ""
        except (COMError, OSError):
            return ""
    
    def _get_property(self, element: Any, property_id: int, default: Any = None) -> Any:
        """获取元素属性"""
        try:
            return element.GetCurrentPropertyValue(property_id)
        except (COMError, OSError):
            return default
    
    def _get_control_type_name(self, element: Any) -> str:
        """获取控件类型名称"""
        try:
            control_type_id = element.CurrentControlType
            control_type_names = {
                50000: "Button",
                50001: "Calendar",
                50002: "CheckBox",
                50003: "ComboBox",
                50004: "Edit",
                50005: "Hyperlink",
                50006: "Image",
                50007: "ListItem",
                50008: "List",
                50009: "Menu",
                50010: "MenuBar",
                50011: "MenuItem",
                50012: "ProgressBar",
                50013: "RadioButton",
                50014: "ScrollBar",
                50015: "Slider",
                50016: "Spinner",
                50017: "StatusBar",
                50018: "Tab",
                50019: "TabItem",
                50020: "Text",
                50021: "ToolBar",
                50022: "ToolTip",
                50023: "Tree",
                50024: "TreeItem",
                50025: "Custom",
                50026: "Group",
                50027: "Thumb",
                50028: "DataGrid",
                50029: "DataItem",
                50030: "Document",
                50031: "SplitButton",
                50032: "Window",
                50033: "Pane",
                50034: "Header",
                50035: "HeaderItem",
                50036: "Table",
                50037: "TitleBar",
                50038: "Separator"
            }
            return control_type_names.get(control_type_id, f"Unknown({control_type_id})")
        except (COMError, OSError):
            return "Unknown"
    
    def _get_parent(self, element: Any) -> Optional[Any]:
        """获取父元素"""
        try:
            walker = self.uia.ControlViewWalker
            return walker.GetParentElement(element)
        except (COMError, OSError):
            return None


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    try:
        uia = UIAutomationWrapper()
        
        # 获取前台窗口的 UI 树
        print("获取前台窗口 UI 树...")
        tree = uia.get_foreground_window_tree(max_depth=3)
        
        if tree:
            print(f"窗口名称: {tree.name}")
            print(f"子元素数量: {len(tree.children)}")
            
            # 打印前几个子元素
            for i, child in enumerate(tree.children[:5]):
                print(f"  子元素 {i+1}: {child.name} ({child.control_type})")
        else:
            print("没有找到前台窗口")
    
    except Exception as e:
        print(f"测试失败: {e}")
