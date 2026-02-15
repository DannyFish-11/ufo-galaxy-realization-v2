"""
Hardware Trigger Module for UFO Galaxy

Handles hardware-level triggers and integrates with UI state machine:
- Hardware key triggers
- Gesture recognition triggers
- Voice activation triggers
- State machine integration
"""

from enum import Enum, auto
from typing import Dict, Callable, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SystemState(Enum):
    """System UI states"""
    SLEEP = "sleep"
    ISLAND = "island"      # 灵动岛状态
    SIDESHEET = "sidesheet"  # 侧边栏状态
    FULLAGENT = "fullagent"  # 全屏Agent状态


class TriggerType(Enum):
    """Hardware trigger types"""
    HARDWARE_KEY = "hardware_key"  # 物理按键
    GESTURE = "gesture"            # 手势触发
    VOICE = "voice"                # 语音唤醒
    TOUCH = "touch"                # 触摸触发


class UIStateMachine:
    """
    UI State Machine for managing system states
    
    Handles state transitions and callback notifications
    """
    
    def __init__(self):
        self.current_state = SystemState.SLEEP
        self.on_state_enter: Dict[SystemState, Callable] = {}
        self.on_state_exit: Dict[SystemState, Callable] = {}
        self.state_history: list = []
        logger.info("UIStateMachine initialized")
    
    def register_callback(self, state: SystemState, on_enter: Optional[Callable] = None, on_exit: Optional[Callable] = None):
        """Register callbacks for state transitions"""
        if on_enter:
            self.on_state_enter[state] = on_enter
        if on_exit:
            self.on_state_exit[state] = on_exit
    
    def transition_to(self, new_state: SystemState):
        """Transition to a new state"""
        if self.current_state == new_state:
            return
        
        # Call exit callback for current state
        if self.current_state in self.on_state_exit:
            try:
                self.on_state_exit[self.current_state]()
            except Exception as e:
                logger.error(f"Error in exit callback for {self.current_state}: {e}")
        
        # Record state history
        self.state_history.append({
            "from": self.current_state.value,
            "to": new_state.value
        })
        
        old_state = self.current_state
        self.current_state = new_state
        logger.info(f"State transition: {old_state.value} -> {new_state.value}")
        
        # Call enter callback for new state
        if new_state in self.on_state_enter:
            try:
                self.on_state_enter[new_state]()
            except Exception as e:
                logger.error(f"Error in enter callback for {new_state}: {e}")
    
    def wakeup(self):
        """Wake up from sleep to island state"""
        if self.current_state == SystemState.SLEEP:
            self.transition_to(SystemState.ISLAND)
            logger.info("System wakeup: SLEEP -> ISLAND")
    
    def expand_to_sidesheet(self):
        """Expand from island to sidesheet"""
        if self.current_state == SystemState.ISLAND:
            self.transition_to(SystemState.SIDESHEET)
            logger.info("Expand: ISLAND -> SIDESHEET")
    
    def expand_to_fullagent(self):
        """Expand to full agent view"""
        if self.current_state in [SystemState.ISLAND, SystemState.SIDESHEET]:
            self.transition_to(SystemState.FULLAGENT)
            logger.info("Expand to full agent")
    
    def go_to_sleep(self):
        """Go back to sleep state"""
        if self.current_state != SystemState.SLEEP:
            self.transition_to(SystemState.SLEEP)
            logger.info("System going to sleep")
    
    def get_current_state(self) -> SystemState:
        """Get current system state"""
        return self.current_state


class UIController:
    """
    UI Controller for managing UI components
    
    Provides methods to show/hide different UI components
    """
    
    def __init__(self):
        self.island_visible = False
        self.sidesheet_visible = False
        self.fullagent_visible = False
        logger.info("UIController initialized")
    
    def show_island(self):
        """Show Dynamic Island UI"""
        self.island_visible = True
        self.sidesheet_visible = False
        self.fullagent_visible = False
        logger.info("UI: Showing Dynamic Island")
        # TODO: Integrate with actual UI rendering
    
    def hide_island(self):
        """Hide Dynamic Island UI"""
        self.island_visible = False
        logger.info("UI: Hiding Dynamic Island")
    
    def show_sidesheet(self):
        """Show Side Sheet UI"""
        self.island_visible = False
        self.sidesheet_visible = True
        self.fullagent_visible = False
        logger.info("UI: Showing Side Sheet")
        # TODO: Integrate with actual UI rendering
    
    def hide_sidesheet(self):
        """Hide Side Sheet UI"""
        self.sidesheet_visible = False
        logger.info("UI: Hiding Side Sheet")
    
    def show_fullagent(self):
        """Show Full Agent UI"""
        self.island_visible = False
        self.sidesheet_visible = False
        self.fullagent_visible = True
        logger.info("UI: Showing Full Agent")
        # TODO: Integrate with actual UI rendering
    
    def hide_fullagent(self):
        """Hide Full Agent UI"""
        self.fullagent_visible = False
        logger.info("UI: Hiding Full Agent")
    
    def hide_all(self):
        """Hide all UI components"""
        self.island_visible = False
        self.sidesheet_visible = False
        self.fullagent_visible = False
        logger.info("UI: Hiding all components")


class HardwareTrigger:
    """
    Hardware Trigger Handler
    
    Integrates hardware events with UI state machine:
    - Hardware key events
    - Gesture recognition events
    - Voice activation events
    """
    
    def __init__(self, state_machine: Optional[UIStateMachine] = None, ui_controller: Optional[UIController] = None):
        """
        Initialize hardware trigger handler
        
        Args:
            state_machine: UI state machine instance
            ui_controller: UI controller instance
        """
        self.state_machine = state_machine or UIStateMachine()
        self.ui_controller = ui_controller or UIController()
        self.trigger_handlers: Dict[TriggerType, Callable] = {}
        self._setup_default_handlers()
        logger.info("HardwareTrigger initialized")
    
    def _setup_default_handlers(self):
        """Setup default trigger handlers"""
        self.trigger_handlers[TriggerType.HARDWARE_KEY] = self._handle_hardware_key
        self.trigger_handlers[TriggerType.GESTURE] = self._handle_gesture
        self.trigger_handlers[TriggerType.VOICE] = self._handle_voice
        self.trigger_handlers[TriggerType.TOUCH] = self._handle_touch
    
    def register_ui_callbacks(self, ui_controller: UIController):
        """
        Register UI callbacks for state transitions
        
        Binds UI controller methods to state machine callbacks:
        - ISLAND state -> show_island()
        - SIDESHEET state -> show_sidesheet()
        - FULLAGENT state -> show_fullagent()
        
        Args:
            ui_controller: UI controller instance with show methods
        """
        self.state_machine.on_state_enter[SystemState.ISLAND] = ui_controller.show_island
        self.state_machine.on_state_enter[SystemState.SIDESHEET] = ui_controller.show_sidesheet
        self.state_machine.on_state_enter[SystemState.FULLAGENT] = ui_controller.show_fullagent
        
        # Register exit callbacks
        self.state_machine.on_state_exit[SystemState.ISLAND] = ui_controller.hide_island
        self.state_machine.on_state_exit[SystemState.SIDESHEET] = ui_controller.hide_sidesheet
        self.state_machine.on_state_exit[SystemState.FULLAGENT] = ui_controller.hide_fullagent
        self.state_machine.on_state_exit[SystemState.SLEEP] = ui_controller.hide_all
        
        logger.info("UI callbacks registered with state machine")
    
    def on_hardware_trigger(self, trigger_type: TriggerType, **kwargs):
        """
        Handle hardware trigger events
        
        Maps hardware triggers to state machine transitions:
        - HARDWARE_KEY: SLEEP -> ISLAND (wakeup)
        - GESTURE: ISLAND -> SIDESHEET (expand)
        - VOICE: SLEEP -> ISLAND (wakeup)
        - TOUCH: Context-dependent
        
        Args:
            trigger_type: Type of hardware trigger
            **kwargs: Additional trigger parameters
        """
        logger.info(f"Hardware trigger received: {trigger_type.value}")
        
        if trigger_type == TriggerType.HARDWARE_KEY:
            # 休眠→灵动岛
            self.state_machine.wakeup()
        elif trigger_type == TriggerType.GESTURE:
            # 灵动岛→侧边栏
            self.state_machine.expand_to_sidesheet()
        elif trigger_type == TriggerType.VOICE:
            # Voice wakeup
            self.state_machine.wakeup()
        elif trigger_type == TriggerType.TOUCH:
            # Handle touch based on current state
            self._handle_touch_trigger(**kwargs)
        else:
            logger.warning(f"Unknown trigger type: {trigger_type}")
    
    def _handle_hardware_key(self, **kwargs):
        """Handle hardware key trigger"""
        key_code = kwargs.get("key_code", "unknown")
        logger.info(f"Hardware key pressed: {key_code}")
        self.state_machine.wakeup()
    
    def _handle_gesture(self, **kwargs):
        """Handle gesture trigger"""
        gesture_type = kwargs.get("gesture_type", "unknown")
        logger.info(f"Gesture detected: {gesture_type}")
        self.state_machine.expand_to_sidesheet()
    
    def _handle_voice(self, **kwargs):
        """Handle voice trigger"""
        wake_word = kwargs.get("wake_word", "unknown")
        logger.info(f"Voice wake word detected: {wake_word}")
        self.state_machine.wakeup()
    
    def _handle_touch(self, **kwargs):
        """Handle touch trigger"""
        touch_area = kwargs.get("touch_area", "unknown")
        logger.info(f"Touch detected in area: {touch_area}")
        self._handle_touch_trigger(**kwargs)
    
    def _handle_touch_trigger(self, **kwargs):
        """Handle touch trigger based on current state"""
        current_state = self.state_machine.get_current_state()
        touch_area = kwargs.get("touch_area", "")
        
        if current_state == SystemState.SLEEP:
            # Wake up on touch
            self.state_machine.wakeup()
        elif current_state == SystemState.ISLAND:
            if touch_area == "expand":
                self.state_machine.expand_to_sidesheet()
            elif touch_area == "full":
                self.state_machine.expand_to_fullagent()
        elif current_state == SystemState.SIDESHEET:
            if touch_area == "full":
                self.state_machine.expand_to_fullagent()
            elif touch_area == "collapse":
                self.state_machine.go_to_sleep()
    
    def get_current_state(self) -> SystemState:
        """Get current system state"""
        return self.state_machine.get_current_state()
    
    def force_state(self, state: SystemState):
        """Force system to a specific state (for testing/debugging)"""
        self.state_machine.transition_to(state)
        logger.info(f"Forced state transition to: {state.value}")


# Convenience functions for easy integration
def create_hardware_trigger() -> HardwareTrigger:
    """Create and initialize hardware trigger with UI bindings"""
    ui_controller = UIController()
    state_machine = UIStateMachine()
    trigger = HardwareTrigger(state_machine, ui_controller)
    trigger.register_ui_callbacks(ui_controller)
    return trigger


def start_hardware_trigger_system() -> HardwareTrigger:
    """Start the hardware trigger system"""
    trigger = create_hardware_trigger()
    logger.info("Hardware trigger system started")
    return trigger


# Example usage
if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Create hardware trigger system
    hw_trigger = start_hardware_trigger_system()
    
    # Simulate hardware triggers
    print("\n=== Simulating Hardware Triggers ===")
    
    # Initial state
    print(f"Initial state: {hw_trigger.get_current_state().value}")
    
    # Hardware key press (sleep -> island)
    hw_trigger.on_hardware_trigger(TriggerType.HARDWARE_KEY, key_code="POWER")
    print(f"After hardware key: {hw_trigger.get_current_state().value}")
    
    # Gesture (island -> sidesheet)
    hw_trigger.on_hardware_trigger(TriggerType.GESTURE, gesture_type="swipe_up")
    print(f"After gesture: {hw_trigger.get_current_state().value}")
    
    # Touch to expand to full agent
    hw_trigger.on_hardware_trigger(TriggerType.TOUCH, touch_area="full")
    print(f"After touch (full): {hw_trigger.get_current_state().value}")
    
    print("\n=== Demo Complete ===")
