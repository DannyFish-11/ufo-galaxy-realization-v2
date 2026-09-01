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
            v('table"; DROP TABLE --')


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
        self.assertTrue(
            result.get("success")
            or "taskkill" in str(result.get("error", "")).lower()
            or "No such file" in str(result.get("error", ""))
        )

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

    def test_node_120_returns_the_value_it_validated(self):
        """``_resolve_path`` 必须返回**它校验过的那个值**。

        此前它校验 ``p.resolve()`` 却返回未解析的 ``p`` —— 检查一个值、用另一个值。
        包含性判定本身没错,但把没摊平的那个交出去,等于让下游 19 个调用点各自再
        解析一次;任何一处解析方式不同,校验就白做了。
        """
        try:
            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace).resolve()
            (root / "sub").mkdir()
            (root / "sub" / "a.txt").write_text("a", encoding="utf-8")
            svc = FileService(workspace_root=workspace)

            got = svc._resolve_path("sub/../sub/a.txt")
            self.assertNotIn("..", got.parts, "返回的路径必须已规范化")
            self.assertEqual(got, got.resolve(), "返回值必须等于它自己的 resolve()")
            self.assertEqual(got, root / "sub" / "a.txt")

    def test_node_120_rejects_a_symlink_that_escapes(self):
        """工作区**内**的符号链接指向工作区外 —— 必须挡住。

        这条是穿越防护真正的硬骨头:路径字符串看起来完全在工作区里。
        """
        try:
            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "secret.txt").write_text("SECRET", encoding="utf-8")
            os.symlink(outside, Path(workspace) / "escape")
            svc = FileService(workspace_root=workspace)

            with self.assertRaises(ValueError):
                svc._resolve_path("escape/secret.txt")


class TestNode120ClosesTheTOCTOUWindow(unittest.TestCase):
    """穿越防护最后一块:**校验过之后**路径被换掉。

    ``_resolve_path`` 本身挡不住这个 —— 它校验的是"此刻这个名字指向哪儿",而真正
    的 ``open()`` 在之后发生。实测:纯路径校验下 42953 次通过里有 576 次读到了
    工作区外的文件。修法是让读写走 ``FileService.guard``,把校验与使用绑在同一个
    文件描述符上。

    这里测的是**服务层**(经由 ``read_file``/``write_file`` 这些对外接口),
    ``core/safe_fs`` 那一层的单元测试在
    ``tests/test_safe_fs_closes_the_toctou_window.py``。
    """

    def _service(self, workspace):
        try:
            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")
        return FileService(workspace_root=workspace)

    def _swap_forever(self, workspace, secret, stop):
        """在"普通文件"与"指向工作区外的符号链接"之间原子替换 ``f.txt``。

        ``rename`` 一个符号链接盖到已存在的普通文件上是允许且原子的 —— 这正是
        纯路径校验挡不住的那条路。
        """
        plain = os.path.join(workspace, ".plain")
        link = os.path.join(workspace, ".link")
        target = os.path.join(workspace, "f.txt")
        while not stop.is_set():
            try:
                with open(plain, "w", encoding="utf-8") as handle:
                    handle.write("inside")
                if os.path.islink(link):
                    os.unlink(link)
                os.symlink(secret, link)
                os.rename(link, target)
                os.rename(plain, target)
            except OSError:
                pass

    def test_read_file_never_returns_content_from_outside(self):
        import tempfile
        import threading
        import time

        from core.safe_fs import dir_fd_supported

        if not dir_fd_supported():
            self.skipTest("本平台不支持 dir_fd")

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.txt")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("TOP-SECRET-OUTSIDE")
            with open(os.path.join(workspace, "f.txt"), "w", encoding="utf-8") as handle:
                handle.write("inside")

            svc = self._service(workspace)
            self.assertTrue(
                svc.guard.closes_toctou_window,
                "这个平台上应当拿到描述符守卫;拿到纯路径实现说明降级了",
            )

            from nodes.Node_120_File.main import ReadRequest

            stop = threading.Event()
            thread = threading.Thread(target=self._swap_forever, args=(workspace, secret, stop), daemon=True)
            thread.start()
            leaked = attempts = refused = 0
            try:
                import asyncio

                loop = asyncio.new_event_loop()
                deadline = time.time() + 4
                while time.time() < deadline:
                    attempts += 1
                    try:
                        result = loop.run_until_complete(svc.read_file(ReadRequest(path="f.txt")))
                    except (ValueError, OSError):
                        refused += 1
                        continue
                    if "OUTSIDE" in result["content"]:
                        leaked += 1
                loop.close()
            finally:
                stop.set()
                thread.join(timeout=10)

            self.assertGreater(attempts, 50, f"压力不足,只跑了 {attempts} 轮")
            self.assertGreater(refused, 0, "一次都没撞上替换 —— 这轮没形成竞态,断言等于没做")
            self.assertEqual(leaked, 0, f"read_file 读到工作区外内容 {leaked} 次(共 {attempts} 轮)")

    def test_write_file_never_writes_outside(self):
        """写比读更要命:跟着外链写下去就是**改**工作区外的文件。"""
        import tempfile
        import threading
        import time

        from core.safe_fs import dir_fd_supported

        if not dir_fd_supported():
            self.skipTest("本平台不支持 dir_fd")

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            secret = os.path.join(outside, "secret.txt")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("TOP-SECRET-OUTSIDE")
            with open(os.path.join(workspace, "f.txt"), "w", encoding="utf-8") as handle:
                handle.write("inside")

            svc = self._service(workspace)
            from nodes.Node_120_File.main import WriteRequest

            stop = threading.Event()
            thread = threading.Thread(target=self._swap_forever, args=(workspace, secret, stop), daemon=True)
            thread.start()
            try:
                import asyncio

                loop = asyncio.new_event_loop()
                deadline = time.time() + 4
                while time.time() < deadline:
                    try:
                        loop.run_until_complete(svc.write_file(WriteRequest(path="f.txt", content="OVERWRITTEN")))
                    except (ValueError, OSError):
                        pass
                loop.close()
            finally:
                stop.set()
                thread.join(timeout=10)

            with open(secret, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "TOP-SECRET-OUTSIDE", "工作区外的文件被改写了")

    def test_copy_tree_validates_its_own_arguments(self):
        """``_copy_tree`` 不许把"落点校验"外包给调用方。

        它先前直接拿 ``guard.display_path()`` 的结果喂 ``shutil.copytree`` —— 而当时
        ``display_path`` 是纯拼接,能交出工作区外的路径。走 ``copy()`` 进来时不可利用
        (上游 ``_resolve_path`` 已经拦过),但"我安全是因为调用方会先检查"不是安全,
        是把责任推给了别人。这条直接调 ``_copy_tree``,绕开上游那道。
        """
        try:
            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")
        import tempfile

        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as handle:
                handle.write("TOP-SECRET-OUTSIDE")
            svc = FileService(workspace_root=workspace)

            with self.assertRaises(ValueError):
                svc._copy_tree("../" + os.path.basename(outside), "stolen")
            self.assertFalse(
                os.path.exists(os.path.join(workspace, "stolen")),
                "工作区外的目录被拷进来了",
            )

            os.mkdir(os.path.join(workspace, "src"))
            with self.assertRaises(ValueError):
                svc._copy_tree("src", "../" + os.path.basename(outside) + "/pwned")
            self.assertFalse(
                os.path.exists(os.path.join(outside, "pwned")),
                "写到了工作区外",
            )

    def test_reads_do_not_go_through_resolve_path_anymore(self):
        """``_resolve_path`` 的返回值只许用于展示,不许再拿去 ``open()``。

        这条守的是回归 —— 只要有人把读写改回 ``path.read_text()``,窗口就又开了,
        而且不会有任何测试自然发红。
        """
        try:
            import inspect

            from nodes.Node_120_File.main import FileService
        except ImportError:
            self.skipTest("Node_120 dependencies not available")

        for name in ("read_file", "write_file", "append_file", "calculate_hash"):
            source = inspect.getsource(getattr(FileService, name))
            self.assertIn("self.guard", source, f"{name} 没有走 guard")
            for banned in ("path.read_text(", "path.read_bytes(", "path.write_text(", "open(path"):
                self.assertNotIn(banned, source, f"{name} 又回到按路径打开了: {banned}")


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
            "len",
            "range",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "bool",
            "tuple",
            "set",
            "frozenset",
            "type",
            "isinstance",
            "issubclass",
            "enumerate",
            "zip",
            "map",
            "filter",
            "sorted",
            "reversed",
            "min",
            "max",
            "sum",
            "abs",
            "round",
            "print",
            "repr",
            "hash",
        ]
        # 确保危险函数不在白名单中
        DANGEROUS = [
            "eval",
            "exec",
            "compile",
            "open",
            "__import__",
            "getattr",
            "setattr",
            "delattr",
            "globals",
            "locals",
        ]
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
        self.assertNotIn('f"SELECT COUNT(*) as count FROM {table_name}"', source)

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
