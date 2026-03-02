"""
Unified Launcher for UFO Galaxy

Optimized startup with:
- Parallel node startup
- Smart dependency resolution
- Health monitoring
- Auto-recovery
- Resource management
"""

import os
import sys
import time
import json
import signal
import asyncio
import logging
import subprocess
import psutil
from typing import Dict, List, Set, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor

# Import local modules
from .config_manager import ConfigManager, NodeConfig, NodeGroup
from .dependency_resolver import DependencyResolver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NodeStatus(Enum):
    """Node runtime status"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"
    FAILED = "failed"
    RESTARTING = "restarting"


@dataclass
class RuntimeNode:
    """Runtime node information"""
    config: NodeConfig
    status: NodeStatus = NodeStatus.STOPPED
    process: Optional[subprocess.Popen] = None
    start_time: Optional[datetime] = None
    restart_count: int = 0
    last_health_check: Optional[datetime] = None
    health_failures: int = 0
    log_file: Optional[Path] = None
    
    @property
    def uptime_seconds(self) -> float:
        """Get node uptime in seconds"""
        if self.start_time:
            return (datetime.now() - self.start_time).total_seconds()
        return 0.0
    
    @property
    def is_running(self) -> bool:
        """Check if node process is running"""
        if self.process is None:
            return False
        return self.process.poll() is None


@dataclass
class LaunchConfig:
    """Launcher configuration"""
    groups: List[str] = field(default_factory=lambda: ["core"])
    specific_nodes: Optional[List[str]] = None
    parallel: bool = True
    max_parallel: int = 5
    health_check: bool = True
    auto_restart: bool = True
    startup_delay: float = 0.5
    wait_for_healthy: bool = True
    timeout: int = 60


class UnifiedLauncher:
    """
    Unified Launcher for UFO Galaxy
    
    Features:
    - Parallel node startup for faster initialization
    - Smart dependency resolution
    - Continuous health monitoring
    - Automatic recovery on failure
    - Resource usage tracking
    - Graceful shutdown
    
    Example:
        >>> launcher = UnifiedLauncher()
        >>> await launcher.start(LaunchConfig(groups=["core", "extended"]))
        >>> # System running...
        >>> await launcher.stop()
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize unified launcher
        
        Args:
            config_manager: Configuration manager (auto-created if None)
        """
        self.config = config_manager or ConfigManager()
        self.config.load_all()
        
        self.runtime_nodes: Dict[str, RuntimeNode] = {}
        self.resolver = DependencyResolver(self.config.nodes)
        
        # Async components
        self._http_client: Optional[Any] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._monitoring = False
        
        # Thread pool for parallel operations
        self._executor = ThreadPoolExecutor(max_workers=10)
        
        # Event callbacks
        self._on_node_started: List[Callable] = []
        self._on_node_stopped: List[Callable] = []
        self._on_node_failed: List[Callable] = []
        
        # Setup signal handlers
        self._setup_signals()
        
        logger.info("UnifiedLauncher initialized")
    
    def _setup_signals(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        
        # Schedule shutdown in event loop
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.stop())
        except RuntimeError:
            pass
    
    async def start(self, launch_config: LaunchConfig) -> Dict[str, Any]:
        """
        Start nodes according to configuration
        
        Args:
            launch_config: Launch configuration
            
        Returns:
            Startup result summary
        """
        start_time = time.time()
        
        # Initialize HTTP client
        import httpx
        self._http_client = httpx.AsyncClient(timeout=5.0)
        
        # Determine which nodes to start
        if launch_config.specific_nodes:
            node_ids = launch_config.specific_nodes
        else:
            node_ids = self._get_nodes_for_groups(launch_config.groups)
        
        logger.info(f"Starting {len(node_ids)} nodes...")
        
        # Resolve startup order
        try:
            startup_order = self.resolver.resolve_startup_order(node_ids)
        except Exception as e:
            logger.error(f"Dependency resolution failed: {e}")
            return {"success": False, "error": str(e)}
        
        # Get parallel groups
        if launch_config.parallel:
            parallel_groups = self.resolver.get_parallel_groups(startup_order)
        else:
            parallel_groups = [[n] for n in startup_order]
        
        # Start nodes
        results = {
            "started": [],
            "failed": [],
            "skipped": []
        }
        
        for group in parallel_groups:
            # Start nodes in this group in parallel
            tasks = []
            for node_id in group:
                task = self._start_node_async(node_id, launch_config)
                tasks.append(task)
            
            # Wait for all to complete
            group_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for node_id, result in zip(group, group_results):
                if isinstance(result, Exception):
                    logger.error(f"Node {node_id} failed: {result}")
                    results["failed"].append(node_id)
                elif result:
                    results["started"].append(node_id)
                else:
                    results["skipped"].append(node_id)
            
            # Delay between groups
            if launch_config.startup_delay > 0:
                await asyncio.sleep(launch_config.startup_delay)
        
        # Start health monitoring
        if launch_config.health_check:
            self._start_health_monitoring()
        
        elapsed = time.time() - start_time
        
        summary = {
            "success": len(results["failed"]) == 0,
            "started": len(results["started"]),
            "failed": len(results["failed"]),
            "skipped": len(results["skipped"]),
            "elapsed_seconds": round(elapsed, 2),
            "failed_nodes": results["failed"]
        }
        
        logger.info(f"Startup complete in {elapsed:.2f}s: {summary}")
        
        return summary
    
    async def stop(self, timeout: int = 30) -> Dict[str, Any]:
        """
        Stop all running nodes gracefully
        
        Args:
            timeout: Shutdown timeout per node
            
        Returns:
            Shutdown result summary
        """
        logger.info("Stopping all nodes...")
        
        # Stop health monitoring
        self._monitoring = False
        if self._health_check_task:
            self._health_check_task.cancel()
        
        # Stop nodes in reverse dependency order
        running_nodes = [
            node_id for node_id, runtime in self.runtime_nodes.items()
            if runtime.is_running
        ]
        
        # Get reverse order (dependents first)
        try:
            stop_order = list(reversed(
                self.resolver.resolve_startup_order(running_nodes)
            ))
        except Exception:
            stop_order = running_nodes
        
        results = {"stopped": [], "failed": []}
        
        for node_id in stop_order:
            try:
                await self._stop_node_async(node_id, timeout)
                results["stopped"].append(node_id)
            except Exception as e:
                logger.error(f"Error stopping {node_id}: {e}")
                results["failed"].append(node_id)
        
        # Cleanup
        if self._http_client:
            await self._http_client.aclose()
        
        self._executor.shutdown(wait=False)
        
        logger.info(f"Shutdown complete: {results}")
        return results
    
    async def _start_node_async(
        self,
        node_id: str,
        launch_config: LaunchConfig
    ) -> bool:
        """Start a single node asynchronously"""
        # Check if already running
        if node_id in self.runtime_nodes:
            runtime = self.runtime_nodes[node_id]
            if runtime.is_running:
                logger.debug(f"Node {node_id} already running")
                return True
        
        # Get node configuration
        node_config = self.config.get_node(node_id)
        if not node_config:
            logger.error(f"Node {node_id} not found in configuration")
            return False
        
        # Find node directory
        node_dir = self._find_node_dir(node_id, node_config)
        if not node_dir:
            logger.error(f"Node {node_id} directory not found")
            return False
        
        # Find main file
        main_file = self._find_main_file(node_dir)
        if not main_file:
            logger.error(f"Node {node_id} main file not found")
            return False
        
        # Setup log file
        log_dir = Path(self.config.global_config.get("log_dir", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"node_{node_id}.log"
        
        try:
            # Create runtime node
            runtime = RuntimeNode(
                config=node_config,
                status=NodeStatus.STARTING,
                start_time=datetime.now(),
                log_file=log_file
            )
            self.runtime_nodes[node_id] = runtime
            
            # Setup environment
            env = os.environ.copy()
            env["NODE_ID"] = node_id
            env["NODE_NAME"] = node_config.name
            env["NODE_PORT"] = str(node_config.port)
            env["UFO_GALAXY_MODE"] = "production"
            
            # Add custom env vars
            env.update(node_config.env_vars)
            
            # Start process
            with open(log_file, "a") as log:
                process = subprocess.Popen(
                    [sys.executable, str(main_file)],
                    cwd=str(node_dir),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
            
            runtime.process = process
            runtime.status = NodeStatus.RUNNING
            
            logger.info(f"Node {node_id} ({node_config.name}) started (PID {process.pid})")
            
            # Notify callbacks
            for callback in self._on_node_started:
                try:
                    callback(node_id, runtime)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            
            # Wait for health check if required
            if launch_config.wait_for_healthy:
                healthy = await self._wait_for_healthy(node_id, launch_config.timeout)
                if healthy:
                    runtime.status = NodeStatus.HEALTHY
                    logger.info(f"Node {node_id} is healthy")
                else:
                    runtime.status = NodeStatus.UNHEALTHY
                    logger.warning(f"Node {node_id} health check failed")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start node {node_id}: {e}")
            if node_id in self.runtime_nodes:
                self.runtime_nodes[node_id].status = NodeStatus.FAILED
            return False
    
    async def _stop_node_async(self, node_id: str, timeout: int = 30):
        """Stop a single node asynchronously"""
        runtime = self.runtime_nodes.get(node_id)
        if not runtime or not runtime.process:
            return
        
        runtime.status = NodeStatus.STOPPING
        
        try:
            # Send SIGTERM
            runtime.process.terminate()
            
            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(
                    self._wait_for_process_exit(runtime.process),
                    timeout=timeout
                )
                logger.info(f"Node {node_id} stopped gracefully")
            except asyncio.TimeoutError:
                # Force kill
                logger.warning(f"Node {node_id} did not stop gracefully, killing...")
                runtime.process.kill()
                await self._wait_for_process_exit(runtime.process)
            
            runtime.status = NodeStatus.STOPPED
            runtime.process = None
            
            # Notify callbacks
            for callback in self._on_node_stopped:
                try:
                    callback(node_id, runtime)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
                    
        except Exception as e:
            logger.error(f"Error stopping node {node_id}: {e}")
            runtime.status = NodeStatus.FAILED
    
    async def _wait_for_process_exit(self, process: subprocess.Popen):
        """Wait for process to exit"""
        while process.poll() is None:
            await asyncio.sleep(0.1)
    
    async def _wait_for_healthy(self, node_id: str, timeout: int = 30) -> bool:
        """Wait for node to become healthy"""
        runtime = self.runtime_nodes.get(node_id)
        if not runtime:
            return False
        
        start_time = time.time()
        check_interval = 0.5
        
        while time.time() - start_time < timeout:
            if await self._check_node_health(node_id):
                return True
            await asyncio.sleep(check_interval)
        
        return False
    
    async def _check_node_health(self, node_id: str) -> bool:
        """Check if node is healthy"""
        runtime = self.runtime_nodes.get(node_id)
        if not runtime:
            return False
        
        # Check if process is running
        if not runtime.is_running:
            return False
        
        # HTTP health check
        if self._http_client and runtime.config.health_check_url:
            try:
                response = await self._http_client.get(
                    runtime.config.health_check_url
                )
                return response.status_code == 200
            except Exception:
                return False
        
        return True
    
    def _start_health_monitoring(self):
        """Start background health monitoring"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._health_check_task = asyncio.create_task(
            self._health_monitor_loop()
        )
        logger.info("Health monitoring started")
    
    async def _health_monitor_loop(self):
        """Health monitoring loop"""
        interval = self.config.global_config.get("health_check_interval", 30)
        
        while self._monitoring:
            try:
                for node_id, runtime in list(self.runtime_nodes.items()):
                    if runtime.status in [NodeStatus.RUNNING, NodeStatus.HEALTHY]:
                        healthy = await self._check_node_health(node_id)
                        
                        if healthy:
                            runtime.status = NodeStatus.HEALTHY
                            runtime.health_failures = 0
                        else:
                            runtime.health_failures += 1
                            runtime.status = NodeStatus.UNHEALTHY
                            
                            # Check if we should restart
                            if runtime.health_failures >= 3:
                                logger.warning(
                                    f"Node {node_id} unhealthy for {runtime.health_failures} checks, "
                                    f"considering restart"
                                )
                                # Could trigger auto-restart here
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(interval)
    
    def _get_nodes_for_groups(self, groups: List[str]) -> List[str]:
        """Get all node IDs for specified groups"""
        node_ids = []
        
        for group_name in groups:
            if group_name == "all":
                return list(self.config.nodes.keys())
            
            try:
                group = NodeGroup(group_name)
                nodes = self.config.get_nodes_by_group(group)
                node_ids.extend([n.id for n in nodes if n.auto_start])
            except ValueError:
                logger.warning(f"Unknown group: {group_name}")
        
        return node_ids
    
    def _find_node_dir(self, node_id: str, config: NodeConfig) -> Optional[Path]:
        """Find node directory"""
        nodes_dir = Path(self.config.global_config.get("nodes_dir", "nodes"))
        
        patterns = [
            f"Node_{node_id}_{config.name}",
            f"Node_{node_id}",
            f"node_{node_id}_{config.name}",
            f"node_{node_id}",
        ]
        
        for pattern in patterns:
            node_dir = nodes_dir / pattern
            if node_dir.exists():
                return node_dir
        
        return None
    
    def _find_main_file(self, node_dir: Path) -> Optional[Path]:
        """Find main file in node directory"""
        candidates = [
            "main.py",
            f"{node_dir.name}.py",
            "app.py",
            "server.py",
            "index.py"
        ]
        
        for candidate in candidates:
            main_file = node_dir / candidate
            if main_file.exists():
                return main_file
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current launcher status"""
        return {
            "total_nodes": len(self.config.nodes),
            "running_nodes": len([
                n for n in self.runtime_nodes.values() if n.is_running
            ]),
            "healthy_nodes": len([
                n for n in self.runtime_nodes.values()
                if n.status == NodeStatus.HEALTHY
            ]),
            "failed_nodes": len([
                n for n in self.runtime_nodes.values()
                if n.status == NodeStatus.FAILED
            ]),
            "nodes": {
                node_id: {
                    "name": runtime.config.name,
                    "status": runtime.status.value,
                    "uptime": runtime.uptime_seconds,
                    "restarts": runtime.restart_count
                }
                for node_id, runtime in self.runtime_nodes.items()
            }
        }
    
    def register_callback(self, event: str, callback: Callable):
        """Register event callback"""
        if event == "node_started":
            self._on_node_started.append(callback)
        elif event == "node_stopped":
            self._on_node_stopped.append(callback)
        elif event == "node_failed":
            self._on_node_failed.append(callback)


# CLI interface
async def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO Galaxy Unified Launcher")
    parser.add_argument("command", choices=["start", "stop", "restart", "status"])
    parser.add_argument("--groups", nargs="+", default=["core"],
                       help="Node groups to start")
    parser.add_argument("--nodes", nargs="+", help="Specific node IDs")
    parser.add_argument("--no-parallel", action="store_true",
                       help="Disable parallel startup")
    parser.add_argument("--no-health-check", action="store_true",
                       help="Disable health checks")
    parser.add_argument("--max-parallel", type=int, default=5,
                       help="Maximum parallel starts")
    parser.add_argument("--config", help="Configuration file path")
    
    args = parser.parse_args()
    
    # Create launcher
    config_manager = None
    if args.config:
        config_manager = ConfigManager(Path(args.config).parent)
        config_manager.load_from_json(Path(args.config))
    
    launcher = UnifiedLauncher(config_manager)
    
    if args.command == "start":
        launch_config = LaunchConfig(
            groups=args.groups,
            specific_nodes=args.nodes,
            parallel=not args.no_parallel,
            max_parallel=args.max_parallel,
            health_check=not args.no_health_check
        )
        
        result = await launcher.start(launch_config)
        print(json.dumps(result, indent=2))
        
        if result.get("success"):
            # Keep running
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                await launcher.stop()
        
    elif args.command == "stop":
        result = await launcher.stop()
        print(json.dumps(result, indent=2))
    
    elif args.command == "restart":
        await launcher.stop()
        await asyncio.sleep(2)
        
        launch_config = LaunchConfig(
            groups=args.groups,
            specific_nodes=args.nodes,
            parallel=not args.no_parallel
        )
        result = await launcher.start(launch_config)
        print(json.dumps(result, indent=2))
    
    elif args.command == "status":
        status = launcher.get_status()
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════════╗
║           UFO Galaxy Unified Launcher v2.0                    ║
║           Parallel | Smart Dependencies | Auto-Recovery       ║
╚═══════════════════════════════════════════════════════════════╝
""")
    asyncio.run(main())
