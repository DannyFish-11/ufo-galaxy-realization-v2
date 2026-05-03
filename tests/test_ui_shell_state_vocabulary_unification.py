from system_integration.state_machine_ui_integration import SystemState, SystemStateMachine


def test_system_state_uses_unified_shell_vocabulary():
    assert SystemState.DORMANT.value == "dormant"
    assert SystemState.ISLAND.value == "island"
    assert SystemState.SIDESHEET.value == "sidesheet"
    assert SystemState.FULLAGENT.value == "fullagent"


def test_legacy_state_names_alias_to_canonical_shell_vocabulary():
    assert SystemState.SLEEPING is SystemState.DORMANT
    assert SystemState.FULLSCREEN is SystemState.FULLAGENT


def test_fullagent_transition_uses_canonical_state():
    state_machine = SystemStateMachine()
    state_machine._current_state = SystemState.DORMANT

    assert state_machine.wakeup()
    assert state_machine.current_state is SystemState.ISLAND

    state_machine.expand_to_fullagent()
    assert state_machine.current_state is SystemState.FULLAGENT


def test_legacy_fullscreen_transition_calls_canonical_fullagent_state():
    state_machine = SystemStateMachine()
    state_machine._current_state = SystemState.ISLAND

    state_machine.expand_to_fullscreen()
    assert state_machine.current_state is SystemState.FULLAGENT
