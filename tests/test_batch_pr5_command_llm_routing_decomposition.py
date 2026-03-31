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
from pathlib import Path
import unittest

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

class TestCommandsPackageInit(unittest.TestCase):

    def test_01_commands_init_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "__init__.py").exists(),
            "core/commands/__init__.py must exist",
        )

    def test_02_commands_init_has_authority_sentinel(self):
        content = _read("core/commands/__init__.py")
        self.assertIn("COMMAND_ROUTING_PACKAGE_AUTHORITY", content,
                      "core/commands/__init__.py must define COMMAND_ROUTING_PACKAGE_AUTHORITY")

    def test_03_authority_value_is_core_commands(self):
        from core.commands import COMMAND_ROUTING_PACKAGE_AUTHORITY
        self.assertEqual(
            COMMAND_ROUTING_PACKAGE_AUTHORITY,
            "core.commands",
            "COMMAND_ROUTING_PACKAGE_AUTHORITY must equal 'core.commands'",
        )

    def test_04_commands_init_reexports_command_router(self):
        from core.commands import CommandRouter
        self.assertTrue(callable(CommandRouter),
                        "core.commands must re-export CommandRouter")

    def test_05_commands_init_reexports_get_command_router(self):
        from core.commands import get_command_router
        self.assertTrue(callable(get_command_router),
                        "core.commands must re-export get_command_router callable")


# =============================================================================
# Group 2: core/commands/router.py
# =============================================================================

class TestCommandsRouterModule(unittest.TestCase):

    def test_06_commands_router_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "router.py").exists(),
            "core/commands/router.py must exist",
        )

    def test_07_commands_router_has_authority_sentinel(self):
        content = _read("core/commands/router.py")
        self.assertIn("COMMAND_ROUTER_AUTHORITY", content,
                      "core/commands/router.py must define COMMAND_ROUTER_AUTHORITY")

    def test_08_command_router_authority_value(self):
        from core.commands.router import COMMAND_ROUTER_AUTHORITY
        self.assertEqual(
            COMMAND_ROUTER_AUTHORITY,
            "core.commands.router",
            "COMMAND_ROUTER_AUTHORITY must equal 'core.commands.router'",
        )

    def test_09_commands_router_reexports_get_command_router(self):
        from core.commands.router import get_command_router
        self.assertTrue(callable(get_command_router),
                        "core.commands.router must re-export get_command_router")


# =============================================================================
# Group 3: core/commands/registry.py
# =============================================================================

class TestCommandRegistryModule(unittest.TestCase):

    def test_10_registry_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "registry.py").exists(),
            "core/commands/registry.py must exist",
        )

    def test_11_registry_has_authority_sentinel(self):
        content = _read("core/commands/registry.py")
        self.assertIn("COMMAND_REGISTRY_AUTHORITY", content,
                      "core/commands/registry.py must define COMMAND_REGISTRY_AUTHORITY")

    def test_12_registry_defines_command_registry_class(self):
        from core.commands.registry import CommandRegistry
        self.assertTrue(
            isinstance(CommandRegistry, type),
            "core.commands.registry must define CommandRegistry class",
        )

    def test_13_registry_register_get_list_interface(self):
        from core.commands.registry import CommandRegistry

        registry = CommandRegistry(name="test")
        called = []

        @registry.register("ping")
        async def _ping(ctx, params):
            called.append("ping")
            return {"pong": True}

        self.assertTrue(registry.has("ping"))
        self.assertIn("ping", registry.list_commands())
        handler = registry.get("ping")
        self.assertIs(handler, _ping)


# =============================================================================
# Group 4: core/commands/dispatcher.py
# =============================================================================

class TestCommandDispatcherModule(unittest.TestCase):

    def test_14_dispatcher_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "dispatcher.py").exists(),
            "core/commands/dispatcher.py must exist",
        )

    def test_15_dispatcher_has_authority_sentinel(self):
        content = _read("core/commands/dispatcher.py")
        self.assertIn("COMMAND_DISPATCHER_AUTHORITY", content,
                      "core/commands/dispatcher.py must define COMMAND_DISPATCHER_AUTHORITY")

    def test_16_dispatcher_defines_class(self):
        from core.commands.dispatcher import CommandDispatcher
        self.assertTrue(
            isinstance(CommandDispatcher, type),
            "core.commands.dispatcher must define CommandDispatcher class",
        )


# =============================================================================
# Group 5: core/commands/context.py
# =============================================================================

class TestCommandContextModule(unittest.TestCase):

    def test_17_context_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "context.py").exists(),
            "core/commands/context.py must exist",
        )

    def test_18_context_has_authority_sentinel(self):
        content = _read("core/commands/context.py")
        self.assertIn("COMMAND_CONTEXT_AUTHORITY", content,
                      "core/commands/context.py must define COMMAND_CONTEXT_AUTHORITY")

    def test_19_context_defines_command_context_dataclass(self):
        from core.commands.context import CommandContext
        ctx = CommandContext(source="test", command="ping")
        self.assertEqual(ctx.source, "test")
        self.assertEqual(ctx.command, "ping")
        self.assertIsNotNone(ctx.trace_id)
        self.assertIsNotNone(ctx.request_id)

    def test_20_context_from_request_factory(self):
        from core.commands.context import CommandContext
        from core.commands import CommandRequest

        req = CommandRequest(
            source="api",
            command="screenshot",
            targets=["device-1"],
            metadata={"trace_id": "trc_abc123", "user_id": "u1"},
        )
        ctx = CommandContext.from_request(req)
        self.assertEqual(ctx.trace_id, "trc_abc123")
        self.assertEqual(ctx.source, "api")
        self.assertEqual(ctx.command, "screenshot")


# =============================================================================
# Group 6: core/commands/middleware.py
# =============================================================================

class TestCommandMiddlewareModule(unittest.TestCase):

    def test_21_middleware_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "middleware.py").exists(),
            "core/commands/middleware.py must exist",
        )

    def test_22_middleware_has_authority_sentinel(self):
        content = _read("core/commands/middleware.py")
        self.assertIn("COMMAND_MIDDLEWARE_AUTHORITY", content,
                      "core/commands/middleware.py must define COMMAND_MIDDLEWARE_AUTHORITY")

    def test_23_middleware_defines_abc(self):
        import abc
        from core.commands.middleware import CommandMiddleware
        self.assertTrue(
            issubclass(CommandMiddleware, abc.ABC),
            "CommandMiddleware must be an abstract base class",
        )


# =============================================================================
# Group 7: core/commands/validators/
# =============================================================================

class TestCommandValidatorsSubpackage(unittest.TestCase):

    def test_24_validators_init_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "validators" / "__init__.py").exists(),
            "core/commands/validators/__init__.py must exist",
        )

    def test_25_validators_has_authority_sentinel(self):
        content = _read("core/commands/validators/__init__.py")
        self.assertIn("COMMAND_VALIDATOR_AUTHORITY", content,
                      "core/commands/validators/__init__.py must define COMMAND_VALIDATOR_AUTHORITY")

    def test_26_envelope_validator_rejects_empty_device_id(self):
        from core.commands.validators import EnvelopeValidator, ValidationError

        validator = EnvelopeValidator()
        with self.assertRaises(ValidationError):
            validator.validate(
                command="screenshot",
                device_id="",   # empty — should fail
                command_id="c1",
                task_id="t1",
            )

    def test_27_risk_validator_rejects_high_risk_command(self):
        from core.commands.validators import RiskClassificationValidator, ValidationError

        validator = RiskClassificationValidator()
        with self.assertRaises(ValidationError):
            validator.validate(command="delete")

    def test_28_risk_validator_allows_override(self):
        from core.commands.validators import RiskClassificationValidator

        validator = RiskClassificationValidator()
        # Should NOT raise when allow_high_risk=True
        validator.validate(
            command="delete",
            context_metadata={"allow_high_risk": True},
        )


# =============================================================================
# Group 8: core/commands/handlers/
# =============================================================================

class TestCommandHandlersSubpackage(unittest.TestCase):

    def test_29_handlers_init_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "commands" / "handlers" / "__init__.py").exists(),
            "core/commands/handlers/__init__.py must exist",
        )

    def test_30_handlers_has_authority_sentinel(self):
        content = _read("core/commands/handlers/__init__.py")
        self.assertIn("COMMAND_HANDLER_AUTHORITY", content,
                      "core/commands/handlers/__init__.py must define COMMAND_HANDLER_AUTHORITY")


# =============================================================================
# Group 9: core/llm/ package
# =============================================================================

class TestLLMPackageInit(unittest.TestCase):

    def test_31_llm_init_has_authority_sentinel(self):
        content = _read("core/llm/__init__.py")
        self.assertIn("LLM_ROUTING_PACKAGE_AUTHORITY", content,
                      "core/llm/__init__.py must define LLM_ROUTING_PACKAGE_AUTHORITY")

    def test_32_llm_package_authority_value(self):
        from core.llm import LLM_ROUTING_PACKAGE_AUTHORITY
        self.assertEqual(
            LLM_ROUTING_PACKAGE_AUTHORITY,
            "core.llm",
            "LLM_ROUTING_PACKAGE_AUTHORITY must equal 'core.llm'",
        )

    def test_33_llm_init_reexports_multi_llm_router(self):
        from core.llm import MultiLLMRouter
        self.assertTrue(callable(MultiLLMRouter),
                        "core.llm must re-export MultiLLMRouter")

    def test_34_llm_init_reexports_get_llm_router(self):
        from core.llm import get_llm_router
        self.assertTrue(callable(get_llm_router),
                        "core.llm must re-export get_llm_router callable")


# =============================================================================
# Group 10: core/llm/router.py
# =============================================================================

class TestLLMRouterModule(unittest.TestCase):

    def test_35_llm_router_has_authority_sentinel(self):
        content = _read("core/llm/router.py")
        self.assertIn("LLM_ROUTER_AUTHORITY", content,
                      "core/llm/router.py must define LLM_ROUTER_AUTHORITY")

    def test_36_llm_router_authority_value(self):
        from core.llm.router import LLM_ROUTER_AUTHORITY
        self.assertEqual(
            LLM_ROUTER_AUTHORITY,
            "core.llm.router",
            "LLM_ROUTER_AUTHORITY must equal 'core.llm.router'",
        )


# =============================================================================
# Group 11: core/llm/policies.py
# =============================================================================

class TestLLMPoliciesModule(unittest.TestCase):

    def test_37_policies_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "llm" / "policies.py").exists(),
            "core/llm/policies.py must exist",
        )

    def test_38_policies_has_authority_sentinel(self):
        content = _read("core/llm/policies.py")
        self.assertIn("LLM_POLICIES_AUTHORITY", content,
                      "core/llm/policies.py must define LLM_POLICIES_AUTHORITY")

    def test_39_policies_reexports_task_routing_preferences(self):
        from core.llm.policies import TASK_ROUTING_PREFERENCES
        self.assertIsInstance(TASK_ROUTING_PREFERENCES, dict,
                              "TASK_ROUTING_PREFERENCES must be a dict")
        self.assertTrue(len(TASK_ROUTING_PREFERENCES) > 0,
                        "TASK_ROUTING_PREFERENCES must not be empty")

    def test_40_policies_defines_policy_based_selector(self):
        from core.llm.policies import PolicyBasedSelector
        self.assertTrue(
            isinstance(PolicyBasedSelector, type),
            "core.llm.policies must define PolicyBasedSelector class",
        )


# =============================================================================
# Group 12: core/llm/failover.py
# =============================================================================

class TestLLMFailoverModule(unittest.TestCase):

    def test_41_failover_module_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "llm" / "failover.py").exists(),
            "core/llm/failover.py must exist",
        )

    def test_42_failover_has_authority_sentinel(self):
        content = _read("core/llm/failover.py")
        self.assertIn("LLM_FAILOVER_AUTHORITY", content,
                      "core/llm/failover.py must define LLM_FAILOVER_AUTHORITY")

    def test_43_failover_defines_failover_strategy(self):
        from core.llm.failover import FailoverStrategy
        self.assertTrue(
            isinstance(FailoverStrategy, type),
            "core.llm.failover must define FailoverStrategy class",
        )

    def test_44_failover_defines_retry_policy(self):
        from core.llm.failover import RetryPolicy
        policy = RetryPolicy(max_retries=3, base_delay_s=0.1)
        self.assertEqual(policy.max_retries, 3)
        delay = policy.compute_delay(0)
        self.assertGreater(delay, 0)


# =============================================================================
# Group 13: core/llm/providers/
# =============================================================================

class TestLLMProvidersSubpackage(unittest.TestCase):

    def test_45_providers_init_exists(self):
        self.assertTrue(
            (PROJECT_ROOT / "core" / "llm" / "providers" / "__init__.py").exists(),
            "core/llm/providers/__init__.py must exist",
        )

    def test_46_providers_has_authority_sentinel(self):
        content = _read("core/llm/providers/__init__.py")
        self.assertIn("LLM_PROVIDERS_AUTHORITY", content,
                      "core/llm/providers/__init__.py must define LLM_PROVIDERS_AUTHORITY")

    def test_47_providers_reexports_base_adapter(self):
        from core.llm.providers import BaseProviderAdapter
        self.assertTrue(callable(BaseProviderAdapter),
                        "core.llm.providers must re-export BaseProviderAdapter")

    def test_48_providers_reexports_openai_adapter(self):
        from core.llm.providers import OpenAIAdapter
        self.assertTrue(callable(OpenAIAdapter),
                        "core.llm.providers must re-export OpenAIAdapter")


# =============================================================================
# Group 14: functional validation
# =============================================================================

class TestCommandRegistryFunctional(unittest.TestCase):

    def test_49_registry_register_decorator_end_to_end(self):
        from core.commands.registry import CommandRegistry

        registry = CommandRegistry(name="functional-test")
        results = []

        @registry.register("test_cmd", required_capabilities=["screen"])
        async def _handle(ctx, params):
            results.append(params)
            return {"ok": True}

        self.assertTrue(registry.has("test_cmd"))
        self.assertEqual(
            registry.get_required_capabilities("test_cmd"),
            ["screen"],
        )
        handler = registry.get("test_cmd")
        self.assertIs(handler, _handle)
        self.assertEqual(len(registry), 1)
        registry.unregister("test_cmd")
        self.assertFalse(registry.has("test_cmd"))


class TestFailoverStrategyFunctional(unittest.TestCase):

    def test_50_failover_succeeds_on_first_candidate(self):
        from core.llm.failover import FailoverStrategy

        strategy = FailoverStrategy()

        async def _call(provider, model, req):
            return {"provider": provider, "model": model, "ok": True}

        result = _run(strategy.execute(
            candidates=[("openai", "gpt-4o"), ("anthropic", "claude-sonnet")],
            call=_call,
            request={"messages": []},
        ))
        self.assertEqual(result["provider"], "openai")

    def test_51_failover_falls_back_to_second_candidate(self):
        from core.llm.failover import FailoverStrategy, RetryPolicy

        policy = RetryPolicy(max_retries=2, base_delay_s=0.0, jitter=False)
        strategy = FailoverStrategy(retry_policy=policy)
        call_log = []

        async def _call(provider, model, req):
            call_log.append(provider)
            if provider == "openai":
                raise RuntimeError("openai down")
            return {"provider": provider, "ok": True}

        result = _run(strategy.execute(
            candidates=[("openai", "gpt-4o"), ("anthropic", "claude-sonnet")],
            call=_call,
            request={},
        ))
        self.assertEqual(result["provider"], "anthropic")
        self.assertIn("openai", call_log)

    def test_52_failover_raises_when_all_fail(self):
        from core.llm.failover import FailoverStrategy, RetryPolicy

        policy = RetryPolicy(max_retries=1, base_delay_s=0.0, jitter=False)
        strategy = FailoverStrategy(retry_policy=policy)

        async def _call(provider, model, req):
            raise RuntimeError(f"{provider} always fails")

        with self.assertRaises(RuntimeError):
            _run(strategy.execute(
                candidates=[("openai", "gpt-4o"), ("anthropic", "claude-sonnet")],
                call=_call,
                request={},
            ))


class TestPolicyBasedSelectorFunctional(unittest.TestCase):

    def test_53_selector_returns_none_when_no_providers(self):
        from core.llm.policies import PolicyBasedSelector
        from core.multi_llm_router import TaskType

        selector = PolicyBasedSelector(providers={})
        result = selector.select(TaskType.GENERAL)
        self.assertIsNone(result,
                          "PolicyBasedSelector should return None when no providers configured")


class TestCommandContextFunctional(unittest.TestCase):

    def test_54_context_with_metadata_immutable(self):
        from core.commands.context import CommandContext

        ctx = CommandContext(source="api", command="ping")
        ctx2 = ctx.with_metadata(user_id="u1", extra="value")
        # original unchanged
        self.assertNotIn("user_id", ctx.metadata)
        self.assertEqual(ctx2.metadata.get("user_id"), "u1")
        self.assertEqual(ctx2.metadata.get("extra"), "value")
        self.assertEqual(ctx2.trace_id, ctx.trace_id)

    def test_55_context_with_device_sets_device_id(self):
        from core.commands.context import CommandContext

        ctx = CommandContext(source="api", command="screenshot")
        ctx2 = ctx.with_device("phone-1")
        self.assertEqual(ctx2.device_id, "phone-1")
        self.assertIsNone(ctx.device_id)


# =============================================================================
# Group 15: backward compatibility
# =============================================================================

class TestBackwardCompatibility(unittest.TestCase):

    def test_56_core_command_router_get_command_router_still_works(self):
        from core.command_router import get_command_router
        self.assertTrue(callable(get_command_router),
                        "core.command_router.get_command_router must remain importable")

    def test_57_core_multi_llm_router_still_importable(self):
        from core.multi_llm_router import MultiLLMRouter
        self.assertTrue(callable(MultiLLMRouter),
                        "core.multi_llm_router.MultiLLMRouter must remain importable")

    def test_58_core_llm_multi_llm_router_importable(self):
        from core.llm import MultiLLMRouter
        self.assertTrue(callable(MultiLLMRouter),
                        "from core.llm import MultiLLMRouter must remain importable")


# =============================================================================
# Group 16: architecture documentation
# =============================================================================

class TestArchitectureDocumentation(unittest.TestCase):

    def test_59_canonical_entrypoints_documents_commands_package(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("core/commands/", content,
                      "CANONICAL_ENTRYPOINTS.md must document core/commands/ package")

    def test_60_canonical_entrypoints_documents_llm_package(self):
        content = _read("docs/architecture/CANONICAL_ENTRYPOINTS.md")
        self.assertIn("core/llm/", content,
                      "CANONICAL_ENTRYPOINTS.md must document core/llm/ package")


if __name__ == "__main__":
    unittest.main()
