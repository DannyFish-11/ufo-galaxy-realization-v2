#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_batch_pr5_command_llm_routing_decomposition.py
==========================================================

Batch PR-5 — Refactor command routing and multi-LLM routing into modular,
testable subsystems.

Validates:
  1.  core/commands/__init__.py exists.
  2.  core/commands/__init__.py defines COMMAND_ROUTING_PACKAGE_AUTHORITY.
  3.  COMMAND_ROUTING_PACKAGE_AUTHORITY == "core.commands".
  4.  core/commands/__init__.py re-exports CommandRouter.
  5.  core/commands/__init__.py re-exports get_command_router callable.
  6.  core/commands/router.py exists.
  7.  core/commands/router.py defines COMMAND_ROUTER_AUTHORITY sentinel.
  8.  COMMAND_ROUTER_AUTHORITY == "core.commands.router".
  9.  core/commands/router.py re-exports get_command_router callable.
 10.  core/commands/registry.py exists.
 11.  core/commands/registry.py defines COMMAND_REGISTRY_AUTHORITY sentinel.
 12.  core/commands/registry.py defines CommandRegistry class.
 13.  CommandRegistry supports register/get/list_commands interface.
 14.  core/commands/dispatcher.py exists.
 15.  core/commands/dispatcher.py defines COMMAND_DISPATCHER_AUTHORITY sentinel.
 16.  core/commands/dispatcher.py defines CommandDispatcher class.
 17.  core/commands/context.py exists.
 18.  core/commands/context.py defines COMMAND_CONTEXT_AUTHORITY sentinel.
 19.  core/commands/context.py defines CommandContext dataclass.
 20.  CommandContext.from_request() factory works correctly.
 21.  core/commands/middleware.py exists.
 22.  core/commands/middleware.py defines COMMAND_MIDDLEWARE_AUTHORITY sentinel.
 23.  core/commands/middleware.py defines CommandMiddleware ABC.
 24.  core/commands/validators/__init__.py exists.
 25.  core/commands/validators/__init__.py defines COMMAND_VALIDATOR_AUTHORITY.
 26.  EnvelopeValidator rejects empty device_id.
 27.  RiskClassificationValidator rejects high-risk commands.
 28.  RiskClassificationValidator allows high-risk when override set.
 29.  core/commands/handlers/__init__.py exists.
 30.  core/commands/handlers/__init__.py defines COMMAND_HANDLER_AUTHORITY.
 31.  core/llm/__init__.py defines LLM_ROUTING_PACKAGE_AUTHORITY sentinel.
 32.  LLM_ROUTING_PACKAGE_AUTHORITY == "core.llm".
 33.  core/llm/__init__.py re-exports MultiLLMRouter.
 34.  core/llm/__init__.py re-exports get_llm_router callable.
 35.  core/llm/router.py defines LLM_ROUTER_AUTHORITY sentinel.
 36.  LLM_ROUTER_AUTHORITY == "core.llm.router".
 37.  core/llm/policies.py exists.
 38.  core/llm/policies.py defines LLM_POLICIES_AUTHORITY sentinel.
 39.  core/llm/policies.py re-exports TASK_ROUTING_PREFERENCES.
 40.  core/llm/policies.py defines PolicyBasedSelector class.
 41.  core/llm/failover.py exists.
 42.  core/llm/failover.py defines LLM_FAILOVER_AUTHORITY sentinel.
 43.  core/llm/failover.py defines FailoverStrategy class.
 44.  core/llm/failover.py defines RetryPolicy class.
 45.  core/llm/providers/__init__.py exists.
 46.  core/llm/providers/__init__.py defines LLM_PROVIDERS_AUTHORITY sentinel.
 47.  core/llm/providers/__init__.py re-exports BaseProviderAdapter.
 48.  core/llm/providers/__init__.py re-exports OpenAIAdapter.
 49.  CommandRegistry.register decorator works end-to-end.
 50.  FailoverStrategy.execute() succeeds on first candidate.
 51.  FailoverStrategy.execute() falls back to second candidate on failure.
 52.  FailoverStrategy.execute() raises when all candidates fail.
 53.  PolicyBasedSelector returns None when no providers configured.
 54.  CommandContext.with_metadata() returns new context with merged metadata.
 55.  CommandContext.with_device() returns new context with device_id set.
 56.  Backward compat: from core.command_router import get_command_router still works.
 57.  Backward compat: from core.multi_llm_router import MultiLLMRouter still works.
 58.  Backward compat: from core.llm import MultiLLMRouter still works.
 59.  CANONICAL_ENTRYPOINTS.md documents core/commands/ package.
 60.  CANONICAL_ENTRYPOINTS.md documents core/llm/ package.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path

# ── project root ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# =============================================================================
# Group 1: core/commands/ package
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 2: core/commands/router.py
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 3: core/commands/registry.py
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 4: core/commands/dispatcher.py
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 5: core/commands/context.py
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 6: core/commands/middleware.py
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 7: core/commands/validators/
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。

# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 8: core/commands/handlers/
# =============================================================================


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 9: core/llm/ package
# =============================================================================


class TestLLMPackageInit(unittest.TestCase):

    def test_31_llm_init_has_authority_sentinel(self):
        content = _read("core/llm/__init__.py")
        self.assertIn(
            "LLM_ROUTING_PACKAGE_AUTHORITY", content, "core/llm/__init__.py must define LLM_ROUTING_PACKAGE_AUTHORITY"
        )

    def test_32_llm_package_authority_value(self):
        from core.llm import LLM_ROUTING_PACKAGE_AUTHORITY

        self.assertEqual(
            LLM_ROUTING_PACKAGE_AUTHORITY,
            "core.llm",
            "LLM_ROUTING_PACKAGE_AUTHORITY must equal 'core.llm'",
        )

    def test_33_llm_init_reexports_multi_llm_router(self):
        from core.llm import MultiLLMRouter

        self.assertTrue(callable(MultiLLMRouter), "core.llm must re-export MultiLLMRouter")

    def test_34_llm_init_reexports_get_llm_router(self):
        from core.llm import get_llm_router


# 此处原有的用例引用了本批删除的零引用模块（审计报告产物 / 纯声明层 / 已被取代的
# 平行实现）。模块不存在后这些断言失去对象，随之移除；同文件其余用例保持不变。


# =============================================================================
# Group 15: backward compatibility
# =============================================================================


class TestBackwardCompatibility(unittest.TestCase):

    def test_56_core_command_router_get_command_router_still_works(self):
        from core.command_router import get_command_router

        self.assertTrue(callable(get_command_router), "core.command_router.get_command_router must remain importable")

    def test_57_core_multi_llm_router_still_importable(self):
        from core.multi_llm_router import MultiLLMRouter

        self.assertTrue(callable(MultiLLMRouter), "core.multi_llm_router.MultiLLMRouter must remain importable")

    def test_58_core_llm_multi_llm_router_importable(self):
        from core.llm import MultiLLMRouter

        self.assertTrue(callable(MultiLLMRouter), "from core.llm import MultiLLMRouter must remain importable")


# =============================================================================
# Group 16: architecture documentation
# =============================================================================


class TestArchitectureDocumentation(unittest.TestCase):

    def test_59_canonical_entrypoints_documents_commands_package(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("core/commands/", content, "CANONICAL_ENTRYPOINTS.md must document core/commands/ package")

    def test_60_canonical_entrypoints_documents_llm_package(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("core/llm/", content, "CANONICAL_ENTRYPOINTS.md must document core/llm/ package")


if __name__ == "__main__":
    unittest.main()
