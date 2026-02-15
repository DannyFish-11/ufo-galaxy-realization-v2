#!/usr/bin/env python3
"""
UFO Galaxy 24/7 Daemon

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
import psutil
import json
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
        logging.FileHandler('/var/log/ufo-galaxy/daemon.log')
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
        restart_window: int = 3600
    ):
        self.name = name
        self.command = command
        self.restart_policy = restart_policy
        self.max_restarts = max_restarts
        self.restart_window = restart_window
        
        self.process: Optional[subprocess.Popen] = None
        self.restart_times: List[datetime] = []
        self.status = ServiceStatus(name=name, state=DaemonState.STOPPED)
        
    def start(self) -> bool:
        """Start the managed process"""
        try:
            logger.info(f"Starting {self.name}...")
            self.status.state = DaemonState.STARTING
            
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.environ.get('UFO_GALAXY_HOME', '/opt/ufo-galaxy')
            )
            
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


class UFOGalaxyDaemon:
    """
    UFO Galaxy 24/7 Daemon
    
    Manages all system components for continuous operation:
    - Main Galaxy system
    - Health monitoring
    - Resource management
    - Automatic recovery
    
    Example:
        >>> daemon = UFOGalaxyDaemon()
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
        self.config = self._load_config(config_path)
        self.state = DaemonState.INITIALIZING
        self.start_time: Optional[datetime] = None
        
        # Process managers
        self.processes: Dict[str, ProcessManager] = {}
        
        # Health tracking
        self.health_metrics: List[HealthMetrics] = []
        self.max_health_history = 1000
        
        # Control flags
        self._running = False
        self._shutdown_event = threading.Event()
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGHUP, self._signal_handler)
        
        logger.info("UFOGalaxyDaemon initialized")
    
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
                    "command": ["python", "-m", "galaxy_launcher", "--daemon"],
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
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        
        return default_config
    
    def _signal_handler(self, signum, frame):
        """Handle system signals"""
        signals = {
            signal.SIGTERM: "SIGTERM",
            signal.SIGINT: "SIGINT",
            signal.SIGHUP: "SIGHUP"
        }
        signal_name = signals.get(signum, f"Signal {signum}")
        logger.info(f"Received {signal_name}")
        
        if signum == signal.SIGHUP:
            # Reload configuration
            self._reload_config()
        else:
            # Shutdown
            self._shutdown_event.set()
    
    def _reload_config(self):
        """Reload daemon configuration"""
        logger.info("Reloading configuration...")
        self.config = self._load_config(None)
        logger.info("Configuration reloaded")
    
    def start(self) -> bool:
        """Start the daemon and all managed services"""
        try:
            logger.info("Starting UFO Galaxy Daemon...")
            self.state = DaemonState.STARTING
            self.start_time = datetime.now()
            self._running = True
            
            # Create log directory
            Path("/var/log/ufo-galaxy").mkdir(parents=True, exist_ok=True)
            
            # Start all services
            for name, service_config in self.config["services"].items():
                pm = ProcessManager(
                    name=name,
                    command=service_config["command"],
                    restart_policy=service_config.get("restart_policy", "always"),
                    max_restarts=service_config.get("max_restarts", 10)
                )
                self.processes[name] = pm
                pm.start()
            
            self.state = DaemonState.RUNNING
            logger.info("UFO Galaxy Daemon started successfully")
            
            # Start main loop
            self._main_loop()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start daemon: {e}")
            self.state = DaemonState.ERROR
            return False
    
    def stop(self) -> bool:
        """Stop the daemon and all services gracefully"""
        logger.info("Stopping UFO Galaxy Daemon...")
        self._running = False
        self._shutdown_event.set()
        self.state = DaemonState.STOPPING
        
        # Stop all services
        for name, pm in self.processes.items():
            logger.info(f"Stopping {name}...")
            pm.stop()
        
        self.state = DaemonState.STOPPED
        logger.info("UFO Galaxy Daemon stopped")
        return True
    
    def _main_loop(self):
        """Main daemon loop"""
        health_interval = self.config.get("health_check_interval", 30)
        metrics_interval = self.config.get("metrics_collection_interval", 60)
        
        last_health_check = 0
        last_metrics = 0
        
        while self._running and not self._shutdown_event.is_set():
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
            self.health_metrics.append(metrics)
            if len(self.health_metrics) > self.max_health_history:
                self.health_metrics = self.health_metrics[-self.max_health_history:]
            
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
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)


# Convenience functions
def start_daemon(config_path: Optional[str] = None) -> UFOGalaxyDaemon:
    """Start the daemon"""
    daemon = UFOGalaxyDaemon(config_path)
    daemon.start()
    return daemon


def stop_daemon(daemon: UFOGalaxyDaemon):
    """Stop the daemon"""
    daemon.stop()


if __name__ == "__main__":
    # Run as daemon
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO Galaxy 24/7 Daemon")
    parser.add_argument("--config", "-c", help="Configuration file path")
    parser.add_argument("--status", "-s", action="store_true", help="Show status")
    parser.add_argument("--stop", action="store_true", help="Stop daemon")
    
    args = parser.parse_args()
    
    if args.stop:
        # Send stop signal
        import signal
        # Find and stop running daemon
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if 'ufogalaxy_daemon' in ' '.join(proc.info['cmdline'] or []):
                os.kill(proc.info['pid'], signal.SIGTERM)
                print(f"Stopped daemon (PID {proc.info['pid']})")
    else:
        daemon = start_daemon(args.config)
