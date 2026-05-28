"""
windows_service.galaxy_service -- Galaxy Windows Service
========================================================

使用 pywin32 注册为 Windows 系统服务：
- 开机自动启动
- 崩溃自动重启（FailureActions）
- 服务依赖：NATS
- 服务账户：LocalSystem

安装命令（管理员权限）：
    python windows_service/galaxy_service.py install
    python windows_service/galaxy_service.py start

卸载命令：
    python windows_service/galaxy_service.py stop
    python windows_service/galaxy_service.py remove

依赖::

    pip install pywin32
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

logger = logging.getLogger("Galaxy.WindowsService")

# ---------------------------------------------------------------------------
# pywin32 导入（仅在 Windows 运行时加载）
# ---------------------------------------------------------------------------

_HAVE_PYWIN32 = False
if sys.platform == "win32":
    try:
        import win32event
        import win32service
        import win32serviceutil
        import servicemanager

        _HAVE_PYWIN32 = True
    except ImportError:
        logger.warning("pywin32 not installed; Windows service support unavailable")
else:
    logger.info("Non-Windows platform; galaxy_service runs in stub mode")

# ---------------------------------------------------------------------------
# 服务常量
# ---------------------------------------------------------------------------

SERVICE_NAME = "GalaxyV2AI"
SERVICE_DISPLAY_NAME = "Galaxy V2 AI System"
SERVICE_DESCRIPTION = (
    "Center-based Multi-Relative-Subject Distributed AI System. "
    "Provides persistent AI inference, multimodal processing, "
    "and agent orchestration as a Windows system service."
)

# 重启退避配置（毫秒）
_RESTART_DELAY_MS = 5000          # 首次重启延迟 5 秒
_MAX_RESTARTS = 3                 # 24 小时内最多 3 次重启
_RESTART_RESET_PERIOD_MS = 86400_000  # 24 小时重置计数

# 停止超时（秒）
_STOP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# GalaxyV2Service -- Windows 服务框架
# ---------------------------------------------------------------------------

if _HAVE_PYWIN32:

    class GalaxyV2Service(win32serviceutil.ServiceFramework):
        """Galaxy V2 Windows 服务实现。

        生命周期::

            SvcDoRun()   -> 启动 Galaxy 主进程 + 监控线程
            SvcStop()    -> 优雅停止（等待子进程退出）
            _monitor()   -> 崩溃检测 + 自动重启
        """

        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        # 服务启动类型：自动
        _svc_start_type_ = win32service.SERVICE_AUTO_START

        def __init__(self, args: list[str] | None = None) -> None:
            super().__init__(args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._process: subprocess.Popen[str] | None = None
            self._monitor_thread: threading.Thread | None = None
            self._running = False
            self._restart_count = 0
            self._last_restart_time = 0.0
            self._lock = threading.Lock()

        # ── 服务控制回调 ──

        def SvcStop(self) -> None:
            """SCM 请求停止服务时调用。"""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
            self._running = False

            # 终止子进程
            self._kill_process(graceful=True)

            # 等待监控线程结束
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=_STOP_TIMEOUT)

            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, ""),
            )

        def SvcDoRun(self) -> None:
            """服务主入口 —— 由 SCM 在服务启动时调用。"""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, SERVICE_DESCRIPTION),
            )

            self._running = True
            self._spawn_galaxy()

            # 启动崩溃监控线程
            self._monitor_thread = threading.Thread(
                target=self._monitor, name="GalaxyMonitor", daemon=True
            )
            self._monitor_thread.start()

            # 阻塞直到收到停止信号
            win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)

        # ── 内部方法 ──

        def _spawn_galaxy(self) -> None:
            """启动 Galaxy 主进程（作为子进程，避免阻塞 SCM）。"""
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            # 确保 Python 可以导入项目根目录
            env = os.environ.copy()
            env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
            env["GALAXY_SERVICE_MODE"] = "true"
            env["USE_LOCAL_BRAIN_FIRST"] = "true"
            env["ENABLE_MULTIMODAL"] = "true"
            env["GALAXY_LOG_DIR"] = os.path.join(
                os.path.expanduser("~"), ".galaxy", "logs"
            )

            cmd = [
                sys.executable,
                "-u",
                os.path.join(project_root, "main.py"),
            ]

            # 重定向 stdout/stderr 到日志文件
            log_dir = env["GALAXY_LOG_DIR"]
            os.makedirs(log_dir, exist_ok=True)
            stdout_path = os.path.join(log_dir, "galaxy_service.log")

            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=project_root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                # 启动一个后台线程将子进程输出写入日志文件
                threading.Thread(
                    target=self._pipe_logger,
                    args=(self._process, stdout_path),
                    daemon=True,
                ).start()

                logger.info(
                    "Galaxy process started (pid=%d, log=%s)",
                    self._process.pid,
                    stdout_path,
                )
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    0,
                    (f"{SERVICE_NAME} process started (pid={self._process.pid})",),
                )

            except Exception as exc:
                logger.critical("Failed to start Galaxy process: %s", exc)
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_ERROR_TYPE,
                    0,
                    (f"{SERVICE_NAME} failed to start process: {exc}",),
                )

        def _kill_process(self, graceful: bool = True) -> None:
            """终止子进程。"""
            proc = self._process
            if proc is None:
                return

            try:
                if graceful:
                    proc.terminate()
                    try:
                        proc.wait(timeout=_STOP_TIMEOUT)
                        return
                    except subprocess.TimeoutExpired:
                        logger.warning("Graceful stop timed out, forcing kill")
                proc.kill()
                proc.wait(timeout=5)
            except Exception as exc:
                logger.error("Error killing process: %s", exc)
            finally:
                self._process = None

        def _monitor(self) -> None:
            """后台监控 —— 检测子进程崩溃并自动重启。"""
            while self._running:
                time.sleep(5)

                proc = self._process
                if proc is None:
                    continue

                ret = proc.poll()
                if ret is None:
                    # 进程仍在运行
                    continue

                # 进程已退出
                self._process = None
                logger.warning(
                    "Galaxy process exited with code %d, preparing restart...", ret
                )
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_WARNING_TYPE,
                    0,
                    (
                        f"{SERVICE_NAME} process exited with code {ret}, "
                        f"restarting in {_RESTART_DELAY_MS // 1000}s...",
                    ),
                )

                # 退避策略：24 小时内最多重启 _MAX_RESTARTS 次
                now = time.time()
                if now - self._last_restart_time > _RESTART_RESET_PERIOD_MS / 1000:
                    self._restart_count = 0

                self._restart_count += 1
                if self._restart_count > _MAX_RESTARTS:
                    logger.critical(
                        "Max restarts (%d) reached in 24h, giving up.", _MAX_RESTARTS
                    )
                    servicemanager.LogMsg(
                        servicemanager.EVENTLOG_ERROR_TYPE,
                        0,
                        (
                            f"{SERVICE_NAME} max restarts ({_MAX_RESTARTS}) reached. "
                            "Manual intervention required.",
                        ),
                    )
                    self._running = False
                    self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                    break

                self._last_restart_time = now
                time.sleep(_RESTART_DELAY_MS / 1000)

                if self._running:
                    logger.info("Restarting Galaxy process (attempt %d)...", self._restart_count)
                    self._spawn_galaxy()

        @staticmethod
        def _pipe_logger(
            process: subprocess.Popen[str], log_path: str
        ) -> None:
            """将子进程 stdout 写入日志文件。"""
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    if process.stdout is not None:
                        for line in process.stdout:
                            fh.write(line)
                            fh.flush()
            except Exception as exc:
                logger.error("Pipe logger error: %s", exc)


# ── 非 Windows Stub ──

else:

    class GalaxyV2Service:
        """非 Windows 平台下的 stub 实现（用于导入测试）。"""

        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args: list[str] | None = None) -> None:
            pass

        def SvcStop(self) -> None:
            logger.info("Stub SvcStop called")

        def SvcDoRun(self) -> None:
            logger.info("Stub SvcDoRun called")


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def _customize_service(service_class: type) -> None:
    """注册自定义服务配置：自动启动、失败重启动作。"""
    if not _HAVE_PYWIN32:
        return

    import win32api
    import win32con

    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        hs = win32service.OpenService(hscm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
        try:
            # 配置失败动作：服务崩溃后 5 秒重启，24 小时内最多 3 次
            restart_delay = _RESTART_DELAY_MS
            actions = [
                (win32service.SC_ACTION_RESTART, restart_delay),
                (win32service.SC_ACTION_RESTART, restart_delay),
                (win32service.SC_ACTION_RESTART, restart_delay),
            ]
            failure_actions = win32service.SERVICE_FAILURE_ACTIONS(
                dwResetPeriod=_RESTART_RESET_PERIOD_MS // 1000,  # 秒
                lpRebootMsg=None,
                lpCommand=None,
                lpsaActions=actions,
            )
            win32service.ChangeServiceConfig2(
                hs, win32service.SERVICE_CONFIG_FAILURE_ACTIONS, failure_actions
            )
            logger.info("Service failure actions configured (auto-restart on crash)")
        finally:
            win32service.CloseService(hs)
    except Exception as exc:
        logger.warning("Could not configure failure actions: %s", exc)
    finally:
        win32service.CloseServiceManager(hscm)


if __name__ == "__main__":
    # 确保日志可写
    _log_dir = os.path.join(os.path.expanduser("~"), ".galaxy", "logs")
    os.makedirs(_log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(_log_dir, "windows_service.log")),
            logging.StreamHandler(),
        ],
    )

    if _HAVE_PYWIN32:
        if len(sys.argv) == 1:
            # 由 SCM 直接启动
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(GalaxyV2Service)
            servicemanager.StartServiceCtrlDispatcher()
        else:
            # 命令行安装 / 卸载 / 启动 / 停止
            win32serviceutil.HandleCommandLine(GalaxyV2Service)
            # 如果是 install，额外配置失败动作
            if len(sys.argv) > 1 and sys.argv[1] in ("install", "update"):
                _customize_service(GalaxyV2Service)
    else:
        print("ERROR: pywin32 is required to run Galaxy as a Windows service.")
        print("Install it with:  pip install pywin32")
        sys.exit(1)
