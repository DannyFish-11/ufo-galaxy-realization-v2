"""
UFO Galaxy 状态机与UI集成模块
实现硬件触发 → UI 和 UI状态 → 硬件触发 的双向集成
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

# 导入事件总线
import sys
sys.path.insert(0, '/mnt/okcomputer/output/ufo_galaxy_integration')
from integration.event_bus import (
    EventBus, EventType, UIGalaxyEvent, event_bus
)


class SystemState(Enum):
    """系统状态枚举"""
    SLEEPING = "sleeping"           # 休眠状态
    WAKING = "waking"               # 唤醒中
    ISLAND = "island"               # 灵动岛状态
    SIDESHEET = "sidesheet"         # 侧边栏状态
    FULLSCREEN = "fullscreen"       # 全屏状态
    EXECUTING = "executing"         # 执行中
    ERROR = "error"                 # 错误状态


class TriggerType(Enum):
    """触发类型枚举"""
    HARDWARE_BUTTON = "hardware_button"     # 硬件按键
    GESTURE = "gesture"                      # 手势
    VOICE = "voice"                          # 语音
    SCHEDULED = "scheduled"                  # 定时
    REMOTE = "remote"                        # 远程触发


@dataclass
class StateTransition:
    """状态转换记录"""
    from_state: SystemState
    to_state: SystemState
    trigger_type: TriggerType
    trigger_source: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnimationState:
    """动画状态"""
    animation_id: str
    animation_type: str
    state: str  # "started", "running", "completed", "error"
    progress: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SystemStateMachine:
    """
    UFO Galaxy 系统状态机
    管理UI状态和硬件触发的集成
    """
    
    _instance: Optional['SystemStateMachine'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # 当前状态
        self._current_state = SystemState.SLEEPING
        
        # 状态转换历史
        self._transition_history: List[StateTransition] = []
        self._max_history = 1000
        
        # 动画状态
        self._animations: Dict[str, AnimationState] = {}
        
        # 状态监听器
        self._state_listeners: Dict[SystemState, Set[Callable]] = {
            state: set() for state in SystemState
        }
        
        # 状态进入/退出回调
        self._on_state_enter: Dict[SystemState, List[Callable]] = {
            state: [] for state in SystemState
        }
        self._on_state_exit: Dict[SystemState, List[Callable]] = {
            state: [] for state in SystemState
        }
        
        # 统计信息
        self._state_statistics: Dict[SystemState, int] = {
            state: 0 for state in SystemState
        }
        
        # 日志
        self._logger = logging.getLogger("SystemStateMachine")
        
        self._logger.info("系统状态机已初始化")
    
    @property
    def current_state(self) -> SystemState:
        """获取当前状态"""
        return self._current_state
    
    def transition_to(self, new_state: SystemState, 
                      trigger_type: TriggerType = TriggerType.SCHEDULED,
                      trigger_source: str = "system",
                      metadata: Dict[str, Any] = None) -> bool:
        """
        转换到新状态
        
        Args:
            new_state: 目标状态
            trigger_type: 触发类型
            trigger_source: 触发来源
            metadata: 附加元数据
            
        Returns:
            是否成功转换
        """
        if new_state == self._current_state:
            return False
        
        old_state = self._current_state
        
        # 记录转换
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            trigger_type=trigger_type,
            trigger_source=trigger_source,
            metadata=metadata or {}
        )
        self._transition_history.append(transition)
        self._state_statistics[new_state] += 1
        
        # 限制历史记录大小
        if len(self._transition_history) > self._max_history:
            self._transition_history = self._transition_history[-self._max_history:]
        
        # 执行退出回调
        self._execute_state_exit_callbacks(old_state)
        
        # 更新状态
        self._current_state = new_state
        
        # 执行进入回调
        self._execute_state_enter_callbacks(new_state)
        
        # 发布状态转换事件
        event_bus.publish_sync(
            EventType.STATE_TRANSITION,
            "state_machine",
            {
                "from_state": old_state.value,
                "to_state": new_state.value,
                "trigger_type": trigger_type.value,
                "trigger_source": trigger_source
            }
        )
        
        self._logger.info(f"状态转换: {old_state.value} -> {new_state.value} "
                         f"(触发: {trigger_type.value})")
        
        return True
    
    def _execute_state_enter_callbacks(self, state: SystemState):
        """执行状态进入回调"""
        for callback in self._on_state_enter.get(state, []):
            try:
                callback(state)
            except Exception as e:
                self._logger.error(f"状态进入回调错误: {e}")
    
    def _execute_state_exit_callbacks(self, state: SystemState):
        """执行状态退出回调"""
        for callback in self._on_state_exit.get(state, []):
            try:
                callback(state)
            except Exception as e:
                self._logger.error(f"状态退出回调错误: {e}")
    
    def register_state_enter_callback(self, state: SystemState, callback: Callable):
        """注册状态进入回调"""
        self._on_state_enter[state].append(callback)
    
    def register_state_exit_callback(self, state: SystemState, callback: Callable):
        """注册状态退出回调"""
        self._on_state_exit[state].append(callback)
    
    def wakeup(self, trigger_type: TriggerType = TriggerType.HARDWARE_BUTTON,
               trigger_source: str = "hardware") -> bool:
        """
        唤醒系统（硬件触发 → UI 集成点）
        
        Args:
            trigger_type: 触发类型
            trigger_source: 触发来源
            
        Returns:
            是否成功唤醒
        """
        if self._current_state != SystemState.SLEEPING:
            self._logger.warning(f"系统不在休眠状态，当前状态: {self._current_state.value}")
            return False
        
        # 发布硬件触发事件
        event_bus.publish_sync(
            EventType.HARDWARE_TRIGGER_DETECTED,
            trigger_source,
            {
                "trigger_type": trigger_type.value,
                "action": "wakeup"
            }
        )
        
        # 发布唤醒信号事件
        event_bus.publish_sync(
            EventType.WAKEUP_SIGNAL,
            trigger_source,
            {
                "trigger_type": trigger_type.value
            }
        )
        
        # 转换到灵动岛状态
        success = self.transition_to(
            SystemState.ISLAND,
            trigger_type=trigger_type,
            trigger_source=trigger_source
        )
        
        if success:
            self._logger.info(f"系统被唤醒 (触发: {trigger_type.value})")
        
        return success
    
    def sleep(self):
        """使系统进入休眠状态"""
        self.transition_to(
            SystemState.SLEEPING,
            trigger_type=TriggerType.SCHEDULED,
            trigger_source="system"
        )
    
    def expand_to_sidesheet(self):
        """展开到侧边栏状态"""
        if self._current_state == SystemState.ISLAND:
            self.transition_to(
                SystemState.SIDESHEET,
                trigger_type=TriggerType.GESTURE,
                trigger_source="user"
            )
    
    def expand_to_fullscreen(self):
        """展开到全屏状态"""
        if self._current_state in [SystemState.ISLAND, SystemState.SIDESHEET]:
            self.transition_to(
                SystemState.FULLSCREEN,
                trigger_type=TriggerType.GESTURE,
                trigger_source="user"
            )
    
    def collapse_to_island(self):
        """折叠到灵动岛状态"""
        if self._current_state in [SystemState.SIDESHEET, SystemState.FULLSCREEN]:
            self.transition_to(
                SystemState.ISLAND,
                trigger_type=TriggerType.GESTURE,
                trigger_source="user"
            )
    
    # ==================== 动画状态管理 ====================
    
    def start_animation(self, animation_id: str, animation_type: str):
        """
        开始动画（UI状态 → 硬件触发 集成点）
        
        Args:
            animation_id: 动画ID
            animation_type: 动画类型
        """
        animation = AnimationState(
            animation_id=animation_id,
            animation_type=animation_type,
            state="started",
            started_at=datetime.now()
        )
        self._animations[animation_id] = animation
        
        # 发布动画开始事件
        event_bus.publish_sync(
            EventType.ANIMATION_STARTED,
            "ui",
            {
                "animation_id": animation_id,
                "animation_type": animation_type
            }
        )
        
        self._logger.debug(f"动画开始: {animation_id} ({animation_type})")
    
    def update_animation_progress(self, animation_id: str, progress: float):
        """更新动画进度"""
        if animation_id in self._animations:
            self._animations[animation_id].progress = progress
            self._animations[animation_id].state = "running"
    
    def complete_animation(self, animation_id: str, success: bool = True):
        """
        完成动画（UI状态 → 硬件触发 集成点）
        
        Args:
            animation_id: 动画ID
            success: 是否成功完成
        """
        if animation_id in self._animations:
            animation = self._animations[animation_id]
            animation.state = "completed" if success else "error"
            animation.completed_at = datetime.now()
            
            # 发布动画完成事件
            event_bus.publish_sync(
                EventType.ANIMATION_COMPLETED,
                "ui",
                {
                    "animation_id": animation_id,
                    "animation_type": animation.animation_type,
                    "success": success,
                    "duration": (animation.completed_at - animation.started_at).total_seconds() 
                               if animation.started_at else 0
                }
            )
            
            # 记录转换历史
            self._record_animation_transition(animation)
            
            self._logger.debug(f"动画完成: {animation_id} (成功: {success})")
    
    def _record_animation_transition(self, animation: AnimationState):
        """记录动画转换到状态历史"""
        # 根据动画类型记录相应的状态转换
        if animation.animation_type == "island_appear":
            self._logger.info("记录: 灵动岛出现动画完成")
        elif animation.animation_type == "sidesheet_expand":
            self._logger.info("记录: 侧边栏展开动画完成")
        elif animation.animation_type == "fullscreen_expand":
            self._logger.info("记录: 全屏展开动画完成")
    
    def get_animation_state(self, animation_id: str) -> Optional[AnimationState]:
        """获取动画状态"""
        return self._animations.get(animation_id)
    
    # ==================== 统计和查询 ====================
    
    def get_transition_history(self, limit: int = 100) -> List[StateTransition]:
        """获取状态转换历史"""
        return self._transition_history[-limit:]
    
    def get_state_statistics(self) -> Dict[SystemState, int]:
        """获取状态统计信息"""
        return self._state_statistics.copy()
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态机状态"""
        return {
            "current_state": self._current_state.value,
            "transition_count": len(self._transition_history),
            "statistics": {k.value: v for k, v in self._state_statistics.items()},
            "active_animations": len([a for a in self._animations.values() 
                                     if a.state in ["started", "running"]])
        }


class HardwareTriggerManager:
    """
    硬件触发管理器
    管理硬件事件（按键、手势等）与状态机的集成
    """
    
    def __init__(self):
        self.state_machine = SystemStateMachine()
        self._logger = logging.getLogger("HardwareTriggerManager")
        
        # 触发器监听器
        self._trigger_listeners: Dict[TriggerType, Set[Callable]] = {
            trigger_type: set() for trigger_type in TriggerType
        }
        
        # 注册UI回调
        self._register_ui_callbacks()
    
    def _register_ui_callbacks(self):
        """注册UI回调（硬件触发 → UI 集成点）"""
        # 当进入ISLAND状态时，通知UI播放灵动岛出现动画
        self.state_machine.register_state_enter_callback(
            SystemState.ISLAND,
            self._on_island_enter
        )
        
        # 当进入SIDESHEET状态时，通知UI展开侧边栏
        self.state_machine.register_state_enter_callback(
            SystemState.SIDESHEET,
            self._on_sidesheet_enter
        )
        
        # 当进入FULLSCREEN状态时，通知UI展开全屏
        self.state_machine.register_state_enter_callback(
            SystemState.FULLSCREEN,
            self._on_fullscreen_enter
        )
    
    def _on_island_enter(self, state: SystemState):
        """灵动岛状态进入回调"""
        self._logger.info("进入灵动岛状态，通知UI播放动画")
        
        # 发布事件通知UI
        event_bus.publish_sync(
            EventType.UI_STATE_CHANGED,
            "state_machine",
            {
                "state": state.value,
                "action": "play_animation",
                "animation_type": "island_appear"
            }
        )
    
    def _on_sidesheet_enter(self, state: SystemState):
        """侧边栏状态进入回调"""
        self._logger.info("进入侧边栏状态，通知UI展开")
        
        event_bus.publish_sync(
            EventType.UI_STATE_CHANGED,
            "state_machine",
            {
                "state": state.value,
                "action": "play_animation",
                "animation_type": "sidesheet_expand"
            }
        )
    
    def _on_fullscreen_enter(self, state: SystemState):
        """全屏状态进入回调"""
        self._logger.info("进入全屏状态，通知UI展开")
        
        event_bus.publish_sync(
            EventType.UI_STATE_CHANGED,
            "state_machine",
            {
                "state": state.value,
                "action": "play_animation",
                "animation_type": "fullscreen_expand"
            }
        )
    
    def register_trigger_listener(self, trigger_type: TriggerType, callback: Callable):
        """注册触发器监听器"""
        self._trigger_listeners[trigger_type].add(callback)
    
    def on_hardware_button_pressed(self, button_id: str):
        """
        硬件按键按下处理（硬件触发 → UI 集成点）
        
        Args:
            button_id: 按键ID
        """
        self._logger.info(f"硬件按键按下: {button_id}")
        
        # 通知监听器
        for callback in self._trigger_listeners[TriggerType.HARDWARE_BUTTON]:
            try:
                callback(button_id)
            except Exception as e:
                self._logger.error(f"触发器回调错误: {e}")
        
        # 触发状态机唤醒
        if button_id == "power" or button_id == "assistant":
            self.state_machine.wakeup(
                trigger_type=TriggerType.HARDWARE_BUTTON,
                trigger_source=f"button_{button_id}"
            )
    
    def on_gesture_detected(self, gesture_type: str):
        """
        手势检测处理（硬件触发 → UI 集成点）
        
        Args:
            gesture_type: 手势类型
        """
        self._logger.info(f"手势检测: {gesture_type}")
        
        # 通知监听器
        for callback in self._trigger_listeners[TriggerType.GESTURE]:
            try:
                callback(gesture_type)
            except Exception as e:
                self._logger.error(f"手势回调错误: {e}")
        
        # 根据手势类型转换状态
        if gesture_type == "swipe_up":
            self.state_machine.expand_to_sidesheet()
        elif gesture_type == "swipe_down":
            self.state_machine.collapse_to_island()
        elif gesture_type == "double_tap":
            self.state_machine.expand_to_fullscreen()
    
    def on_voice_command(self, command: str):
        """
        语音命令处理（硬件触发 → UI 集成点）
        
        Args:
            command: 语音命令
        """
        self._logger.info(f"语音命令: {command}")
        
        # 通知监听器
        for callback in self._trigger_listeners[TriggerType.VOICE]:
            try:
                callback(command)
            except Exception as e:
                self._logger.error(f"语音回调错误: {e}")
        
        # 如果系统在休眠，先唤醒
        if self.state_machine.current_state == SystemState.SLEEPING:
            self.state_machine.wakeup(
                trigger_type=TriggerType.VOICE,
                trigger_source="voice_command"
            )


# 全局实例
state_machine = SystemStateMachine()
hardware_trigger_manager = HardwareTriggerManager()


# ==================== 便捷函数 ====================

def wakeup_system(trigger_source: str = "hardware") -> bool:
    """唤醒系统"""
    return state_machine.wakeup(
        trigger_type=TriggerType.HARDWARE_BUTTON,
        trigger_source=trigger_source
    )


def on_ui_animation_completed(animation_id: str, animation_type: str, success: bool = True):
    """
    UI动画完成回调（UI状态 → 硬件触发 集成点）
    
    由UI组件调用，通知状态机动画已完成
    
    Args:
        animation_id: 动画ID
        animation_type: 动画类型
        success: 是否成功完成
    """
    state_machine.complete_animation(animation_id, success)
    
    # 更新状态统计
    logging.getLogger("UIIntegration").info(
        f"UI动画完成: {animation_type} (成功: {success})"
    )


def register_ui_state_callback(state: SystemState, callback: Callable):
    """注册UI状态回调"""
    state_machine.register_state_enter_callback(state, callback)
