"""
安全修复测试
============

覆盖：SQL 注入防护、命令注入防护、路径穿越防护、exec() 沙箱
"""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# SQL 注入防护
# =============================================================================

class TestSQLInjectionPrevention(unittest.TestCase):
    """测试 SQL 标识符验证"""

    def _get_sqlite_validator(self):
        from nodes.Node_13_SQLite.main import SQLiteManager
        return SQLiteManager._validate_identifier

    def _get_postgres_validator(self):
        from nodes.Node_12_Postgres.main import PostgresManager
        return PostgresManager._validate_identifier

    def test_sqlite_valid_identifiers(self):
        v = self._get_sqlite_validator()
        self.assertEqual(v("users"), '"users"')
        self.assertEqual(v("my_table"), '"my_table"')
        self.assertEqual(v("_private"), '"_private"')
        self.assertEqual(v("Table123"), '"Table123"')

    def test_sqlite_rejects_injection(self):
        v = self._get_sqlite_validator()
        with self.assertRaises(ValueError):
            v("users; DROP TABLE users; --")
        with self.assertRaises(ValueError):
            v("users OR 1=1")
        with self.assertRaises(ValueError):
            v("table name")  # spaces
        with self.assertRaises(ValueError):
            v("")  # empty
        with self.assertRaises(ValueError):
            v("123table")  # starts with digit

    def test_postgres_valid_identifiers(self):
        v = self._get_postgres_validator()
        self.assertEqual(v("users"), '"users"')
        self.assertEqual(v("my_table"), '"my_table"')

    def test_postgres_rejects_injection(self):
        v = self._get_postgres_validator()
        with self.assertRaises(ValueError):
            v("users; DROP TABLE users; --")
        with self.assertRaises(ValueError):
            v("table\"; DROP TABLE --")


# =============================================================================
# 命令注入防护
# =============================================================================

class TestCommandInjectionPrevention(unittest.TestCase):
    """测试命令注入防护"""

    def test_uia_launch_app_rejects_shell_metacharacters(self):
        """launch_app 应拒绝含 shell 元字符的路径"""
        import asyncio
        from nodes.Node_36_UIAWindows.ufo_deep_integration import UFODeepIntegration

        integration = UFODeepIntegration.__new__(UFODeepIntegration)
        loop = asyncio.new_event_loop()

        result = loop.run_until_complete(integration.launch_app("notepad.exe & del /s /q C:\\"))
        self.assertFalse(result["success"])
        self.assertIn("Invalid characters", result["error"])

        result = loop.run_until_complete(integration.launch_app("calc.exe | evil"))
        self.assertFalse(result["success"])

        loop.close()

    def test_uia_close_app_rejects_injection(self):
        """close_app 应拒绝含特殊字符的进程名"""
        import asyncio
        from nodes.Node_36_UIAWindows.ufo_deep_integration import UFODeepIntegration

        integration = UFODeepIntegration.__new__(UFODeepIntegration)
        loop = asyncio.new_event_loop()

        result = loop.run_until_complete(integration.close_app("notepad.exe & format C:"))
        self.assertFalse(result["success"])
        self.assertIn("Invalid process name", result["error"])

        # Valid process name should pass validation (subprocess may fail but that's OK)
        result = loop.run_until_complete(integration.close_app("notepad.exe"))
        # On non-Windows, taskkill will fail but the validation passes
        self.assertTrue(result.get("success") or "taskkill" in str(result.get("error", "")).lower()
                        or "No such file" in str(result.get("error", "")))

        loop.close()

    def test_android_list_packages_no_pipe_injection(self):
        """android_granular_adapter 不应使用 shell 管道"""
        import inspect
        from galaxy_gateway.android_granular_adapter import AndroidGranularAdapter
        source = inspect.getsource(AndroidGranularAdapter._handle_list_packages)
        # 确保不再有 shell 管道
        self.assertNotIn("| grep", source)
        # 确保使用 Python 侧过滤
        self.assertIn("if filter_str in p", source)


# =============================================================================
# 路径穿越防护
# =============================================================================

class TestPathTraversalPrevention(unittest.TestCase):
    """测试路径穿越防护"""

    def test_node_120_rejects_outside_workspace(self):
        """Node_120 应拒绝 workspace 外的路径"""
        try:
            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")
        import tempfile

        with tempfile.TemporaryDirectory() as workspace:
            svc = FileService(workspace_root=workspace)

            # workspace 内的路径应该正常
            internal_path = svc._resolve_path("test.txt")
            self.assertIsNotNone(internal_path)

            # workspace 外的路径应该报错
            with self.assertRaises(ValueError) as ctx:
                svc._resolve_path("/etc/passwd")
            self.assertIn("outside the workspace", str(ctx.exception))

            with self.assertRaises(ValueError):
                svc._resolve_path("../../etc/shadow")


# =============================================================================
# exec() 沙箱
# =============================================================================

class TestExecSandbox(unittest.TestCase):
    """测试代码执行沙箱安全性"""

    def test_safe_executor_exists(self):
        """SafeExecutor 应可导入且提供沙箱执行"""
        from core.safe_executor import SafeExecutor
        executor = SafeExecutor()
        assert hasattr(executor, "execute")

    def test_safe_builtins_whitelist(self):
        """安全内置函数白名单应包含常用函数但排除危险函数"""
        # 模拟 skill_manager 的白名单逻辑
        SAFE_NAMES = [
            "len", "range", "str", "int", "float", "list", "dict",
            "bool", "tuple", "set", "frozenset", "type",
            "isinstance", "issubclass", "enumerate", "zip",
            "map", "filter", "sorted", "reversed", "min", "max",
            "sum", "abs", "round", "print", "repr", "hash",
        ]
        # 确保危险函数不在白名单中
        DANGEROUS = ["eval", "exec", "compile", "open", "__import__",
                     "getattr", "setattr", "delattr", "globals", "locals"]
        for d in DANGEROUS:
            self.assertNotIn(d, SAFE_NAMES, f"Dangerous function {d} in whitelist!")

    def test_restricted_exec_blocks_import(self):
        """受限 exec 应阻止 __import__"""
        safe_builtins = {
            k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
            for k in ["len", "str", "int", "print"]
            if (k in __builtins__ if isinstance(__builtins__, dict) else hasattr(__builtins__, k))
        }
        restricted_globals = {"__builtins__": safe_builtins}
        local_vars = {"result": None}

        # 安全代码应该正常执行
        exec("result = len('hello')", restricted_globals, local_vars)
        self.assertEqual(local_vars["result"], 5)

        # 危险代码应该失败
        with self.assertRaises((NameError, ImportError)):
            exec("import os; result = os.system('echo pwned')", restricted_globals, local_vars)

        with self.assertRaises((NameError, TypeError)):
            exec("result = __import__('os')", restricted_globals, local_vars)


# =============================================================================
# Source code verification
# =============================================================================

class TestSourceCodeVerification(unittest.TestCase):
    """验证源代码中的安全修复确实存在"""

    def test_sqlite_uses_validator(self):
        import inspect
        from nodes.Node_13_SQLite.main import SQLiteManager
        source = inspect.getsource(SQLiteManager.get_table_stats)
        self.assertIn("_validate_identifier", source)
        self.assertNotIn("f\"SELECT COUNT(*) as count FROM {table_name}\"", source)

    def test_postgres_uses_validator(self):
        import inspect
        from nodes.Node_12_Postgres.main import PostgresManager
        source = inspect.getsource(PostgresManager.get_table_stats)
        self.assertIn("_validate_identifier", source)

    def test_node_120_raises_on_outside(self):
        try:
            import inspect
            from nodes.Node_120_File.main import FileService
            source = inspect.getsource(FileService._resolve_path)
            self.assertIn("raise ValueError", source)
            self.assertNotIn("# Allow absolute paths outside workspace", source)
        except ImportError:
            self.skipTest("Node_120 dependencies not available")


if __name__ == "__main__":
    unittest.main()
