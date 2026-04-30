#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_l3_cognitive_context_authority.py
=============================================

L3 — Canonicalize cognitive input assembly under a single context authority.

Validates:
  1.  LLM_CONTEXT_AUTHORITY sentinel is importable from core.llm.context_authority.
  2.  LLM_CONTEXT_AUTHORITY is a non-empty string.
  3.  LLM_CONTEXT_AUTHORITY identifies CognitiveContextAuthority by module path.
  4.  CognitiveContextAuthority class is importable from core.llm.context_authority.
  5.  CognitiveContextRequest class is importable from core.llm.context_authority.
  6.  CognitiveContextAssembly class is importable from core.llm.context_authority.
  7.  get_cognitive_context_authority factory is importable from core.llm.context_authority.
  8.  get_cognitive_context_authority returns a CognitiveContextAuthority instance.
  9.  get_cognitive_context_authority returns the same singleton on repeated calls.
  10. refresh_cognitive_context_authority returns a fresh CognitiveContextAuthority instance.
  11. CognitiveContextRequest default task_type is "general".
  12. CognitiveContextRequest default max_history_turns is 8.
  13. CognitiveContextRequest max_history_turns is clamped to >= 0.
  14. CognitiveContextAssembly authority defaults to LLM_CONTEXT_AUTHORITY.
  15. CognitiveContextAssembly is_canonical defaults to True.
  16. CognitiveContextAssembly.to_dict() includes messages key.
  17. CognitiveContextAssembly.to_dict() includes tool_manifest key.
  18. CognitiveContextAssembly.to_dict() includes assembly_trace key.
  19. CognitiveContextAssembly.to_dict() includes authority key.
  20. CognitiveContextAssembly.to_dict() authority equals LLM_CONTEXT_AUTHORITY.
  21. CognitiveContextAssembly.to_dict() includes is_canonical key.
  22. CognitiveContextAssembly.to_dict() includes source_request key.
  23. CognitiveContextAuthority has an assemble method.
  24. assemble returns a CognitiveContextAssembly.
  25. assemble result authority equals LLM_CONTEXT_AUTHORITY.
  26. assemble result is_canonical is True.
  27. assemble result includes source_request.
  28. assemble minimal request produces at least one system message.
  29. assemble system message is the first message.
  30. assemble system message role is "system".
  31. assemble with user_message appends it as last message with role "user".
  32. assemble with no user_message does not append user message.
  33. assemble with system_prefix uses it in system message content.
  34. assemble with no system_prefix uses default identity in system message.
  35. assemble with user_policy includes it in system message content.
  36. assemble with soul_policy includes it in system message content.
  37. assemble with agents_policy includes it in system message content.
  38. assemble with memory_context includes it in system message content.
  39. assemble with continuity_context includes it in system message content.
  40. assemble with policy_constraints includes them in system message content.
  41. assemble with execution_metadata includes summary in system message content.
  42. assemble conversation_history is included in messages.
  43. assemble conversation_history is bounded by max_history_turns.
  44. assemble conversation_history turns appear before user_message.
  45. assemble conversation_history turns appear after system message.
  46. assemble with max_history_turns=0 includes no history turns.
  47. assemble assembly_trace is a non-empty list.
  48. assemble assembly_trace includes "system_message: assembled".
  49. assemble assembly_trace records soul_policy injection.
  50. assemble assembly_trace records user_policy injection.
  51. assemble assembly_trace records memory_context injection.
  52. assemble assembly_trace records absence of soul_policy.
  53. assemble assembly_trace records absence of memory_context.
  54. assemble assembly_trace records conversation history turn count.
  55. assemble assembly_trace records user_message appended.
  56. assemble assembly_trace records absence of user_message.
  57. assemble tool_manifest is None when not provided.
  58. assemble tool_manifest is passed through when provided.
  59. assemble assembly_trace records tool_manifest count.
  60. assemble to_dict is JSON-serialisable.
  61. assemble policy order: soul before agents before user.
  62. assemble policy order: policies before memory.
  63. assemble policy order: memory before continuity.
  64. assemble message order: system then history then user.
  65. retry path assembling with same request produces same message count.
  66. retry path assembly_trace records execution_metadata.
  67. fallback path using same request produces same system message content.
  68. LLM_CONTEXT_AUTHORITY is re-exported from core.llm package.
  69. CognitiveContextRequest is re-exported from core.llm package.
  70. CognitiveContextAssembly is re-exported from core.llm package.
  71. CognitiveContextAuthority is re-exported from core.llm package.
  72. get_cognitive_context_authority is re-exported from core.llm package.
  73. LLM_CONTEXT_AUTHORITY differs from LLM_ROUTE_AUTHORITY.
  74. LLM_CONTEXT_AUTHORITY differs from LLM_SUPPLY_AUTHORITY.
  75. docs/MODEL_ROUTING_AUTHORITY.md contains LLM_CONTEXT_AUTHORITY.
  76. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveContextAuthority.
  77. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveContextRequest.
  78. docs/MODEL_ROUTING_AUTHORITY.md contains CognitiveContextAssembly.
  79. docs/MODEL_ROUTING_AUTHORITY.md contains get_cognitive_context_authority.
  80. docs/MODEL_ROUTING_AUTHORITY.md section 11 exists.
  81. CognitiveContextAuthority is importable without errors.
  82. core.llm.__init__ exports LLM_CONTEXT_AUTHORITY without error.
  83. assemble with empty conversation_history produces no history entries.
  84. assemble source_request has_soul_policy True when soul_policy set.
  85. assemble source_request has_user_policy True when user_policy set.
  86. assemble source_request history_turns matches len of provided history.
  87. assemble source_request has_tool_manifest True when tool_manifest set.
  88. assemble source_request has_user_message True when user_message set.
  89. assemble source_request has_memory_context True when memory_context set.
  90. assemble source_request task_type preserved in to_dict source_request.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# 1-3: LLM_CONTEXT_AUTHORITY sentinel
# ---------------------------------------------------------------------------


def test_01_llm_context_authority_sentinel_importable():
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    assert LLM_CONTEXT_AUTHORITY is not None


def test_02_llm_context_authority_sentinel_non_empty():
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    assert isinstance(LLM_CONTEXT_AUTHORITY, str)
    assert len(LLM_CONTEXT_AUTHORITY) > 0


def test_03_llm_context_authority_sentinel_identifies_class():
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    assert "CognitiveContextAuthority" in LLM_CONTEXT_AUTHORITY


# ---------------------------------------------------------------------------
# 4-7: Class / factory importability
# ---------------------------------------------------------------------------


def test_04_cognitive_context_authority_class_importable():
    from core.llm.context_authority import CognitiveContextAuthority
    assert CognitiveContextAuthority is not None


def test_05_cognitive_context_request_class_importable():
    from core.llm.context_authority import CognitiveContextRequest
    assert CognitiveContextRequest is not None


def test_06_cognitive_context_assembly_class_importable():
    from core.llm.context_authority import CognitiveContextAssembly
    assert CognitiveContextAssembly is not None


def test_07_get_cognitive_context_authority_importable():
    from core.llm.context_authority import get_cognitive_context_authority
    assert callable(get_cognitive_context_authority)


# ---------------------------------------------------------------------------
# 8-10: Singleton / factory behaviour
# ---------------------------------------------------------------------------


def test_08_get_cognitive_context_authority_returns_instance():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        get_cognitive_context_authority,
    )
    auth = get_cognitive_context_authority()
    assert isinstance(auth, CognitiveContextAuthority)


def test_09_get_cognitive_context_authority_singleton():
    from core.llm.context_authority import get_cognitive_context_authority
    a1 = get_cognitive_context_authority()
    a2 = get_cognitive_context_authority()
    assert a1 is a2


def test_10_refresh_cognitive_context_authority_returns_fresh_instance():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        refresh_cognitive_context_authority,
        get_cognitive_context_authority,
    )
    original = get_cognitive_context_authority()
    fresh = refresh_cognitive_context_authority()
    assert isinstance(fresh, CognitiveContextAuthority)
    assert fresh is not original


# ---------------------------------------------------------------------------
# 11-13: CognitiveContextRequest defaults and validation
# ---------------------------------------------------------------------------


def test_11_cognitive_context_request_default_task_type():
    from core.llm.context_authority import CognitiveContextRequest
    req = CognitiveContextRequest()
    assert req.task_type == "general"


def test_12_cognitive_context_request_default_max_history_turns():
    from core.llm.context_authority import CognitiveContextRequest
    req = CognitiveContextRequest()
    assert req.max_history_turns == 8


def test_13_cognitive_context_request_max_history_turns_clamped():
    from core.llm.context_authority import CognitiveContextRequest
    req = CognitiveContextRequest(max_history_turns=-5)
    assert req.max_history_turns == 0


# ---------------------------------------------------------------------------
# 14-22: CognitiveContextAssembly defaults and to_dict
# ---------------------------------------------------------------------------


def test_14_cognitive_context_assembly_authority_default():
    from core.llm.context_authority import (
        CognitiveContextAssembly,
        LLM_CONTEXT_AUTHORITY,
    )
    asm = CognitiveContextAssembly()
    assert asm.authority == LLM_CONTEXT_AUTHORITY


def test_15_cognitive_context_assembly_is_canonical_default():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    assert asm.is_canonical is True


def test_16_cognitive_context_assembly_to_dict_messages_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "messages" in d


def test_17_cognitive_context_assembly_to_dict_tool_manifest_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "tool_manifest" in d


def test_18_cognitive_context_assembly_to_dict_assembly_trace_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "assembly_trace" in d


def test_19_cognitive_context_assembly_to_dict_authority_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "authority" in d


def test_20_cognitive_context_assembly_to_dict_authority_value():
    from core.llm.context_authority import (
        CognitiveContextAssembly,
        LLM_CONTEXT_AUTHORITY,
    )
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert d["authority"] == LLM_CONTEXT_AUTHORITY


def test_21_cognitive_context_assembly_to_dict_is_canonical_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "is_canonical" in d


def test_22_cognitive_context_assembly_to_dict_source_request_key():
    from core.llm.context_authority import CognitiveContextAssembly
    asm = CognitiveContextAssembly()
    d = asm.to_dict()
    assert "source_request" in d


# ---------------------------------------------------------------------------
# 23-27: CognitiveContextAuthority.assemble core contracts
# ---------------------------------------------------------------------------


def test_23_cognitive_context_authority_has_assemble_method():
    from core.llm.context_authority import CognitiveContextAuthority
    assert hasattr(CognitiveContextAuthority, "assemble")
    assert callable(CognitiveContextAuthority.assemble)


def test_24_assemble_returns_cognitive_context_assembly():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextAssembly,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert isinstance(result, CognitiveContextAssembly)


def test_25_assemble_result_authority_equals_sentinel():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
        LLM_CONTEXT_AUTHORITY,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert result.authority == LLM_CONTEXT_AUTHORITY


def test_26_assemble_result_is_canonical_true():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert result.is_canonical is True


def test_27_assemble_result_includes_source_request():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    req = CognitiveContextRequest(task_type="coding")
    auth = CognitiveContextAuthority()
    result = auth.assemble(req)
    assert result.source_request is req


# ---------------------------------------------------------------------------
# 28-32: Message structure
# ---------------------------------------------------------------------------


def test_28_assemble_produces_at_least_one_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert len(result.messages) >= 1


def test_29_assemble_system_message_is_first():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest(user_message="Hi"))
    assert result.messages[0]["role"] == "system"


def test_30_assemble_system_message_role_is_system():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    system_msgs = [m for m in result.messages if m.get("role") == "system"]
    assert len(system_msgs) == 1


def test_31_assemble_user_message_appended_as_last_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_message="What can you do?")
    )
    assert result.messages[-1]["role"] == "user"
    assert result.messages[-1]["content"] == "What can you do?"


def test_32_assemble_no_user_message_does_not_append_user():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest(user_message=None))
    user_msgs = [m for m in result.messages if m.get("role") == "user"]
    assert len(user_msgs) == 0


# ---------------------------------------------------------------------------
# 33-41: System message content assembly
# ---------------------------------------------------------------------------


def test_33_assemble_custom_system_prefix_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(system_prefix="You are a coding assistant.")
    )
    system_content = result.messages[0]["content"]
    assert "coding assistant" in system_content


def test_34_assemble_default_system_prefix_when_not_provided():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    system_content = result.messages[0]["content"]
    assert "Galaxy" in system_content


def test_35_assemble_user_policy_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_policy="Always reply in English.")
    )
    system_content = result.messages[0]["content"]
    assert "English" in system_content


def test_36_assemble_soul_policy_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            soul_policy="Never reveal internal config.",
            execution_mode="task_execute",
        )
    )
    system_content = result.messages[0]["content"]
    assert "Never reveal internal config" in system_content


def test_37_assemble_agents_policy_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(agents_policy="Agents must confirm before deleting.")
    )
    system_content = result.messages[0]["content"]
    assert "confirm before deleting" in system_content


def test_38_assemble_memory_context_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(memory_context="User prefers Python for scripting.")
    )
    system_content = result.messages[0]["content"]
    assert "prefers Python" in system_content


def test_39_assemble_continuity_context_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            continuity_context="Resuming task from session abc123."
        )
    )
    system_content = result.messages[0]["content"]
    assert "abc123" in system_content


def test_40_assemble_policy_constraints_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(policy_constraints=["Constraint A", "Constraint B"])
    )
    system_content = result.messages[0]["content"]
    assert "Constraint A" in system_content
    assert "Constraint B" in system_content


def test_41_assemble_execution_metadata_in_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            execution_metadata={"retry_count": 2, "recovery": True}
        )
    )
    system_content = result.messages[0]["content"]
    assert "retry_count" in system_content


# ---------------------------------------------------------------------------
# 42-46: Conversation history
# ---------------------------------------------------------------------------


def test_42_assemble_conversation_history_included():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(conversation_history=history)
    )
    assert any(m["content"] == "Hello" for m in result.messages)
    assert any(m["content"] == "Hi there!" for m in result.messages)


def test_43_assemble_conversation_history_bounded_by_max_turns():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [
        {"role": "user", "content": f"Turn {i}"}
        for i in range(20)
    ]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            conversation_history=history, max_history_turns=3
        )
    )
    history_in_messages = [
        m for m in result.messages if m.get("role") == "user"
        and m.get("content", "").startswith("Turn ")
    ]
    assert len(history_in_messages) <= 3


def test_44_assemble_history_before_user_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [{"role": "user", "content": "Old question"}]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            conversation_history=history,
            user_message="New question",
        )
    )
    roles = [m["role"] for m in result.messages]
    # Find positions
    old_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("content") == "Old question"
    )
    new_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("content") == "New question"
    )
    assert old_idx < new_idx


def test_45_assemble_history_after_system_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [{"role": "user", "content": "Old question"}]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(conversation_history=history)
    )
    system_idx = next(
        i for i, m in enumerate(result.messages) if m.get("role") == "system"
    )
    old_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("content") == "Old question"
    )
    assert system_idx < old_idx


def test_46_assemble_max_history_turns_zero_includes_no_history():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [{"role": "user", "content": f"H{i}"} for i in range(5)]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            conversation_history=history,
            max_history_turns=0,
            user_message="Now",
        )
    )
    # Only system message + user_message ("Now") should be present
    history_in_messages = [
        m for m in result.messages
        if m.get("content", "").startswith("H")
    ]
    assert len(history_in_messages) == 0


# ---------------------------------------------------------------------------
# 47-56: Assembly trace
# ---------------------------------------------------------------------------


def test_47_assemble_trace_is_non_empty_list():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert isinstance(result.assembly_trace, list)
    assert len(result.assembly_trace) > 0


def test_48_assemble_trace_includes_system_message_assembled():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert any("system_message" in t for t in result.assembly_trace)


def test_49_assemble_trace_records_soul_policy_injection():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(soul_policy="Do not harm.")
    )
    soul_entries = [t for t in result.assembly_trace if "soul_policy" in t]
    assert len(soul_entries) >= 1
    assert any("injected" in t for t in soul_entries)


def test_50_assemble_trace_records_user_policy_injection():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_policy="Be concise.")
    )
    user_policy_entries = [
        t for t in result.assembly_trace if "user_policy" in t
    ]
    assert any("injected" in t for t in user_policy_entries)


def test_51_assemble_trace_records_memory_context_injection():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(memory_context="Some memory.")
    )
    memory_entries = [
        t for t in result.assembly_trace if "memory_context" in t
    ]
    assert any("injected" in t for t in memory_entries)


def test_52_assemble_trace_records_absence_of_soul_policy():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest(soul_policy=None))
    soul_entries = [t for t in result.assembly_trace if "soul_policy" in t]
    assert any("absent" in t for t in soul_entries)


def test_53_assemble_trace_records_absence_of_memory_context():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest(memory_context=None))
    memory_entries = [
        t for t in result.assembly_trace if "memory_context" in t
    ]
    assert any("absent" in t for t in memory_entries)


def test_54_assemble_trace_records_history_turn_count():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [{"role": "user", "content": "Hi"}]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(conversation_history=history)
    )
    history_entries = [
        t for t in result.assembly_trace if "conversation_history" in t
    ]
    assert len(history_entries) >= 1
    # Should record at least the "1" turn count
    assert any("1" in t for t in history_entries)


def test_55_assemble_trace_records_user_message_appended():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_message="Ping")
    )
    user_msg_entries = [
        t for t in result.assembly_trace if "user_message" in t
    ]
    assert any("appended" in t for t in user_msg_entries)


def test_56_assemble_trace_records_absence_of_user_message():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest(user_message=None))
    user_msg_entries = [
        t for t in result.assembly_trace if "user_message" in t
    ]
    assert any("absent" in t for t in user_msg_entries)


# ---------------------------------------------------------------------------
# 57-60: Tool manifest
# ---------------------------------------------------------------------------


def test_57_assemble_tool_manifest_none_when_not_provided():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(CognitiveContextRequest())
    assert result.tool_manifest is None


def test_58_assemble_tool_manifest_passed_through():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    tools = [{"name": "search", "description": "Search the web"}]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(tool_manifest=tools)
    )
    assert result.tool_manifest == tools


def test_59_assemble_trace_records_tool_manifest_count():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    tools = [
        {"name": "tool_a"},
        {"name": "tool_b"},
    ]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(tool_manifest=tools)
    )
    tool_entries = [
        t for t in result.assembly_trace if "tool_manifest" in t
    ]
    assert any("2" in t for t in tool_entries)


def test_60_assemble_to_dict_json_serialisable():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            system_prefix="You are helpful.",
            user_message="What is 2+2?",
            user_policy="Be brief.",
            task_type="general",
            session_id="test-session",
        )
    )
    d = result.to_dict()
    serialised = json.dumps(d)
    assert len(serialised) > 0


# ---------------------------------------------------------------------------
# 61-64: Assembly order contract
# ---------------------------------------------------------------------------


def test_61_assemble_policy_order_soul_before_agents_before_user():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            soul_policy="SOUL",
            agents_policy="AGENTS",
            user_policy="USER",
        )
    )
    system_content = result.messages[0]["content"]
    soul_pos = system_content.find("SOUL")
    agents_pos = system_content.find("AGENTS")
    user_pos = system_content.find("USER")
    assert soul_pos < agents_pos < user_pos


def test_62_assemble_policy_order_policies_before_memory():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            user_policy="USER_POLICY_MARKER",
            memory_context="MEMORY_MARKER",
        )
    )
    system_content = result.messages[0]["content"]
    policy_pos = system_content.find("USER_POLICY_MARKER")
    memory_pos = system_content.find("MEMORY_MARKER")
    assert policy_pos < memory_pos


def test_63_assemble_policy_order_memory_before_continuity():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            memory_context="MEMORY_MARKER",
            continuity_context="CONTINUITY_MARKER",
        )
    )
    system_content = result.messages[0]["content"]
    memory_pos = system_content.find("MEMORY_MARKER")
    continuity_pos = system_content.find("CONTINUITY_MARKER")
    assert memory_pos < continuity_pos


def test_64_assemble_message_order_system_then_history_then_user():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [{"role": "assistant", "content": "HIST_CONTENT"}]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            conversation_history=history,
            user_message="USER_CONTENT",
        )
    )
    system_idx = next(
        i for i, m in enumerate(result.messages) if m["role"] == "system"
    )
    hist_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("content") == "HIST_CONTENT"
    )
    user_idx = next(
        i for i, m in enumerate(result.messages)
        if m.get("content") == "USER_CONTENT"
    )
    assert system_idx < hist_idx < user_idx


# ---------------------------------------------------------------------------
# 65-67: Retry / fallback / recovery path contracts
# ---------------------------------------------------------------------------


def test_65_retry_path_same_request_produces_same_message_count():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    req = CognitiveContextRequest(
        user_message="Hello",
        user_policy="Be helpful.",
        conversation_history=[{"role": "user", "content": "Prior"}],
    )
    auth = CognitiveContextAuthority()
    first = auth.assemble(req)
    second = auth.assemble(req)
    assert len(first.messages) == len(second.messages)


def test_66_retry_path_execution_metadata_in_trace():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    req = CognitiveContextRequest(
        user_message="Retry me",
        execution_metadata={"retry_count": 1},
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(req)
    meta_entries = [
        t for t in result.assembly_trace if "execution_metadata" in t
    ]
    assert any("injected" in t for t in meta_entries)


def test_67_fallback_path_same_system_message_content():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    req = CognitiveContextRequest(
        system_prefix="You are a fallback assistant.",
        user_message="Fallback test",
    )
    auth = CognitiveContextAuthority()
    normal_asm = auth.assemble(req)
    fallback_asm = auth.assemble(req)
    assert (
        normal_asm.messages[0]["content"]
        == fallback_asm.messages[0]["content"]
    )


# ---------------------------------------------------------------------------
# 68-72: core.llm package re-exports
# ---------------------------------------------------------------------------


def test_68_llm_context_authority_re_exported_from_core_llm():
    from core.llm import LLM_CONTEXT_AUTHORITY
    assert LLM_CONTEXT_AUTHORITY is not None


def test_69_cognitive_context_request_re_exported_from_core_llm():
    from core.llm import CognitiveContextRequest
    assert CognitiveContextRequest is not None


def test_70_cognitive_context_assembly_re_exported_from_core_llm():
    from core.llm import CognitiveContextAssembly
    assert CognitiveContextAssembly is not None


def test_71_cognitive_context_authority_re_exported_from_core_llm():
    from core.llm import CognitiveContextAuthority
    assert CognitiveContextAuthority is not None


def test_72_get_cognitive_context_authority_re_exported_from_core_llm():
    from core.llm import get_cognitive_context_authority
    assert callable(get_cognitive_context_authority)


# ---------------------------------------------------------------------------
# 73-74: Sentinel uniqueness
# ---------------------------------------------------------------------------


def test_73_llm_context_authority_differs_from_llm_route_authority():
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    from core.llm.route_authority import LLM_ROUTE_AUTHORITY
    assert LLM_CONTEXT_AUTHORITY != LLM_ROUTE_AUTHORITY


def test_74_llm_context_authority_differs_from_llm_supply_authority():
    from core.llm.context_authority import LLM_CONTEXT_AUTHORITY
    from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY
    assert LLM_CONTEXT_AUTHORITY != LLM_SUPPLY_AUTHORITY


# ---------------------------------------------------------------------------
# 75-80: Documentation checks
# ---------------------------------------------------------------------------


def test_75_docs_contain_llm_context_authority():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "LLM_CONTEXT_AUTHORITY" in content


def test_76_docs_contain_cognitive_context_authority():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "CognitiveContextAuthority" in content


def test_77_docs_contain_cognitive_context_request():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "CognitiveContextRequest" in content


def test_78_docs_contain_cognitive_context_assembly():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "CognitiveContextAssembly" in content


def test_79_docs_contain_get_cognitive_context_authority():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "get_cognitive_context_authority" in content


def test_80_docs_section_11_exists():
    doc_path = os.path.join(
        _REPO_ROOT, "docs", "MODEL_ROUTING_AUTHORITY.md"
    )
    with open(doc_path, encoding="utf-8") as fh:
        content = fh.read()
    assert "## 11." in content


# ---------------------------------------------------------------------------
# 81-82: Module importability
# ---------------------------------------------------------------------------


def test_81_cognitive_context_authority_importable_without_error():
    import importlib
    mod = importlib.import_module("core.llm.context_authority")
    assert mod is not None


def test_82_core_llm_init_exports_llm_context_authority_without_error():
    import importlib
    mod = importlib.import_module("core.llm")
    assert hasattr(mod, "LLM_CONTEXT_AUTHORITY")


# ---------------------------------------------------------------------------
# 83-90: to_dict source_request metadata
# ---------------------------------------------------------------------------


def test_83_assemble_empty_conversation_history_produces_no_history_entries():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(
            conversation_history=[],
            user_message="Hi",
        )
    )
    # Only system message + user message
    assert len(result.messages) == 2


def test_84_to_dict_source_request_has_soul_policy_true_when_set():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(soul_policy="SOUL")
    )
    d = result.to_dict()
    assert d["source_request"]["has_soul_policy"] is True


def test_85_to_dict_source_request_has_user_policy_true_when_set():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_policy="USER")
    )
    d = result.to_dict()
    assert d["source_request"]["has_user_policy"] is True


def test_86_to_dict_source_request_history_turns_matches_provided():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    history = [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "B"},
        {"role": "user", "content": "C"},
    ]
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(conversation_history=history)
    )
    d = result.to_dict()
    assert d["source_request"]["history_turns"] == 3


def test_87_to_dict_source_request_has_tool_manifest_true_when_set():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(tool_manifest=[{"name": "my_tool"}])
    )
    d = result.to_dict()
    assert d["source_request"]["has_tool_manifest"] is True


def test_88_to_dict_source_request_has_user_message_true_when_set():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(user_message="Hello!")
    )
    d = result.to_dict()
    assert d["source_request"]["has_user_message"] is True


def test_89_to_dict_source_request_has_memory_context_true_when_set():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(memory_context="memory data")
    )
    d = result.to_dict()
    assert d["source_request"]["has_memory_context"] is True


def test_90_to_dict_source_request_task_type_preserved():
    from core.llm.context_authority import (
        CognitiveContextAuthority,
        CognitiveContextRequest,
    )
    auth = CognitiveContextAuthority()
    result = auth.assemble(
        CognitiveContextRequest(task_type="reasoning")
    )
    d = result.to_dict()
    assert d["source_request"]["task_type"] == "reasoning"
