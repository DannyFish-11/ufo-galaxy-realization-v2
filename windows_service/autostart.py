"""
windows_service.autostart -- Windows Auto-Start Registration
=============================================================

注册 Galaxy 到 Windows 启动项（注册表 Run 键）。

- HKEY_CURRENT_USER 级别 -- 不需要管理员权限
- 使用注册表键 ``Software\\Microsoft\\Windows\\CurrentVersion\\Run``
- 支持静默启动（最小化窗口）

命令行::

    python -m windows_service.autostart              # 注册开机自启
    python -m windows_service.autostart --unregister  # 取消开机自启
    python -m windows_service.autostart --status      # 查询当前状态
    python -m windows_service.autostart --tray        # 注册时同时启动托盘

依赖::

    无（使用标准库 winreg，仅 Windows）
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger("Galaxy.AutoStart")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 注册表路径（当前用户级别 -- 无需管理员权限）
REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

# 注册表中的应用程序名称
APP_NAME = "GalaxyV2AI"

# 注册表中的托盘启动器名称
TRAY_APP_NAME = "GalaxyV2AITray"


# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import winreg


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------


def _build_command(
    script_name: str = "main.py",
    args: list[str] | None = None,
    tray_mode: bool = False,
    python_exe: str | None = None,
) -> str:
    """构建注册表 Run 命令字符串。

    参数:
        script_name: 启动的脚本（"main.py" 或 "tray"）
        args: 传递给脚本的额外参数
        tray_mode: 如果为 True，注册托盘启动器
        python_exe: 使用的 Python 解释器（默认 sys.executable）

    返回:
        完整的命令字符串，适合写入注册表值
    """
    if python_exe is None:
        python_exe = sys.executable

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if tray_mode:
        # 启动托盘图标
        script_path = os.path.join(project_root, "windows_service", "tray_icon.py")
    else:
        script_path = os.path.join(project_root, script_name)

    # 规范化路径
    python_exe = os.path.normpath(python_exe)
    script_path = os.path.normpath(script_path)

    # 构建命令
    cmd_parts = [f'"{python_exe}"', f'"{script_path}"']

    if args:
        cmd_parts.extend(args)

    # Windows: 使用 pythonw.exe 实现静默启动（无控制台窗口）
    if sys.platform == "win32" and python_exe.endswith("python.exe"):
        pythonw = python_exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            cmd_parts[0] = f'"{pythonw}"'
            logger.debug("Using pythonw.exe for silent startup")

    return " ".join(cmd_parts)


def register_autostart(
    args: list[str] | None = None,
    tray_mode: bool = False,
) -> bool:
    """注册 Galaxy 到 Windows 启动项。

    在 ``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
    下创建一个注册表值，使得用户登录时 Windows 自动启动 Galaxy。

    参数:
        args: 传递给 main.py 的额外参数
        tray_mode: 如果为 True，注册托盘启动器而非主服务

    返回:
        注册成功返回 True，否则返回 False
    """
    if not _IS_WINDOWS:
        logger.error("Auto-start registration is only supported on Windows")
        return False

    try:
        command = _build_command(args=args, tray_mode=tray_mode)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_WRITE)

        reg_name = TRAY_APP_NAME if tray_mode else APP_NAME
        winreg.SetValueEx(key, reg_name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)

        logger.info("Auto-start registered: %s = %s", reg_name, command)
        return True

    except PermissionError as exc:
        logger.error(
            "Permission denied writing to registry. "
            "Try running as administrator: %s",
            exc,
        )
        return False
    except Exception as exc:
        logger.error("Failed to register auto-start: %s", exc)
        return False


def unregister_autostart(tray_mode: bool = False) -> bool:
    """从 Windows 启动项中移除 Galaxy。

    参数:
        tray_mode: 如果为 True，移除托盘条目而非主服务

    返回:
        取消注册成功返回 True，否则返回 False
    """
    if not _IS_WINDOWS:
        logger.error("Auto-start unregistration is only supported on Windows")
        return False

    reg_name = TRAY_APP_NAME if tray_mode else APP_NAME

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_WRITE)
        winreg.DeleteValue(key, reg_name)
        winreg.CloseKey(key)

        logger.info("Auto-start unregistered: %s", reg_name)
        return True

    except FileNotFoundError:
        logger.info("Auto-start entry %s was not registered", reg_name)
        return True
    except PermissionError as exc:
        logger.error("Permission denied: %s", exc)
        return False
    except Exception as exc:
        logger.error("Failed to unregister auto-start: %s", exc)
        return False


def is_autostart_registered(tray_mode: bool = False) -> bool:
    """检查 Galaxy 是否已注册开机自启。

    参数:
        tray_mode: 如果为 True，检查托盘条目

    返回:
        如果已注册则返回 True，否则返回 False
    """
    if not _IS_WINDOWS:
        return False

    reg_name = TRAY_APP_NAME if tray_mode else APP_NAME

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, reg_name)
        winreg.CloseKey(key)
        return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def get_autostart_command(tray_mode: bool = False) -> Optional[str]:
    """获取当前注册的启动命令。

    参数:
        tray_mode: 如果为 True，获取托盘条目

    返回:
        命令字符串，或如果未注册则返回 None
    """
    if not _IS_WINDOWS:
        return None

    reg_name = TRAY_APP_NAME if tray_mode else APP_NAME

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, reg_name)
        winreg.CloseKey(key)
        return str(value)
    except FileNotFoundError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 启动文件夹（替代方法）
# ---------------------------------------------------------------------------


def _get_startup_folder() -> str:
    """获取用户启动文件夹路径。"""
    return os.path.join(
        os.path.expanduser("~"),
        "AppData",
        "Roaming",
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def create_startup_shortcut(
    name: str = "GalaxyV2AI",
    tray_mode: bool = False,
) -> bool:
    """在 Windows 启动文件夹中创建快捷方式。

    这是注册表方法的替代方案 —— 对用户更可见，
    但可以通过文件资源管理器轻松禁用。

    参数:
        name: 快捷方式文件名称（不含 .lnk）
        tray_mode: 如果为 True，启动托盘

    返回:
        成功返回 True
    """
    if not _IS_WINDOWS:
        logger.error("Shortcut creation is only supported on Windows")
        return False

    try:
        import winshell  # type: ignore[import-untyped]

        startup_dir = _get_startup_folder()
        os.makedirs(startup_dir, exist_ok=True)
        shortcut_path = os.path.join(startup_dir, f"{name}.lnk")

        python_exe = sys.executable
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        if tray_mode:
            target = os.path.join(project_root, "windows_service", "tray_icon.py")
        else:
            target = os.path.join(project_root, "main.py")

        # 使用 pythonw 实现静默启动
        if python_exe.endswith("python.exe"):
            pythonw = python_exe.replace("python.exe", "pythonw.exe")
            if os.path.exists(pythonw):
                python_exe = pythonw

        with winshell.shortcut(shortcut_path) as shortcut:
            shortcut.path = python_exe
            shortcut.arguments = f'"{target}"'
            shortcut.description = "Galaxy V2 AI System"
            shortcut.working_directory = project_root

        logger.info("Startup shortcut created: %s", shortcut_path)
        return True

    except ImportError:
        logger.error("winshell not installed; cannot create shortcut")
        return False
    except Exception as exc:
        logger.error("Failed to create startup shortcut: %s", exc)
        return False


def remove_startup_shortcut(name: str = "GalaxyV2AI") -> bool:
    """从 Windows 启动文件夹中移除快捷方式。"""
    if not _IS_WINDOWS:
        return False

    try:
        shortcut_path = os.path.join(_get_startup_folder(), f"{name}.lnk")
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            logger.info("Startup shortcut removed: %s", shortcut_path)
        return True
    except Exception as exc:
        logger.error("Failed to remove startup shortcut: %s", exc)
        return False


# ---------------------------------------------------------------------------
# 批量操作
# ---------------------------------------------------------------------------


def register_all(tray_mode: bool = True) -> dict[str, bool]:
    """注册所有自动启动机制（注册表 + 启动文件夹）。

    参数:
        tray_mode: 如果为 True，也注册托盘

    返回:
        每个机制的字典 -> 成功标志
    """
    results: dict[str, bool] = {}

    # 主服务（注册表）
    results["registry_main"] = register_autostart()

    # 托盘（注册表）
    if tray_mode:
        results["registry_tray"] = register_autostart(tray_mode=True)

    # 启动文件夹快捷方式
    results["shortcut"] = create_startup_shortcut()

    return results


def unregister_all() -> dict[str, bool]:
    """注销所有自动启动机制。"""
    results: dict[str, bool] = {}

    results["registry_main"] = unregister_autostart()
    results["registry_tray"] = unregister_autostart(tray_mode=True)
    results["shortcut"] = remove_startup_shortcut()

    return results


# ---------------------------------------------------------------------------
# 命令行接口
# ---------------------------------------------------------------------------


def _print_status() -> None:
    """打印当前自动启动状态。"""
    print("=" * 50)
    print("Galaxy V2 AI -- Auto-Start Status")
    print("=" * 50)

    if not _IS_WINDOWS:
        print("Platform:", sys.platform)
        print("Auto-start is only supported on Windows.")
        return

    # 注册表 -- 主服务
    main_reg = is_autostart_registered()
    main_cmd = get_autostart_command()
    print(f"\n[Registry] Main Service: {'REGISTERED' if main_reg else 'NOT REGISTERED'}")
    if main_cmd:
        print(f"  Command: {main_cmd}")

    # 注册表 -- 托盘
    tray_reg = is_autostart_registered(tray_mode=True)
    tray_cmd = get_autostart_command(tray_mode=True)
    print(f"\n[Registry] Tray Icon:    {'REGISTERED' if tray_reg else 'NOT REGISTERED'}")
    if tray_cmd:
        print(f"  Command: {tray_cmd}")

    # 启动文件夹
    shortcut_path = os.path.join(_get_startup_folder(), "GalaxyV2AI.lnk")
    print(f"\n[Shortcut] Startup Folder: {'EXISTS' if os.path.exists(shortcut_path) else 'NOT FOUND'}")
    print(f"  Path: {shortcut_path}")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if not _IS_WINDOWS:
        print("ERROR: Windows auto-start requires Windows platform.")
        sys.exit(1)

    if len(sys.argv) > 1:
        if sys.argv[1] == "--unregister":
            results = unregister_all()
            print("Unregistration results:", results)

        elif sys.argv[1] == "--status":
            _print_status()

        elif sys.argv[1] == "--tray":
            ok = register_autostart(tray_mode=True)
            print(f"Tray auto-start: {'registered' if ok else 'failed'}")

        elif sys.argv[1] == "--shortcut":
            ok = create_startup_shortcut()
            print(f"Startup shortcut: {'created' if ok else 'failed'}")

        elif sys.argv[1] == "--all":
            results = register_all(tray_mode=True)
            print("Registration results:", results)

        else:
            print(__doc__)
    else:
        # 默认：注册主服务
        ok = register_autostart()
        print(f"Auto-start: {'registered' if ok else 'failed'}")
        if ok:
            _print_status()
