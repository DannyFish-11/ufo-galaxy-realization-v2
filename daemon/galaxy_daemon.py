#!/usr/bin/env python3
"""
Galaxy 24/7 Daemon

This module provides the main daemon process for 24/7 operation:
- Automatic restart on failure
- Health monitoring
- Resource management
- Graceful shutdown handling
"""

import os
import sys
import time
import signal
import logging
import asyncio
try:
    import psutil
except ImportError:
    psutil = None
import json
from collections import deque
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum, auto
import threading
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


class DaemonState(Enum):
    """Daemon operational states"""
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"  # Running but with issues
    RESTARTING = "restarting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class HealthMetrics:
    """System health metrics"""
    timestamp: datetime = field(default_factory=datetime.now)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    disk_percent: float = 0.0
    network_io_mb: float = 0.0
    process_count: int = 0
    thread_count: int = 0
    uptime_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "memory_used_mb": self.memory_used_mb,
            "disk_percent": self.disk_percent,
            "network_io_mb": self.network_io_mb,
            "process_count": self.process_count,
            "thread_count": self.thread_count,
            "uptime_seconds": self.uptime_seconds
        }


@dataclass
class ServiceStatus:
    """Service component status"""
    name: str
    state: DaemonState
    last_heartbeat: Optional[datetime] = None
    restart_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None
    
    def is_healthy(self, timeout_seconds: float = 60) -> bool:
        """Check if service is healthy based on heartbeat"""
        if self.state != DaemonState.RUNNING:
            return False
        if self.last_heartbeat is None:
            return False
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds


class ProcessManager:
    """Manages child processes with automatic restart"""
    
    def __init__(
        self,
        name: str,
        command: List[str],
        restart_policy: str = "always",
        max_restarts: int = 10,
        restart_window: int = 3600,
        log_dir: Optional[Path] = None,
    ):
        self.name = name
        self.command = command
        self.restart_policy = restart_policy
        self.max_restarts = max_restarts
        self.restart_window = restart_window
        self.log_dir = log_dir

        self.process: Optional[subprocess.Popen] = None
        self.restart_times: List[datetime] = []
        self.status = ServiceStatus(name=name, state=DaemonState.STOPPED)

    def start(self) -> bool:
        """Start the managed process"""
        try:
            logger.info(f"Starting {self.name}...")
            self.status.state = DaemonState.STARTING

            # 子进程输出去向:此前用 stdout/stderr=subprocess.PIPE 但从不读取——子服务
            # 写满 ~64KB 管道缓冲后 write 阻塞,整个服务卡死(长跑守护进程必踩)。改为
            # 写进日志文件(无日志目录则 DEVNULL,绝不再用不排水的 PIPE)。
            if self.log_dir is not None:
                logf = open(self.log_dir / f"{self.name}.log", "ab")
            else:
                logf = None
            # cwd 防御:GALAXY_HOME 未设且 /opt/galaxy 不存在时 Popen 直接
            # FileNotFoundError,所有子服务启动失败。目录不存在则回退当前目录。
            cwd = os.environ.get('GALAXY_HOME', '/opt/galaxy')
            if not os.path.isdir(cwd):
                logger.warning("GALAXY_HOME %s does not exist; using current directory", cwd)
                cwd = None
            try:
                self.process = subprocess.Popen(
                    self.command,
                    stdout=logf if logf is not None else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT if logf is not None else subprocess.DEVNULL,
                    cwd=cwd,
                )
            finally:
                # 父进程关闭自己的句柄(子进程已持有 dup fd),避免每次重启泄漏 fd
                if logf is not None:
                    logf.close()
            
            self.status.state = DaemonState.RUNNING
            self.status.last_heartbeat = datetime.now()
            
            logger.info(f"{self.name} started with PID {self.process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start {self.name}: {e}")
            self.status.state = DaemonState.ERROR
            self.status.last_error = str(e)
            return False
    
    def stop(self, timeout: int = 30) -> bool:
        """Stop the managed process gracefully"""
        if self.process is None:
            return True
        
        try:
            logger.info(f"Stopping {self.name}...")
            self.status.state = DaemonState.STOPPING
            
            # Send SIGTERM for graceful shutdown
            self.process.terminate()
            
            # Wait for process to exit
            try:
                self.process.wait(timeout=timeout)
                logger.info(f"{self.name} stopped gracefully")
            except subprocess.TimeoutExpired:
                logger.warning(f"{self.name} did not stop gracefully, forcing...")
                self.process.kill()
                self.process.wait()
            
            self.status.state = DaemonState.STOPPED
            self.process = None
            return True
            
        except Exception as e:
            logger.error(f"Error stopping {self.name}: {e}")
            return False
    
    def check_health(self) -> bool:
        """Check if process is healthy"""
        if self.process is None:
            return False
        
        # Check if process is still running
        if self.process.poll() is not None:
            logger.warning(f"{self.name} has exited with code {self.process.returncode}")
            self.status.state = DaemonState.ERROR
            return False
        
        # Update heartbeat
        self.status.last_heartbeat = datetime.now()
        return True
    
    def should_restart(self) -> bool:
        """Check if process should be restarted based on policy"""
        if self.restart_policy == "never":
            return False
        
        # Clean old restart times
        cutoff = datetime.now() - timedelta(seconds=self.restart_window)
        self.restart_times = [t for t in self.restart_times if t > cutoff]
        
        # Check restart limit
        if len(self.restart_times) >= self.max_restarts:
            logger.error(f"{self.name} exceeded max restarts ({self.max_restarts})")
            return False
        
        return True
    
    def restart(self) -> bool:
        """Restart the process"""
        self.stop()
        self.restart_times.append(datetime.now())
        self.status.restart_count += 1
        self.status.state = DaemonState.RESTARTING
        return self.start()


class GalaxyDaemon:
    """
    Galaxy 24/7 Daemon
    
    Manages all system components for continuous operation:
    - Main Galaxy system
    - Health monitoring
    - Resource management
    - Automatic recovery
    
    Example:
        >>> daemon = GalaxyDaemon()
        >>> daemon.start()
        >>> # Runs 24/7 until stopped
        >>> daemon.stop()
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the daemon
        
        Args:
            config_path: Path to daemon configuration file
        """
        # 记住配置路径:SIGHUP 热重载必须用它重读,否则 _reload_config 会把用户
        # 配置整体丢回内置默认值。
        self._config_path = config_path
        self.config = self._load_config(config_path)
        self.state = DaemonState.INITIALIZING
        self.start_time: Optional[datetime] = None
        
        # Process managers
        self.processes: Dict[str, ProcessManager] = {}
        
        # Health tracking
        self.health_metrics: deque = deque(maxlen=1000)  # B3 fixed: O(1) append + auto-truncate
        self.max_health_history = 1000
        
        # Control flags
        self._running = False
        self._shutdown_event = threading.Event()
        # H8 fixed: use atomic int flag for signal-safe deferred handling
        self._signal_pending: int = 0  # 0=none, SIGTERM/SIGINT=shutdown, SIGHUP=reload

        # Setup signal handlers — use a simple atomic flag approach for thread safety
        # Windows 兼容(开机自启的前提):SIGHUP 与 siginterrupt 在 Windows 上不存在,
        # 此前无条件调用 → 守护进程在 Windows 一启动就 AttributeError 崩掉。
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._signal_handler)
        if hasattr(signal, "siginterrupt"):
            # Prevent signals from interrupting system calls (retry instead)
            signal.siginterrupt(signal.SIGTERM, False)
            signal.siginterrupt(signal.SIGINT, False)
            if hasattr(signal, "SIGHUP"):
                signal.siginterrupt(signal.SIGHUP, False)

        logger.info("GalaxyDaemon initialized")
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load daemon configuration"""
        default_config = {
            "health_check_interval": 30,
            "metrics_collection_interval": 60,
            "max_restarts_per_hour": 10,
            "memory_threshold": 90,  # Percent
            "cpu_threshold": 95,  # Percent
            "disk_threshold": 90,  # Percent
            "services": {
                "galaxy_main": {
                    "command": ["python", "unified_launcher.py"],
                    "restart_policy": "always",
                    "max_restarts": 10
                },
                "health_monitor": {
                    "command": ["python", "-m", "health_monitor", "--watchdog"],
                    "restart_policy": "always",
                    "max_restarts": 20
                }
            }
        }
        
        if config_path and os.path.exists(config_path):
            # 显式 UTF-8:config.json 可能含中文;Windows 默认 cp1252 读取会
            # UnicodeDecodeError 崩掉守护进程启动。
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        
        return default_config
    
    def _signal_handler(self, signum, frame):
        """Handle system signals — thread-safe deferred processing.

        H8 fixed: Only set an atomic flag; actual handling is done in the
        main loop to avoid signal-handler race conditions with file I/O.
        """
        import signal as _signal_module
        # SIGHUP 在 Windows 上不存在,无条件取属性会让 handler 本身 AttributeError
        # (即使 SIGHUP 从未注册,构造 dict 时求值就炸)。用 getattr 防御。
        signals = {
            _signal_module.SIGTERM: "SIGTERM",
            _signal_module.SIGINT: "SIGINT",
        }
        _sighup = getattr(_signal_module, "SIGHUP", None)
        if _sighup is not None:
            signals[_sighup] = "SIGHUP"
        signal_name = signals.get(signum, f"Signal {signum}")
        logger.info("Received %s", signal_name)
        # Set atomic flag — main loop will process it safely
        self._signal_pending = signum

    def _process_pending_signals(self):
        """Process any pending signals in the main loop (thread-safe)."""
        if self._signal_pending == 0:
            return
        signum = self._signal_pending
        self._signal_pending = 0  # Clear before processing
        # Windows 上 signal.SIGHUP 属性不存在,直接 `signum == signal.SIGHUP`
        # 会在主循环里 AttributeError 崩掉(即使 SIGHUP 从未注册,求值本身就炸)。
        _sighup = getattr(signal, "SIGHUP", None)
        if _sighup is not None and signum == _sighup:
            self._reload_config()
        else:
            self._shutdown_event.set()

    def _reload_config(self):
        """Reload daemon configuration"""
        logger.info("Reloading configuration...")
        # 用启动时的配置路径重读;原来传 None 会把用户配置整体丢回内置默认值。
        self.config = self._load_config(self._config_path)
        logger.info("Configuration reloaded")

    def _resolve_log_dir(self) -> Optional[Path]:
        """Resolve a writable log directory with graceful fallback.

        优先级:GALAXY_LOG_DIR 环境变量 → /var/log/galaxy → ~/.galaxy/logs。
        原来硬编码 mkdir /var/log/galaxy,非 root 运行直接 PermissionError,
        整个守护进程启动失败。全部失败返回 None(子服务输出走 DEVNULL)。
        """
        candidates: List[Path] = []
        env_dir = os.environ.get("GALAXY_LOG_DIR")
        if env_dir:
            candidates.append(Path(env_dir))
        candidates.append(Path("/var/log/galaxy"))
        try:
            candidates.append(Path.home() / ".galaxy" / "logs")
        except (RuntimeError, OSError):
            pass
        for cand in candidates:
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand
            except (PermissionError, OSError) as exc:
                logger.warning("Log dir %s unavailable: %s", cand, exc)
        logger.warning("No writable log directory found; child service output goes to DEVNULL")
        return None
    
    def start(self) -> bool:
        """Start the daemon and all managed services"""
        try:
            logger.info("Starting Galaxy Daemon...")
            self.state = DaemonState.STARTING
            self.start_time = datetime.now()
            self._running = True
            
            # Create log directory (带降级,见 _resolve_log_dir)
            log_dir = self._resolve_log_dir()

            # Start all services
            for name, service_config in self.config["services"].items():
                pm = ProcessManager(
                    name=name,
                    command=service_config["command"],
                    restart_policy=service_config.get("restart_policy", "always"),
                    max_restarts=service_config.get("max_restarts", 10),
                    log_dir=log_dir,
                )
                self.processes[name] = pm
                pm.start()
            
            self.state = DaemonState.RUNNING
            logger.info("Galaxy Daemon started successfully")
            
            # Start main loop
            self._main_loop()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start daemon: {e}")
            self.state = DaemonState.ERROR
            return False
    
    def stop(self) -> bool:
        """Stop the daemon and all services gracefully"""
        logger.info("Stopping Galaxy Daemon...")
        self._running = False
        self._shutdown_event.set()
        self.state = DaemonState.STOPPING
        
        # Stop all services
        for name, pm in self.processes.items():
            logger.info(f"Stopping {name}...")
            pm.stop()
        
        self.state = DaemonState.STOPPED
        logger.info("Galaxy Daemon stopped")
        return True
    
    def _main_loop(self):
        """Main daemon loop"""
        health_interval = self.config.get("health_check_interval", 30)
        metrics_interval = self.config.get("metrics_collection_interval", 60)

        last_health_check = 0
        last_metrics = 0

        while self._running and not self._shutdown_event.is_set():
            # H8 fixed: process signals in main loop (thread-safe)
            self._process_pending_signals()

            current_time = time.time()

            # Health check
            if current_time - last_health_check >= health_interval:
                self._health_check()
                last_health_check = current_time

            # Collect metrics
            if current_time - last_metrics >= metrics_interval:
                self._collect_metrics()
                last_metrics = current_time

            # Check for shutdown
            if self._shutdown_event.wait(1):
                break

        # Graceful shutdown
        self.stop()
    
    def _health_check(self):
        """Check health of all services"""
        for name, pm in self.processes.items():
            if not pm.check_health():
                logger.warning(f"{name} is not healthy")
                
                if pm.should_restart():
                    logger.info(f"Restarting {name}...")
                    pm.restart()
                else:
                    logger.error(f"{name} exceeded restart limit")
                    self.state = DaemonState.DEGRADED
    
    def _collect_metrics(self):
        """Collect system health metrics"""
        try:
            metrics = HealthMetrics()

            if psutil is None:
                # Fallback: minimal metrics without psutil
                if self.start_time:
                    metrics.uptime_seconds = (datetime.now() - self.start_time).total_seconds()
                # 正确容器是 health_metrics(有界 deque);原来写的 health_history
                # 属性根本不存在 → AttributeError 被外层 except 吞掉,psutil 缺失时
                # 指标从不落地。
                self.health_metrics.append(metrics)
                return metrics

            # CPU usage
            metrics.cpu_percent = psutil.cpu_percent(interval=1)

            # Memory usage
            memory = psutil.virtual_memory()
            metrics.memory_percent = memory.percent
            metrics.memory_used_mb = memory.used / (1024 * 1024)

            # Disk usage
            disk = psutil.disk_usage('/')
            metrics.disk_percent = (disk.used / disk.total) * 100

            # Network I/O
            net_io = psutil.net_io_counters()
            metrics.network_io_mb = (net_io.bytes_sent + net_io.bytes_recv) / (1024 * 1024)

            # Process info
            metrics.process_count = len(psutil.pids())
            metrics.thread_count = sum(p.num_threads() for p in psutil.process_iter())
            
            # Uptime
            if self.start_time:
                metrics.uptime_seconds = (datetime.now() - self.start_time).total_seconds()
            
            # Store metrics
            self.health_metrics.append(metrics)  # B3 fixed: deque auto-truncates
            
            # Check thresholds
            self._check_thresholds(metrics)
            
        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
    
    def _check_thresholds(self, metrics: HealthMetrics):
        """Check if metrics exceed thresholds"""
        if metrics.cpu_percent > self.config.get("cpu_threshold", 95):
            logger.warning(f"CPU usage high: {metrics.cpu_percent}%")
        
        if metrics.memory_percent > self.config.get("memory_threshold", 90):
            logger.warning(f"Memory usage high: {metrics.memory_percent}%")
        
        if metrics.disk_percent > self.config.get("disk_threshold", 90):
            logger.warning(f"Disk usage high: {metrics.disk_percent}%")
    
    def get_status(self) -> Dict[str, Any]:
        """Get daemon status"""
        return {
            "state": self.state.value,
            "uptime_seconds": (
                (datetime.now() - self.start_time).total_seconds()
                if self.start_time else 0
            ),
            "services": {
                name: {
                    "state": pm.status.state.value,
                    "restart_count": pm.status.restart_count,
                    "error_count": pm.status.error_count,
                    "is_healthy": pm.status.is_healthy()
                }
                for name, pm in self.processes.items()
            },
            "latest_metrics": (
                self.health_metrics[-1].to_dict()
                if self.health_metrics else None
            )
        }
    
    def save_metrics(self, filepath: str):
        """Save metrics to file"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "metrics": [m.to_dict() for m in self.health_metrics]
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)


# Convenience functions
def start_daemon(config_path: Optional[str] = None) -> GalaxyDaemon:
    """Start the daemon"""
    daemon = GalaxyDaemon(config_path)
    daemon.start()
    return daemon


def stop_daemon(daemon: GalaxyDaemon):
    """Stop the daemon"""
    daemon.stop()


if __name__ == "__main__":
    # Run as daemon
    import argparse
    
    parser = argparse.ArgumentParser(description="Galaxy 24/7 Daemon")
    parser.add_argument("--config", "-c", help="Configuration file path")
    parser.add_argument("--status", "-s", action="store_true", help="Show status")
    parser.add_argument("--stop", action="store_true", help="Stop daemon")
    parser.add_argument("--install-autostart", action="store_true",
                        help="注册开机自启(Windows 计划任务 / systemd user / LaunchAgent)")
    parser.add_argument("--uninstall-autostart", action="store_true", help="取消开机自启")
    parser.add_argument("--autostart-status", action="store_true", help="查看开机自启状态")

    args = parser.parse_args()

    if args.install_autostart or args.uninstall_autostart or args.autostart_status:
        try:
            from daemon.autostart import install, status, uninstall
        except ImportError:
            # 直接 `python daemon/galaxy_daemon.py` 运行时 sys.path[0] 是 daemon/
            # 目录本身,包名不可见 → 退回同目录导入。
            from autostart import install, status, uninstall
        if args.install_autostart:
            result = install()
        elif args.uninstall_autostart:
            result = uninstall()
        else:
            result = status()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result.get("ok", result.get("installed")) != "False" else 1)

    if args.stop:
        # Send stop signal
        # Find and stop running daemon
        if psutil is None:
            print("psutil not available, cannot find daemon process")
            sys.exit(1)
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if 'galaxy_daemon' in ' '.join(proc.info['cmdline'] or []):
                os.kill(proc.info['pid'], signal.SIGTERM)
                print(f"Stopped daemon (PID {proc.info['pid']})")
    elif args.status:
        daemon = GalaxyDaemon(args.config)
        print(json.dumps(daemon.get_status(), indent=2, ensure_ascii=False, default=str))
    else:
        daemon = GalaxyDaemon(args.config)
        try:
            daemon.start()  # blocks in the main loop until shutdown
        except KeyboardInterrupt:
            daemon.stop()
