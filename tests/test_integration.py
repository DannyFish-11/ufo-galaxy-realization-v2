"""
UFO Galaxy UI-L4集成测试
测试4个集成点的完整数据流
"""

import asyncio
import unittest
import sys
import time
from typing import List, Dict, Any

sys.path.insert(0, '/mnt/okcomputer/output/ufo_galaxy_integration')

from integration.event_bus import (
    EventBus, EventType, UIGalaxyEvent, 
    ui_progress_callback, event_bus
)
from core.galaxy_main_loop_l4_enhanced import (
    GalaxyMainLoopL4Enhanced, get_galaxy_loop, PendingGoal
)
from system_integration.state_machine_ui_integration import (
    SystemStateMachine, HardwareTriggerManager,
    SystemState, TriggerType, state_machine, hardware_trigger_manager
)


class TestEventBus(unittest.TestCase):
    """测试事件总线"""
    
    def setUp(self):
        self.received_events: List[UIGalaxyEvent] = []
    
    def test_event_creation(self):
        """测试事件创建"""
        event = UIGalaxyEvent(
            event_type=EventType.GOAL_SUBMITTED,
            source="test",
            data={"test": "data"}
        )
        
        self.assertEqual(event.event_type, EventType.GOAL_SUBMITTED)
        self.assertEqual(event.source, "test")
        self.assertEqual(event.data["test"], "data")
    
    def test_event_to_dict(self):
        """测试事件转换为字典"""
        event = UIGalaxyEvent(
            event_type=EventType.GOAL_SUBMITTED,
            source="test",
            data={"goal_id": "123"}
        )
        
        event_dict = event.to_dict()
        self.assertEqual(event_dict["event_type"], "GOAL_SUBMITTED")
        self.assertEqual(event_dict["source"], "test")
        self.assertEqual(event_dict["data"]["goal_id"], "123")
    
    def test_subscribe_and_publish(self):
        """测试订阅和发布"""
        def callback(event: UIGalaxyEvent):
            self.received_events.append(event)
        
        event_bus.subscribe(EventType.GOAL_SUBMITTED, callback)
        
        event = UIGalaxyEvent(
            event_type=EventType.GOAL_SUBMITTED,
            source="test",
            data={"test": "data"}
        )
        
        event_bus.publish(event, async_dispatch=False)
        
        # 等待事件处理
        time.sleep(0.1)
        
        self.assertEqual(len(self.received_events), 1)
        self.assertEqual(self.received_events[0].event_type, EventType.GOAL_SUBMITTED)


class TestL4Integration(unittest.IsolatedAsyncioTestCase):
    """测试L4主循环集成"""
    
    async def asyncSetUp(self):
        await event_bus.start()
        self.galaxy_loop = GalaxyMainLoopL4Enhanced({
            "cycle_interval": 0.1,
            "auto_scan_interval": 300.0
        })
    
    async def asyncTearDown(self):
        await self.galaxy_loop.stop()
        await event_bus.stop()
    
    async def test_receive_goal(self):
        """测试接收目标（UI → L4 集成点）"""
        goal_id = self.galaxy_loop.receive_goal("测试目标")
        
        self.assertIsNotNone(goal_id)
        self.assertIsInstance(goal_id, str)
        self.assertTrue(len(goal_id) > 0)
    
    async def test_get_status(self):
        """测试获取状态"""
        status = self.galaxy_loop.get_status()
        
        self.assertIn("running", status)
        self.assertIn("state", status)
        self.assertIn("cycle_count", status)


class TestStateMachineIntegration(unittest.TestCase):
    """测试状态机集成"""
    
    def setUp(self):
        self.state_machine = SystemStateMachine()
    
    def test_initial_state(self):
        """测试初始状态"""
        self.assertEqual(self.state_machine.current_state, SystemState.SLEEPING)
    
    def test_wakeup(self):
        """测试唤醒（硬件触发 → UI 集成点）"""
        success = self.state_machine.wakeup(
            trigger_type=TriggerType.HARDWARE_BUTTON,
            trigger_source="test_button"
        )
        
        self.assertTrue(success)
        self.assertEqual(self.state_machine.current_state, SystemState.ISLAND)
    
    def test_state_transition(self):
        """测试状态转换"""
        # 唤醒
        self.state_machine.wakeup(TriggerType.HARDWARE_BUTTON, "test")
        self.assertEqual(self.state_machine.current_state, SystemState.ISLAND)
        
        # 展开到侧边栏
        self.state_machine.expand_to_sidesheet()
        self.assertEqual(self.state_machine.current_state, SystemState.SIDESHEET)
        
        # 展开到全屏
        self.state_machine.expand_to_fullscreen()
        self.assertEqual(self.state_machine.current_state, SystemState.FULLSCREEN)
        
        # 折叠到灵动岛
        self.state_machine.collapse_to_island()
        self.assertEqual(self.state_machine.current_state, SystemState.ISLAND)
    
    def test_animation_tracking(self):
        """测试动画跟踪（UI状态 → 硬件触发 集成点）"""
        animation_id = "test_animation_1"
        animation_type = "island_appear"
        
        # 开始动画
        self.state_machine.start_animation(animation_id, animation_type)
        
        anim_state = self.state_machine.get_animation_state(animation_id)
        self.assertIsNotNone(anim_state)
        self.assertEqual(anim_state.animation_type, animation_type)
        self.assertEqual(anim_state.state, "started")
        
        # 完成动画
        self.state_machine.complete_animation(animation_id, True)
        
        anim_state = self.state_machine.get_animation_state(animation_id)
        self.assertEqual(anim_state.state, "completed")
    
    def test_state_callback(self):
        """测试状态回调"""
        callback_called = [False]
        received_state = [None]
        
        def callback(state: SystemState):
            callback_called[0] = True
            received_state[0] = state
        
        self.state_machine.register_state_enter_callback(SystemState.ISLAND, callback)
        
        self.state_machine.wakeup(TriggerType.HARDWARE_BUTTON, "test")
        
        self.assertTrue(callback_called[0])
        self.assertEqual(received_state[0], SystemState.ISLAND)


class TestHardwareTriggerManager(unittest.TestCase):
    """测试硬件触发管理器"""
    
    def setUp(self):
        self.trigger_manager = HardwareTriggerManager()
    
    def test_hardware_button_trigger(self):
        """测试硬件按键触发（硬件触发 → UI 集成点）"""
        self.trigger_manager.on_hardware_button_pressed("assistant")
        
        # 系统应该被唤醒
        self.assertEqual(
            self.trigger_manager.state_machine.current_state,
            SystemState.ISLAND
        )
    
    def test_gesture_trigger(self):
        """测试手势触发"""
        # 先唤醒系统
        self.trigger_manager.state_machine.wakeup(TriggerType.HARDWARE_BUTTON, "test")
        
        # 手势展开
        self.trigger_manager.on_gesture_detected("swipe_up")
        self.assertEqual(
            self.trigger_manager.state_machine.current_state,
            SystemState.SIDESHEET
        )


class TestProgressCallback(unittest.TestCase):
    """测试进度回调（L4 → UI 集成点）"""
    
    def setUp(self):
        self.received_events: List[UIGalaxyEvent] = []
        
        def callback(event: UIGalaxyEvent):
            self.received_events.append(event)
        
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_STARTED, callback)
        event_bus.subscribe(EventType.GOAL_DECOMPOSITION_COMPLETED, callback)
        event_bus.subscribe(EventType.PLAN_GENERATION_STARTED, callback)
        event_bus.subscribe(EventType.PLAN_GENERATION_COMPLETED, callback)
        event_bus.subscribe(EventType.ACTION_EXECUTION_STARTED, callback)
        event_bus.subscribe(EventType.ACTION_EXECUTION_PROGRESS, callback)
        event_bus.subscribe(EventType.ACTION_EXECUTION_COMPLETED, callback)
        event_bus.subscribe(EventType.TASK_COMPLETED, callback)
    
    def test_goal_decomposition_callbacks(self):
        """测试目标分解回调"""
        ui_progress_callback.on_goal_decomposition_started("测试目标")
        ui_progress_callback.on_goal_decomposition_completed(
            "测试目标",
            [{"id": 1, "description": "子任务1"}]
        )
        
        time.sleep(0.1)
        
        # 验证事件被发布
        events = event_bus.get_event_history(EventType.GOAL_DECOMPOSITION_STARTED)
        self.assertTrue(len(events) > 0)
    
    def test_action_execution_callbacks(self):
        """测试动作执行回调"""
        ui_progress_callback.on_action_execution_started("action_1", "test_command")
        ui_progress_callback.on_action_execution_progress("action_1", 0.5, "执行中...")
        ui_progress_callback.on_action_execution_completed(
            "action_1",
            True,
            {"output": "success"}
        )
        
        time.sleep(0.1)
        
        # 验证事件被发布
        events = event_bus.get_event_history(EventType.ACTION_EXECUTION_PROGRESS)
        self.assertTrue(len(events) > 0)


class TestEndToEndFlow(unittest.IsolatedAsyncioTestCase):
    """测试端到端数据流"""
    
    async def asyncSetUp(self):
        await event_bus.start()
        self.galaxy_loop = GalaxyMainLoopL4Enhanced({
            "cycle_interval": 0.1,
            "auto_scan_interval": 300.0
        })
        self.received_events: List[UIGalaxyEvent] = []
        
        # 订阅所有L4事件
        for event_type in [
            EventType.GOAL_SUBMITTED,
            EventType.GOAL_DECOMPOSITION_STARTED,
            EventType.GOAL_DECOMPOSITION_COMPLETED,
            EventType.PLAN_GENERATION_STARTED,
            EventType.PLAN_GENERATION_COMPLETED,
            EventType.TASK_COMPLETED
        ]:
            event_bus.subscribe(event_type, self._on_event)
    
    async def asyncTearDown(self):
        await self.galaxy_loop.stop()
        await event_bus.stop()
    
    def _on_event(self, event: UIGalaxyEvent):
        self.received_events.append(event)
    
    async def test_full_flow(self):
        """测试完整数据流"""
        # 1. 用户提交目标（UI → L4）
        goal_id = self.galaxy_loop.receive_goal("搜索关于AI的最新新闻")
        
        # 等待事件处理
        await asyncio.sleep(0.2)
        
        # 验证GOAL_SUBMITTED事件
        submitted_events = [e for e in self.received_events 
                          if e.event_type == EventType.GOAL_SUBMITTED]
        self.assertTrue(len(submitted_events) > 0)
        self.assertEqual(submitted_events[0].data.get("goal_id"), goal_id)


class TestDataFlowDiagram(unittest.TestCase):
    """
    生成数据流图描述
    用于文档和可视化
    """
    
    def test_ui_to_l4_flow(self):
        """UI → L4 数据流"""
        flow = """
        UI → L4 数据流:
        
        1. 用户输入命令
           Windows: MinimalistWindow._on_command_submitted()
           Android: MainActivity.onCommandSubmitted()
           
        2. 解析用户意图
           Windows: _parse_user_intent()
           Android: parseUserIntent()
           
        3. 创建Goal对象
           GalaxyMainLoopL4Enhanced.receive_goal()
           
        4. 添加到目标队列
           asyncio.Queue.put()
           
        5. 发布GOAL_SUBMITTED事件
           EventBus.publish_sync()
           
        6. L4主循环处理目标
           GalaxyMainLoopL4Enhanced.run_cycle()
        """
        print(flow)
    
    def test_l4_to_ui_flow(self):
        """L4 → UI 数据流"""
        flow = """
        L4 → UI 数据流:
        
        1. 目标分解开始
           UIProgressCallback.on_goal_decomposition_started()
           → EventBus.publish(GOAL_DECOMPOSITION_STARTED)
           
        2. 目标分解完成
           UIProgressCallback.on_goal_decomposition_completed()
           → EventBus.publish(GOAL_DECOMPOSITION_COMPLETED)
           
        3. 计划生成完成
           UIProgressCallback.on_plan_generation_completed()
           → EventBus.publish(PLAN_GENERATION_COMPLETED)
           
        4. 动作执行进度
           UIProgressCallback.on_action_execution_progress()
           → EventBus.publish(ACTION_EXECUTION_PROGRESS)
           
        5. 任务完成
           UIProgressCallback.on_task_completed()
           → EventBus.publish(TASK_COMPLETED)
           
        6. WebSocket服务器广播
           ConnectionManager.broadcast()
           
        7. UI更新
           Windows: _append_output(), _update_tasks_list()
           Android: handleServerMessage()
        """
        print(flow)
    
    def test_hardware_to_ui_flow(self):
        """硬件触发 → UI 数据流"""
        flow = """
        硬件触发 → UI 数据流:
        
        1. 硬件事件检测
           HardwareTriggerManager.on_hardware_button_pressed()
           HardwareTriggerManager.on_gesture_detected()
           
        2. 触发状态机转换
           SystemStateMachine.wakeup()
           SystemStateMachine.transition_to()
           
        3. 发布状态转换事件
           EventBus.publish(STATE_TRANSITION)
           EventBus.publish(WAKEUP_SIGNAL)
           
        4. 执行状态进入回调
           _on_island_enter() → 播放灵动岛动画
           _on_sidesheet_enter() → 展开侧边栏
           
        5. UI响应
           Windows: 播放动画，更新界面
           Android: 播放动画，更新界面
        """
        print(flow)
    
    def test_ui_to_hardware_flow(self):
        """UI状态 → 硬件触发 数据流"""
        flow = """
        UI状态 → 硬件触发 数据流:
        
        1. UI动画开始
           SystemStateMachine.start_animation()
           → EventBus.publish(ANIMATION_STARTED)
           
        2. UI动画完成
           SystemStateMachine.complete_animation()
           → EventBus.publish(ANIMATION_COMPLETED)
           
        3. 记录转换历史
           _record_animation_transition()
           
        4. 更新状态统计
           _state_statistics
           
        5. 触发后续回调
           根据动画类型执行相应操作
        """
        print(flow)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestEventBus))
    suite.addTests(loader.loadTestsFromTestCase(TestL4Integration))
    suite.addTests(loader.loadTestsFromTestCase(TestStateMachineIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestHardwareTriggerManager))
    suite.addTests(loader.loadTestsFromTestCase(TestProgressCallback))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestDataFlowDiagram))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
