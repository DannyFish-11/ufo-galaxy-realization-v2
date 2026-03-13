"""
comtypes_bootstrap.py — comtypes 启动引导模块

在 comtypes 缓存出现问题（路径含非 ASCII 字符、缓存损坏等）时自动修复。

三项策略:
  1. 检测 UIAutomationClient 缺失/损坏 → 清理旧缓存 → 调用 GetModule 重新生成。
  2. 将 comtypes.client.gen_dir 重定向到 ASCII 安全路径（项目根目录下的
     .comtypes_cache、%PROGRAMDATA%\\GalaxyClient\\comtypes_cache，或固定兜底路径）。
  3. 通过 log_diagnostics() 输出结构化诊断信息。

使用方法
--------
在 windows_client/autonomy/ui_automation.py 的 comtypes 导入之后调用::

    from . import comtypes_bootstrap
    comtypes_bootstrap.ensure_uia_client()

在 windows_client/main.py 的 _preflight_checks() 中调用::

    from autonomy.comtypes_bootstrap import setup_comtypes_gen_dir, log_diagnostics
    setup_comtypes_gen_dir()
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 策略 2：ASCII 安全缓存路径
# ---------------------------------------------------------------------------

def _get_ascii_safe_cache_dir() -> str:
    """返回一个 ASCII 安全的 comtypes 缓存目录路径。

    优先级：
    1. 环境变量 GALAXY_COMTYPES_CACHE（用户手动指定）。
    2. 项目根目录下的 .comtypes_cache（windows_client/autonomy/ 上两级）。
    3. %PROGRAMDATA%\\GalaxyClient\\comtypes_cache（通常为 C:\\ProgramData\\...）。
    4. C:\\galaxy_comtypes_cache（绝对安全的兜底路径）。
    """
    # 1. 用户指定的环境变量
    env = os.environ.get("GALAXY_COMTYPES_CACHE", "").strip()
    if env:
        return env

    # 2. 项目根目录（本文件位于 windows_client/autonomy/，上两级即为项目根）
    try:
        this_file = os.path.abspath(__file__)
        autonomy_dir = os.path.dirname(this_file)           # .../windows_client/autonomy
        windows_client_dir = os.path.dirname(autonomy_dir)  # .../windows_client
        proj_root = os.path.dirname(windows_client_dir)     # 项目根目录
        candidate = os.path.join(proj_root, ".comtypes_cache")
        candidate.encode("ascii")  # 验证是否为 ASCII 安全路径
        return candidate
    except (UnicodeEncodeError, ValueError, TypeError):
        pass

    # 3. %PROGRAMDATA%（通常是 C:\ProgramData，ASCII 安全）
    prog_data = os.environ.get("PROGRAMDATA", "")
    if prog_data:
        try:
            prog_data.encode("ascii")
            return os.path.join(prog_data, "GalaxyClient", "comtypes_cache")
        except (UnicodeEncodeError, ValueError):
            pass

    # 4. 绝对安全的兜底路径
    return r"C:\galaxy_comtypes_cache"


def setup_comtypes_gen_dir() -> str:
    """将 comtypes.client.gen_dir 重定向到 ASCII 安全目录。

    必须在首次访问 ``comtypes.gen.UIAutomationClient`` 之前调用，
    但可以在 ``import comtypes.client`` 之后调用。

    在非 Windows 系统上为空操作，直接返回空字符串。

    Returns:
        str: 实际设置的缓存目录路径（非 Windows 返回空字符串）。
    """
    if sys.platform != "win32":
        return ""

    cache_dir = _get_ascii_safe_cache_dir()

    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        logger.warning("无法创建 comtypes 缓存目录 %s: %s", cache_dir, exc)

    try:
        import comtypes.client
        import comtypes.gen

        old = getattr(comtypes.client, "gen_dir", None)
        comtypes.client.gen_dir = cache_dir

        # 同步更新 comtypes.gen.__path__，使 import comtypes.gen.XXX 能找到新目录
        if cache_dir not in comtypes.gen.__path__:
            comtypes.gen.__path__.insert(0, cache_dir)

        if old != cache_dir:
            logger.info("comtypes gen_dir 已重定向: %r -> %r", old, cache_dir)
    except Exception as exc:
        logger.warning("setup_comtypes_gen_dir 执行时出错（非严重）: %s", exc)

    return cache_dir


# ---------------------------------------------------------------------------
# 策略 1：自动清理损坏缓存并重新生成
# ---------------------------------------------------------------------------

def _clear_cache_dir(cache_dir: str) -> bool:
    """安全地清理 comtypes 缓存目录中的所有文件和子目录。

    无权限访问的条目会被静默跳过。

    Args:
        cache_dir: 要清理的目录路径。

    Returns:
        bool: True 表示无错误完成；False 表示存在无法删除的条目。
    """
    import shutil

    if not os.path.isdir(cache_dir):
        return True

    deleted = skipped = 0
    try:
        for entry in os.scandir(cache_dir):
            try:
                if entry.is_file(follow_symlinks=False):
                    os.remove(entry.path)
                    deleted += 1
                elif entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                    deleted += 1
            except (PermissionError, OSError):
                skipped += 1
    except OSError as exc:
        logger.warning("扫描 comtypes 缓存目录时出错: %s", exc)
        return False

    logger.info(
        "comtypes 缓存已清理: 删除 %d 项，跳过 %d 项（权限不足）", deleted, skipped
    )
    return skipped == 0


def _collect_stale_cache_dirs(ascii_cache_dir: str) -> list:
    """收集所有可能包含旧版 comtypes 缓存文件的目录。

    Args:
        ascii_cache_dir: 当前 ASCII 安全缓存目录（也会被包含以确保重置）。

    Returns:
        list[str]: 需要清理的目录路径列表。
    """
    dirs: list = []

    # 旧版 comtypes 默认在 temp 目录下创建的缓存位置
    try:
        import tempfile
        tmp = tempfile.gettempdir()
        for name in ("comtypes_cache", "comtypes-cache"):
            d = os.path.join(tmp, name)
            if os.path.isdir(d):
                dirs.append(d)
    except Exception:
        pass

    # comtypes.gen 包目录（Python 安装路径内）
    try:
        import comtypes.gen
        pkg_dir = os.path.dirname(comtypes.gen.__file__)
        if pkg_dir and os.path.isdir(pkg_dir) and pkg_dir not in dirs:
            dirs.append(pkg_dir)
    except Exception:
        pass

    # 目标 ASCII 缓存目录（确保彻底重置）
    if ascii_cache_dir and os.path.isdir(ascii_cache_dir) and ascii_cache_dir not in dirs:
        dirs.append(ascii_cache_dir)

    return dirs


def _regenerate_uia_module() -> bool:
    """调用 GetModule 强制重新生成 UIAutomationClient 包装代码。

    Returns:
        bool: 成功返回 True，失败返回 False。
    """
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        logger.info("UIAutomationClient 模块重新生成成功")
        return True
    except Exception as exc:
        logger.error("重新生成 UIAutomationClient 失败: %s", exc)
        return False


def ensure_uia_client() -> bool:
    """确保 ``comtypes.gen.UIAutomationClient`` 可正常导入。

    执行顺序:

    1. 将 gen_dir 重定向到 ASCII 安全路径（策略 2）。
    2. 尝试直接导入 UIAutomationClient。
    3. 若失败，清理所有旧缓存，然后重新生成（策略 1）。
    4. 再次导入验证。

    在非 Windows 系统上为空操作，返回 False。

    Returns:
        bool: True 表示 UIAutomationClient 可用，False 表示不可用。
    """
    if sys.platform != "win32":
        return False

    # 步骤 1：设置 ASCII 安全的 gen_dir
    cache_dir = setup_comtypes_gen_dir()

    # 步骤 2：尝试直接导入
    try:
        import comtypes.gen.UIAutomationClient  # noqa: F401
        logger.debug("UIAutomationClient 可用（缓存命中）")
        return True
    except (ImportError, OSError, AttributeError) as exc:
        logger.info(
            "UIAutomationClient 不可用: %s，尝试自动修复...", exc
        )

    # 步骤 3：清理所有旧缓存
    for stale_dir in _collect_stale_cache_dirs(cache_dir):
        logger.info("清理旧 comtypes 缓存: %s", stale_dir)
        _clear_cache_dir(stale_dir)

    # 步骤 4：重新生成
    if not _regenerate_uia_module():
        return False

    # 步骤 5：验证
    try:
        import importlib
        importlib.invalidate_caches()

        # 确保新 gen_dir 在 comtypes.gen.__path__ 中
        import comtypes.gen
        if cache_dir and cache_dir not in comtypes.gen.__path__:
            comtypes.gen.__path__.insert(0, cache_dir)

        import comtypes.gen.UIAutomationClient  # noqa: F401
        logger.info("UIAutomationClient 自动修复成功")
        return True
    except Exception as exc:
        logger.error("UIAutomationClient 修复后仍不可用: %s", exc)
        return False


# ---------------------------------------------------------------------------
# 策略 3：诊断信息
# ---------------------------------------------------------------------------

def log_diagnostics() -> None:
    """将 comtypes / UIAutomation 环境诊断信息以 INFO 级别写入日志。"""
    lines = ["=== comtypes / UIAutomation 诊断信息 ==="]

    # 用户主目录
    home = os.path.expanduser("~")
    try:
        home.encode("ascii")
        lines.append(f"  用户目录   : {home}  [ASCII 安全 ✓]")
    except UnicodeEncodeError:
        lines.append(f"  用户目录   : {home}  [含非 ASCII 字符 ✗ — 可能导致 comtypes 问题]")

    lines.append(f"  Python     : {sys.version}")

    # comtypes 版本及 gen_dir
    try:
        import comtypes
        lines.append(f"  comtypes   : {comtypes.__version__}")
        import comtypes.client
        gen_dir = getattr(comtypes.client, "gen_dir", "?")
        try:
            str(gen_dir).encode("ascii")
            lines.append(f"  gen_dir    : {gen_dir}  [ASCII 安全 ✓]")
        except (UnicodeEncodeError, AttributeError):
            lines.append(f"  gen_dir    : {gen_dir}  [含非 ASCII 字符 ✗]")
    except ImportError:
        lines.append("  comtypes   : 未安装")

    # UIAutomationClient 可用性
    try:
        import comtypes.gen.UIAutomationClient  # noqa: F401
        lines.append("  UIAClient  : 可用 ✓")
    except ImportError:
        lines.append("  UIAClient  : 不可用（缓存未生成）✗")
    except Exception as exc:
        lines.append(f"  UIAClient  : 错误 — {exc} ✗")

    # GALAXY_COMTYPES_CACHE 环境变量
    env_cache = os.environ.get("GALAXY_COMTYPES_CACHE", "")
    if env_cache:
        lines.append(
            f"  GALAXY_COMTYPES_CACHE={env_cache}  "
            f"(目录存在: {os.path.isdir(env_cache)})"
        )

    lines.append("=" * 44)
    for line in lines:
        logger.info(line)
