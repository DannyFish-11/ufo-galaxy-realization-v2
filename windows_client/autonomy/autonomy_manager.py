"""
Windows 自主操纵管理器

整合 UI Automation 和输入模拟，提供高级自动化功能
"""

import logging
import json
from typing import Dict, Any, List, Optional
from .ui_automation import UIAutomationWrapper, UIElement
from .input_simulator import InputSimulator

logger = logging.getLogger(__name__)


class WindowsAutonomyManager:
    """Windows 自主操纵管理器"""
    
    def __init__(self):
        """初始化管理器"""
        try:
            self.uia = UIAutomationWrapper()
            self.simulator = InputSimulator()
            logger.info("Windows 自主操纵管理器初始化成功")
        except Exception as e:
            logger.error(f"Windows 自主操纵管理器初始化失败: {e}")
            raise
    
    def get_screen_state(self) -> Dict[str, Any]:
        """
        获取当前屏幕状态
        
        Returns:
            Dict: 屏幕状态，包含前台窗口的 UI 树
        """
        try:
            tree = self.uia.get_foreground_window_tree(max_depth=5)
            if tree:
                return {
                    'success': True,
                    'window_name': tree.name,
                    'ui_tree': tree.to_dict()
                }
            else:
                return {
                    'success': False,
                    'error': '没有找到前台窗口'
                }
        except Exception as e:
            logger.error(f"获取屏幕状态失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行操作
        
        Args:
            action: 操作描述，格式:
                {
                    'type': 'click' | 'type' | 'press_key' | 'find_and_click' | ...,
                    'params': {...}
                }
        
        Returns:
            Dict: 执行结果
        """
        try:
            action_type = action.get('type')
            params = action.get('params', {})
            
            if action_type == 'click':
                return self._action_click(params)
            elif action_type == 'type':
                return self._action_type(params)
            elif action_type == 'press_key':
                return self._action_press_key(params)
            elif action_type == 'press_keys':
                return self._action_press_keys(params)
            elif action_type == 'find_and_click':
                return self._action_find_and_click(params)
            elif action_type == 'find_and_type':
                return self._action_find_and_type(params)
            elif action_type == 'scroll':
                return self._action_scroll(params)
            else:
                return {
                    'success': False,
                    'error': f'不支持的操作类型: {action_type}'
                }
        except Exception as e:
            logger.error(f"执行操作失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行任务（包含多个操作）
        
        Args:
            task: 任务描述，格式:
                {
                    'name': '任务名称',
                    'actions': [action1, action2, ...]
                }
        
        Returns:
            Dict: 执行结果
        """
        try:
            task_name = task.get('name', 'Unknown Task')
            actions = task.get('actions', [])
            
            logger.info(f"开始执行任务: {task_name}")
            
            results = []
            for i, action in enumerate(actions):
                logger.info(f"执行操作 {i+1}/{len(actions)}: {action.get('type')}")
                result = self.execute_action(action)
                results.append(result)
                
                if not result.get('success'):
                    logger.error(f"操作 {i+1} 失败: {result.get('error')}")
                    return {
                        'success': False,
                        'error': f'操作 {i+1} 失败',
                        'failed_action': action,
                        'results': results
                    }
            
            logger.info(f"任务执行成功: {task_name}")
            return {
                'success': True,
                'results': results
            }
        except Exception as e:
            logger.error(f"执行任务失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _action_click(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行点击操作"""
        x = params.get('x')
        y = params.get('y')
        button = params.get('button', 'left')
        double = params.get('double', False)
        
        success = self.simulator.click(x, y, button, double)
        return {
            'success': success,
            'action': 'click',
            'params': params
        }
    
    def _action_type(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行输入操作"""
        text = params.get('text', '')
        interval = params.get('interval', 0.05)
        
        success = self.simulator.type_text(text, interval)
        return {
            'success': success,
            'action': 'type',
            'params': params
        }
    
    def _action_press_key(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行按键操作"""
        key = params.get('key', '')
        
        success = self.simulator.press_key(key)
        return {
            'success': success,
            'action': 'press_key',
            'params': params
        }
    
    def _action_press_keys(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行组合键操作"""
        keys = params.get('keys', [])
        
        success = self.simulator.press_keys(keys)
        return {
            'success': success,
            'action': 'press_keys',
            'params': params
        }
    
    def _action_find_and_click(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """查找元素并点击"""
        name = params.get('name')
        automation_id = params.get('automation_id')
        
        # 查找元素
        if name:
            element = self.uia.find_element_by_name(name)
        elif automation_id:
            element = self.uia.find_element_by_automation_id(automation_id)
        else:
            return {
                'success': False,
                'error': '必须提供 name 或 automation_id',
                'action': 'find_and_click',
                'params': params
            }
        
        if not element:
            return {
                'success': False,
                'error': '未找到元素',
                'action': 'find_and_click',
                'params': params
            }
        
        # 点击元素
        success = self.uia.click_element(element)
        return {
            'success': success,
            'action': 'find_and_click',
            'params': params
        }
    
    def _action_find_and_type(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """查找元素并输入文本"""
        name = params.get('name')
        automation_id = params.get('automation_id')
        text = params.get('text', '')
        
        # 查找元素
        if name:
            element = self.uia.find_element_by_name(name)
        elif automation_id:
            element = self.uia.find_element_by_automation_id(automation_id)
        else:
            return {
                'success': False,
                'error': '必须提供 name 或 automation_id',
                'action': 'find_and_type',
                'params': params
            }
        
        if not element:
            return {
                'success': False,
                'error': '未找到元素',
                'action': 'find_and_type',
                'params': params
            }
        
        # 设置值
        success = self.uia.set_value(element, text)
        return {
            'success': success,
            'action': 'find_and_type',
            'params': params
        }
    
    def _action_scroll(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行滚动操作"""
        amount = params.get('amount', 120)
        
        success = self.simulator.scroll(amount)
        return {
            'success': success,
            'action': 'scroll',
            'params': params
        }


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    try:
        manager = WindowsAutonomyManager()
        
        # 测试获取屏幕状态
        print("获取屏幕状态...")
        state = manager.get_screen_state()
        print(f"成功: {state['success']}")
        if state['success']:
            print(f"窗口名称: {state['window_name']}")
        
        # 测试执行简单任务
        print("\n执行测试任务...")
        task = {
            'name': '测试任务',
            'actions': [
                {
                    'type': 'press_keys',
                    'params': {'keys': ['win', 'r']}
                },
                {
                    'type': 'type',
                    'params': {'text': 'notepad'}
                },
                {
                    'type': 'press_key',
                    'params': {'key': 'enter'}
                }
            ]
        }
        
        result = manager.execute_task(task)
        print(f"任务执行结果: {result['success']}")
    
    except Exception as e:
        print(f"测试失败: {e}")
