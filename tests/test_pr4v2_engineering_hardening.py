"""
tests/test_pr4v2_engineering_hardening.py
==========================================

PR4V2 工程加固测试套件。

验证以下工程加固改动：

1. 启动预检严格失败模式（``GALAXY_STRICT_PREFLIGHT``）
2. 权限边界严格检查模式（``GALAXY_STRICT_AUTHORITY_CHECK``）
3. asyncio 边界修复（``asyncio.get_running_loop()`` 替代 ``get_event_loop()``）
4. ``core.final_code_only_dual_repo_audit`` 部署依赖条件处理
5. ``core.audit_layer`` 子包与向后兼容存根
6. ``pytest.ini`` 弃用噪声过滤
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# 1. 严格预检失败模式
# ---------------------------------------------------------------------------


class TestStrictPreflightMode:
    """``GALAXY_STRICT_PREFLIGHT`` 环境变量必须使预检异常变为硬失败。"""

    def test_strict_preflight_env_var_sentinel_declared(self):
        """``system_orchestrator`` 必须声明严格模式环境变量名称常量。"""
        from core.system_orchestrator import STRICT_PREFLIGHT_ENV_VAR
        assert STRICT_PREFLIGHT_ENV_VAR == "GALAXY_STRICT_PREFLIGHT"

    def test_strict_authority_check_env_var_sentinel_declared(self):
        """``system_orchestrator`` 必须声明严格权限检查环境变量名称常量。"""
        from core.system_orchestrator import STRICT_AUTHORITY_CHECK_ENV_VAR
        assert STRICT_AUTHORITY_CHECK_ENV_VAR == "GALAXY_STRICT_AUTHORITY_CHECK"

    def test_system_orchestrator_accepts_strict_preflight_kwarg(self):
        """``SystemOrchestrator.__init__`` 必须接受 ``strict_preflight`` 关键字参数。"""
        from core.system_orchestrator import SystemOrchestrator
        import inspect
        sig = inspect.signature(SystemOrchestrator.__init__)
        assert "strict_preflight" in sig.parameters, (
            "SystemOrchestrator.__init__ must accept strict_preflight keyword argument"
        )

    def test_strict_preflight_false_by_default(self):
        """默认情况下 ``strict_preflight`` 应为 ``False``（宽松模式）。"""
        old_val = os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
        try:
            from core.system_orchestrator import SystemOrchestrator
            orch = SystemOrchestrator()
            assert orch.strict_preflight is False, (
                "strict_preflight should be False by default when env var is not set"
            )
        finally:
            if old_val is not None:
                os.environ["GALAXY_STRICT_PREFLIGHT"] = old_val

    def test_strict_preflight_enabled_via_env_var(self):
        """设置 ``GALAXY_STRICT_PREFLIGHT=1`` 后，``strict_preflight`` 应为 ``True``。"""
        old_val = os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
        try:
            os.environ["GALAXY_STRICT_PREFLIGHT"] = "1"
            from core.system_orchestrator import SystemOrchestrator
            orch = SystemOrchestrator()
            assert orch.strict_preflight is True, (
                "strict_preflight should be True when GALAXY_STRICT_PREFLIGHT=1"
            )
        finally:
            os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
            if old_val is not None:
                os.environ["GALAXY_STRICT_PREFLIGHT"] = old_val

    def test_strict_preflight_kwarg_overrides_env_var(self):
        """显式传入 ``strict_preflight=True`` 时应覆盖环境变量。"""
        old_val = os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
        try:
            # env var absent but kwarg=True
            from core.system_orchestrator import SystemOrchestrator
            orch = SystemOrchestrator(strict_preflight=True)
            assert orch.strict_preflight is True
            # env var present but kwarg=False
            os.environ["GALAXY_STRICT_PREFLIGHT"] = "1"
            orch2 = SystemOrchestrator(strict_preflight=False)
            assert orch2.strict_preflight is False
        finally:
            os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
            if old_val is not None:
                os.environ["GALAXY_STRICT_PREFLIGHT"] = old_val

    def test_main_py_imports_os(self):
        """``main.py`` 必须导入 ``os`` 以读取 GALAXY_STRICT_PREFLIGHT 环境变量。"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_path = os.path.join(repo_root, "main.py")
        with open(main_path) as f:
            content = f.read()
        assert "import os" in content, "main.py must import os to support GALAXY_STRICT_PREFLIGHT"

    def test_main_py_references_strict_preflight(self):
        """``main.py`` 必须引用 GALAXY_STRICT_PREFLIGHT 以实现严格失败模式。"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_path = os.path.join(repo_root, "main.py")
        with open(main_path) as f:
            content = f.read()
        assert "GALAXY_STRICT_PREFLIGHT" in content, (
            "main.py must reference GALAXY_STRICT_PREFLIGHT for strict-failure mode"
        )

    def test_strict_mode_exception_returns_false(self):
        """严格模式下，当 ``SystemOrchestrator.run_startup_sequence()`` 抛出异常时，
        ``_run_orchestrator_preflight()`` 应返回 ``False``。
        """
        import main as main_module
        old_val = os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
        try:
            os.environ["GALAXY_STRICT_PREFLIGHT"] = "1"
            # Monkeypatch SystemOrchestrator.run_startup_sequence to raise
            import unittest.mock as mock
            with mock.patch(
                "core.system_orchestrator.SystemOrchestrator.run_startup_sequence",
                side_effect=RuntimeError("simulated critical failure"),
            ):
                # Re-import _is_strict_preflight and _run_orchestrator_preflight from main
                result = main_module._run_orchestrator_preflight()
            assert result is False, (
                "In strict mode, an unhandled preflight exception must return False"
            )
        finally:
            os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
            if old_val is not None:
                os.environ["GALAXY_STRICT_PREFLIGHT"] = old_val

    def test_non_strict_mode_exception_returns_true(self):
        """非严格模式下，当 ``run_startup_sequence()`` 抛出异常时，
        ``_run_orchestrator_preflight()`` 应仍返回 ``True``（降级但非失败）。
        """
        import main as main_module
        old_val = os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
        try:
            import unittest.mock as mock
            with mock.patch(
                "core.system_orchestrator.SystemOrchestrator.run_startup_sequence",
                side_effect=RuntimeError("simulated non-critical failure"),
            ):
                result = main_module._run_orchestrator_preflight()
            assert result is True, (
                "In non-strict mode, an unhandled preflight exception must still return True"
            )
        finally:
            os.environ.pop("GALAXY_STRICT_PREFLIGHT", None)
            if old_val is not None:
                os.environ["GALAXY_STRICT_PREFLIGHT"] = old_val


# ---------------------------------------------------------------------------
# 2. Asyncio 边界修复
# ---------------------------------------------------------------------------


class TestAsyncIoBoundaryHardening:
    """关键模块必须使用 ``asyncio.get_running_loop()`` 而非 ``asyncio.get_event_loop()``。"""

    def _read_source(self, rel_path: str) -> str:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(repo_root, rel_path)
        with open(full_path) as f:
            return f.read()

    def test_llm_manager_uses_get_running_loop(self):
        """``core/llm_manager.py`` 的 ``reload()`` 方法应使用 ``asyncio.get_running_loop()``。"""
        source = self._read_source("core/llm_manager.py")
        assert "asyncio.get_running_loop()" in source, (
            "core/llm_manager.py must use asyncio.get_running_loop() in reload()"
        )

    def test_llm_manager_does_not_use_deprecated_get_event_loop_in_reload(self):
        """``core/llm_manager.py`` 的 ``reload()`` 方法不应使用已弃用的 ``asyncio.get_event_loop()``。"""
        import ast
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(repo_root, "core/llm_manager.py")
        with open(full_path) as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            pytest.skip("Could not parse llm_manager.py as AST")
        # Find the reload method and collect all attribute accesses within it
        reload_node = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "reload":
                reload_node = node
                break
        if reload_node is None:
            pytest.skip("reload() method not found in llm_manager.py")
        deprecated_calls = [
            node for node in ast.walk(reload_node)
            if isinstance(node, ast.Attribute) and node.attr == "get_event_loop"
        ]
        assert not deprecated_calls, (
            "llm_manager.py reload() must not use deprecated asyncio.get_event_loop()"
        )

    def test_async_queue_uses_get_running_loop(self):
        """``core/queueing/async_queue.py`` 的 ``submit()`` 方法应使用 ``asyncio.get_running_loop()``。"""
        source = self._read_source("core/queueing/async_queue.py")
        assert "asyncio.get_running_loop()" in source, (
            "core/queueing/async_queue.py must use asyncio.get_running_loop() in submit()"
        )

    def test_ingest_runtime_uses_get_running_loop(self):
        """``core/multimodal/ingest_runtime.py`` 应使用 ``asyncio.get_running_loop()``。"""
        source = self._read_source("core/multimodal/ingest_runtime.py")
        assert "asyncio.get_running_loop()" in source, (
            "core/multimodal/ingest_runtime.py must use asyncio.get_running_loop()"
        )

    def test_audio_ingest_uses_get_running_loop(self):
        """``core/multimodal/audio_ingest.py`` 应使用 ``asyncio.get_running_loop()``。"""
        source = self._read_source("core/multimodal/audio_ingest.py")
        assert "asyncio.get_running_loop()" in source, (
            "core/multimodal/audio_ingest.py must use asyncio.get_running_loop()"
        )


# ---------------------------------------------------------------------------
# 3. 审计文件迁移到 core.audit_layer
# ---------------------------------------------------------------------------


class TestAuditLayerRelocation:
    """叙述性审计文件应已迁移到 ``core.audit_layer`` 子包。"""

    def test_audit_layer_package_exists(self):
        """``core/audit_layer/__init__.py`` 必须存在。"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        init_path = os.path.join(repo_root, "core", "audit_layer", "__init__.py")
        assert os.path.exists(init_path), "core/audit_layer/__init__.py must exist"

    def test_comprehensive_audit_in_audit_layer(self):
        """``core.audit_layer.comprehensive_joint_dual_repo_audit`` 必须可导入。"""
        m = importlib.import_module("core.audit_layer.comprehensive_joint_dual_repo_audit")
        assert m is not None

    def test_fresh_audit_in_audit_layer(self):
        """``core.audit_layer.fresh_dual_repo_code_audit`` 必须可导入。"""
        m = importlib.import_module("core.audit_layer.fresh_dual_repo_code_audit")
        assert m is not None

    def test_post_closure_reassessment_in_audit_layer(self):
        """``core.audit_layer.post_closure_dual_repo_reassessment`` 必须可导入。"""
        m = importlib.import_module("core.audit_layer.post_closure_dual_repo_reassessment")
        assert m is not None

    def test_stub_backward_compat_comprehensive(self):
        """``core.comprehensive_joint_dual_repo_audit`` 存根必须保持向后兼容性。"""
        m = importlib.import_module("core.comprehensive_joint_dual_repo_audit")
        assert m is not None

    def test_stub_backward_compat_post_closure(self):
        """``core.post_closure_dual_repo_reassessment`` 存根必须保持向后兼容性。"""
        m = importlib.import_module("core.post_closure_dual_repo_reassessment")
        assert m is not None

    def test_stub_backward_compat_pr993(self):
        """``core.pr993_dual_repo_reevaluation`` 存根必须保持向后兼容性。"""
        m = importlib.import_module("core.pr993_dual_repo_reevaluation")
        assert m is not None


# ---------------------------------------------------------------------------
# 4. final_code_only_dual_repo_audit 部署依赖条件处理
# ---------------------------------------------------------------------------


class TestAuditDeploymentConditionHandling:
    """当运行时依赖（如 ``fastapi``）未安装时，审计检查不应返回 ``passed=False``。"""

    def test_deployment_dep_error_helper_exists(self):
        """``core.final_code_only_dual_repo_audit`` 必须有 ``_deployment_dep_error`` 辅助函数。"""
        from core.final_code_only_dual_repo_audit import _deployment_dep_error
        assert callable(_deployment_dep_error)

    def test_deployment_dep_error_detects_fastapi(self):
        """``_deployment_dep_error`` 对 fastapi 的 ``ModuleNotFoundError`` 应返回 ``True``。"""
        from core.final_code_only_dual_repo_audit import _deployment_dep_error
        err = ModuleNotFoundError("No module named 'fastapi'")
        err.name = "fastapi"
        assert _deployment_dep_error(err) is True

    def test_deployment_dep_error_ignores_real_errors(self):
        """``_deployment_dep_error`` 对非依赖错误应返回 ``False``。"""
        from core.final_code_only_dual_repo_audit import _deployment_dep_error
        # AttributeError is not a deployment dep error
        assert _deployment_dep_error(AttributeError("some_attr missing")) is False
        # ModuleNotFoundError for a non-deployment module is not a dep error
        err = ModuleNotFoundError("No module named 'my_custom_module'")
        err.name = "my_custom_module"
        assert _deployment_dep_error(err) is False

    def test_fastapi_availability_flag_exists(self):
        """``_FASTAPI_AVAILABLE`` 标志必须存在。"""
        from core.final_code_only_dual_repo_audit import _FASTAPI_AVAILABLE
        assert isinstance(_FASTAPI_AVAILABLE, bool)

    def test_all_checks_pass_when_fastapi_missing(self):
        """当 fastapi 不可用时，所有依赖 fastapi 的审计检查必须返回 ``passed=True``（部署条件）。"""
        fastapi_available = importlib.util.find_spec("fastapi") is not None
        if fastapi_available:
            pytest.skip("fastapi is installed — test only applies when fastapi is absent")

        from core.final_code_only_dual_repo_audit import (
            check_canonical_ws_ingress,
            check_handler_registration_completeness,
            check_reconciliation_signal_handler_wired,
            check_handoff_v2_result_handler_wired,
            check_reconnect_canonical_path_sentinel,
        )
        for check_fn in [
            check_canonical_ws_ingress,
            check_handler_registration_completeness,
            check_reconciliation_signal_handler_wired,
            check_handoff_v2_result_handler_wired,
            check_reconnect_canonical_path_sentinel,
        ]:
            result = check_fn()
            assert result.passed, (
                f"{check_fn.__name__} must return passed=True when fastapi is absent "
                f"(deployment condition), got: {result.failure_detail}"
            )
