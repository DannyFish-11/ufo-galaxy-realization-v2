"""
tests/test_comtypes_bootstrap.py
================================

测试 windows_client/autonomy/comtypes_bootstrap.py 的各项功能：
  - ASCII 安全缓存路径选择逻辑（Strategy 2）
  - 缓存目录清理（Strategy 1 辅助）
  - stale 缓存目录收集
  - ensure_uia_client 在非 Windows 平台的行为
  - setup_comtypes_gen_dir 在非 Windows 平台的行为
  - log_diagnostics 不抛出异常
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# 确保项目根目录在 sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# 将 windows_client/autonomy 加入路径，使 comtypes_bootstrap 可直接导入
_AUTONOMY_DIR = os.path.join(_REPO_ROOT, "windows_client", "autonomy")
sys.path.insert(0, _AUTONOMY_DIR)

import comtypes_bootstrap as cb  # noqa: E402 (inserted path above)


# ---------------------------------------------------------------------------
# Helper: build a minimal comtypes mock suitable for sys.modules patching
# ---------------------------------------------------------------------------

def _make_comtypes_mocks(gen_dir="/old/gen", gen_path=None):
    """Return a dict suitable for ``patch.dict(sys.modules, ...)``."""
    if gen_path is None:
        gen_path = [gen_dir]

    mock_comtypes = MagicMock()
    mock_comtypes.__version__ = "1.4.0"
    mock_comtypes.__path__ = [gen_dir]

    mock_client = MagicMock()
    mock_client.gen_dir = gen_dir

    mock_gen = MagicMock()
    mock_gen.__path__ = list(gen_path)
    mock_gen.__file__ = os.path.join(gen_dir, "__init__.py")

    # Pre-bind child modules on the parent so that attribute access after
    # ``import comtypes.client`` returns the correct mocks.
    # (Python's import system only sets parent attributes during module *loading*,
    #  not when a module is already cached in sys.modules.)
    mock_comtypes.client = mock_client
    mock_comtypes.gen = mock_gen

    return {
        "comtypes": mock_comtypes,
        "comtypes.client": mock_client,
        "comtypes.gen": mock_gen,
    }


class TestGetAsciiSafeCacheDir(unittest.TestCase):
    """_get_ascii_safe_cache_dir 路径选择逻辑"""

    def test_env_var_takes_priority(self):
        """GALAXY_COMTYPES_CACHE 环境变量应被优先返回"""
        with patch.dict(os.environ, {"GALAXY_COMTYPES_CACHE": r"D:\custom_cache"}):
            result = cb._get_ascii_safe_cache_dir()
        self.assertEqual(result, r"D:\custom_cache")

    def test_project_root_candidate_returned_on_current_env(self):
        """当环境变量未设置时，应返回 ASCII 安全路径（项目根或备用）"""
        env_backup = os.environ.pop("GALAXY_COMTYPES_CACHE", None)
        try:
            result = cb._get_ascii_safe_cache_dir()
            # 结果必须是 ASCII 安全的字符串
            self.assertIsInstance(result, str)
            result.encode("ascii")  # 若含非 ASCII 会抛出 UnicodeEncodeError
        finally:
            if env_backup is not None:
                os.environ["GALAXY_COMTYPES_CACHE"] = env_backup

    def test_programdata_fallback_when_project_path_non_ascii(self):
        """当项目根路径不 ASCII 安全时，应回退到 %PROGRAMDATA% 路径"""
        env_backup = os.environ.pop("GALAXY_COMTYPES_CACHE", None)
        try:
            # 模拟 _get_ascii_safe_cache_dir 的内部候选 2 失败 → 走 PROGRAMDATA 路径
            original_join = os.path.join

            def _failing_join(*args):
                # 第一次调用（构造候选路径）返回含非 ASCII 字符的路径
                if args and args[-1] == ".comtypes_cache":
                    return "/tmp/\u4e2d\u6587\u76ee\u5f55/.comtypes_cache"
                return original_join(*args)

            with patch.dict(os.environ, {"PROGRAMDATA": r"C:\ProgramData"}):
                with patch("os.path.join", side_effect=_failing_join):
                    result = cb._get_ascii_safe_cache_dir()

            self.assertIn("GalaxyClient", result)
            result.encode("ascii")  # 必须仍为 ASCII 安全
        finally:
            if env_backup is not None:
                os.environ["GALAXY_COMTYPES_CACHE"] = env_backup

    def test_absolute_fallback_when_all_candidates_non_ascii(self):
        """当所有候选路径均不可用时，返回绝对安全兜底路径"""
        env_backup = os.environ.pop("GALAXY_COMTYPES_CACHE", None)
        try:
            original_join = os.path.join

            def _failing_join(*args):
                if args and args[-1] in (".comtypes_cache", "comtypes_cache"):
                    # 返回含非 ASCII 字符的路径，使 ASCII 检查失败
                    return "/tmp/\u4e2d\u6587/.comtypes_cache"
                return original_join(*args)

            with patch.dict(os.environ, {
                "PROGRAMDATA": "\u4e2d\u6587\\ProgramData",  # 非 ASCII PROGRAMDATA
            }):
                with patch("os.path.join", side_effect=_failing_join):
                    result = cb._get_ascii_safe_cache_dir()

            self.assertEqual(result, r"C:\galaxy_comtypes_cache")
        finally:
            if env_backup is not None:
                os.environ["GALAXY_COMTYPES_CACHE"] = env_backup


class TestClearCacheDir(unittest.TestCase):
    """_clear_cache_dir 安全清理逻辑"""

    def test_clears_files_and_subdirs(self):
        """应删除目录内所有文件及子目录"""
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "a.py"), "w").close()
            open(os.path.join(tmp, "b.py"), "w").close()
            sub = os.path.join(tmp, "subdir")
            os.makedirs(sub)
            open(os.path.join(sub, "c.py"), "w").close()

            result = cb._clear_cache_dir(tmp)

            self.assertTrue(result)
            self.assertEqual(os.listdir(tmp), [])

    def test_nonexistent_dir_returns_true(self):
        """不存在的目录应被视为"已清理"，返回 True"""
        result = cb._clear_cache_dir("/nonexistent/path/xyz_galaxy_test")
        self.assertTrue(result)

    def test_empty_dir_returns_true(self):
        """空目录返回 True"""
        with tempfile.TemporaryDirectory() as tmp:
            result = cb._clear_cache_dir(tmp)
            self.assertTrue(result)


class TestCollectStaleCacheDirs(unittest.TestCase):
    """_collect_stale_cache_dirs 收集逻辑"""

    def test_returns_list(self):
        """返回值应为列表"""
        result = cb._collect_stale_cache_dirs("/tmp/ascii_cache")
        self.assertIsInstance(result, list)

    def test_ascii_cache_dir_included_if_exists(self):
        """若 ascii_cache_dir 存在，应被包含在结果中"""
        with tempfile.TemporaryDirectory() as tmp:
            result = cb._collect_stale_cache_dirs(tmp)
            self.assertIn(tmp, result)

    def test_nonexistent_ascii_cache_dir_not_included(self):
        """若 ascii_cache_dir 不存在，不应被包含"""
        result = cb._collect_stale_cache_dirs("/nonexistent/path/xyz_galaxy_test")
        self.assertNotIn("/nonexistent/path/xyz_galaxy_test", result)


class TestNonWindowsBehavior(unittest.TestCase):
    """在非 Windows 平台上，函数应为空操作"""

    def _run_on_non_windows(self, func, *args, **kwargs):
        with patch.object(sys, "platform", "linux"):
            return func(*args, **kwargs)

    def test_setup_comtypes_gen_dir_returns_empty_on_non_windows(self):
        result = self._run_on_non_windows(cb.setup_comtypes_gen_dir)
        self.assertEqual(result, "")

    def test_ensure_uia_client_returns_false_on_non_windows(self):
        result = self._run_on_non_windows(cb.ensure_uia_client)
        self.assertFalse(result)


class TestLogDiagnostics(unittest.TestCase):
    """log_diagnostics 不应抛出任何异常"""

    def test_does_not_raise(self):
        try:
            cb.log_diagnostics()
        except Exception as exc:
            self.fail(f"log_diagnostics() raised an exception: {exc}")

    def test_does_not_raise_with_comtypes_mocked(self):
        """即使 comtypes 的 mock 对象已就绪，也不应抛出异常"""
        mocks = _make_comtypes_mocks()
        mocks["comtypes.gen.UIAutomationClient"] = MagicMock()
        with patch.dict("sys.modules", mocks):
            try:
                cb.log_diagnostics()
            except Exception as exc:
                self.fail(f"log_diagnostics() raised an exception: {exc}")


class TestSetupComtypesGenDirOnWindows(unittest.TestCase):
    """setup_comtypes_gen_dir 在 Windows 平台的行为（用 mock 模拟）"""

    def test_sets_gen_dir_and_patches_path(self):
        """应将 comtypes.client.gen_dir 设置为目标路径，并更新 comtypes.gen.__path__"""
        with tempfile.TemporaryDirectory() as tmp:
            mocks = _make_comtypes_mocks(gen_dir="/old/gen")
            mock_client = mocks["comtypes.client"]
            mock_gen = mocks["comtypes.gen"]

            with patch.dict(os.environ, {"GALAXY_COMTYPES_CACHE": tmp}):
                with patch.dict("sys.modules", mocks):
                    with patch.object(sys, "platform", "win32"):
                        result = cb.setup_comtypes_gen_dir()

        self.assertEqual(result, tmp)
        self.assertEqual(mock_client.gen_dir, tmp)
        self.assertIn(tmp, mock_gen.__path__)

    def test_idempotent_path_not_duplicated(self):
        """若目标路径已在 __path__ 中，不应重复添加"""
        with tempfile.TemporaryDirectory() as tmp:
            mocks = _make_comtypes_mocks(gen_dir=tmp, gen_path=[tmp])
            mock_gen = mocks["comtypes.gen"]

            with patch.dict(os.environ, {"GALAXY_COMTYPES_CACHE": tmp}):
                with patch.dict("sys.modules", mocks):
                    with patch.object(sys, "platform", "win32"):
                        cb.setup_comtypes_gen_dir()

        self.assertEqual(mock_gen.__path__.count(tmp), 1)


class TestEnsureUiaClientOnWindows(unittest.TestCase):
    """ensure_uia_client 在 Windows 上的自动修复路径"""

    def test_returns_true_if_uia_already_importable(self):
        """若 UIAutomationClient 已可导入，应直接返回 True"""
        with tempfile.TemporaryDirectory() as tmp:
            mocks = _make_comtypes_mocks(gen_dir=tmp)
            mocks["comtypes.gen.UIAutomationClient"] = MagicMock()

            with patch.dict(os.environ, {"GALAXY_COMTYPES_CACHE": tmp}):
                with patch.dict("sys.modules", mocks):
                    with patch.object(sys, "platform", "win32"):
                        result = cb.ensure_uia_client()

        self.assertTrue(result)

    def test_calls_regenerate_on_import_error(self):
        """当 UIAutomationClient 导入失败时，应调用 _regenerate_uia_module"""
        call_log = []

        def mock_regenerate():
            call_log.append("regenerate")
            return False  # 模拟重新生成也失败

        with patch.object(sys, "platform", "win32"):
            with patch.object(cb, "setup_comtypes_gen_dir", return_value="/tmp/ascii"):
                with patch.object(cb, "_collect_stale_cache_dirs", return_value=[]):
                    with patch.object(cb, "_regenerate_uia_module", side_effect=mock_regenerate):
                        import builtins
                        original = builtins.__import__

                        def fake_import(name, *args, **kwargs):
                            if name == "comtypes.gen.UIAutomationClient":
                                raise ImportError("no module")
                            return original(name, *args, **kwargs)

                        with patch("builtins.__import__", side_effect=fake_import):
                            result = cb.ensure_uia_client()

        self.assertIn("regenerate", call_log)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()

