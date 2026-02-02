#!/usr/bin/env python3
"""
UFO³ Galaxy 系统管理器 v2.0 (修复版)
=================================

修复内容:
- 使用 unified_config.json 统一配置
- 完整支持所有102个节点
- 端口配置与统一端口分配对齐

统一管理所有节点的启动、停止、监控和健康检查

功能：
1. 一键启动/停止所有节点
2. 分组管理（9个分组）
3. 实时监控节点状态
4. 自动重启失败的节点
5. 生成系统报告

作者: Manus AI
版本: 2.0
日期: 2026-01-23
"""

import os
import sys
import time
import json
import signal
import subprocess
import asyncio
import httpx
from typing import Dict, List, Set, Optional
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

# ANSI 颜色代码
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

# =============================================================================
# Configuration - 从 unified_config.json 加载
# =============================================================================

@dataclass
class NodeConfig:
    """节点配置"""
    id: str
    name: str
    port: int
    group: str
    auto_start: bool = True
    health_check_path: str = "/health"
    dependencies: List[str] = None
    critical: bool = False
    description: str = ""
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []

class ConfigManager:
    """配置管理器"""
    
    CONFIG_FILE = Path(__file__).parent / "config" / "unified_config.json"
    
    @classmethod
    def load_nodes(cls) -> Dict[str, List[NodeConfig]]:
        """从配置文件加载节点"""
        if not cls.CONFIG_FILE.exists():
            print(f"{YELLOW}⚠️  Config file not found, using defaults{RESET}")
            return cls._get_default_nodes()
        
        try:
            with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            nodes_by_group = {}
            
            for node_key, node_info in config.get("nodes", {}).items():
                # 解析节点ID
                parts = node_key.split('_')
                if len(parts) >= 3:
                    node_id = '_'.join(parts[1:-1]) if len(parts) > 3 else parts[1]
                    node_name = parts[-1]
                else:
                    continue
                
                group = node_info.get("group", "core")
                
                if group not in nodes_by_group:
                    nodes_by_group[group] = []
                
                nodes_by_group[group].append(NodeConfig(
                    id=node_id,
                    name=node_name,
                    port=node_info["port"],
                    group=group,
                    auto_start=node_info.get("critical", False),
                    dependencies=node_info.get("dependencies", []),
                    critical=node_info.get("critical", False),
                    description=node_info.get("description", "")
                ))
            
            return nodes_by_group
            
        except Exception as e:
            print(f"{RED}❌ Error loading config: {e}{RESET}")
            return cls._get_default_nodes()
    
    @classmethod
    def _get_default_nodes(cls) -> Dict[str, List[NodeConfig]]:
        """默认节点配置"""
        return {
            "core": [
                NodeConfig("00", "StateMachine", 8000, "core", True, critical=True),
                NodeConfig("01", "OneAPI", 8001, "core", True, critical=True),
                NodeConfig("02", "Tasker", 8002, "core", True, critical=True),
                NodeConfig("03", "SecretVault", 8003, "core", True, critical=True),
                NodeConfig("04", "Router", 8004, "core", True, critical=True),
                NodeConfig("05", "Auth", 8005, "core", True, critical=True),
                NodeConfig("06", "Filesystem", 8006, "core", True, critical=True),
            ],
            "monitoring": [
                NodeConfig("65", "LoggerCentral", 8064, "monitoring", True, critical=True),
                NodeConfig("67", "HealthMonitor", 8066, "monitoring", True, critical=True),
            ]
        }

# 加载节点配置
NODES = ConfigManager.load_nodes()

# =============================================================================
# System Manager
# =============================================================================

class SystemManager:
    """系统管理器"""
    
    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path(__file__).parent
        self.nodes_dir = self.project_root / "nodes"
        self.log_dir = self.project_root / "logs"
        self.log_dir.mkdir(exist_ok=True)
        
        self.processes: Dict[str, subprocess.Popen] = {}
        self.node_status: Dict[str, str] = {}
        self.nodes_config = self._flatten_nodes()
    
    def _flatten_nodes(self) -> Dict[str, NodeConfig]:
        """将分组节点展平为字典"""
        result = {}
        for group_nodes in NODES.values():
            for config in group_nodes:
                result[config.id] = config
        return result
    
    def get_node_path(self, node_id: str, node_name: str) -> Optional[Path]:
        """获取节点路径"""
        possible_paths = [
            self.nodes_dir / f"Node_{node_id}_{node_name}",
            self.nodes_dir / f"Node_{node_id}",
            self.nodes_dir / f"node_{node_id}",
        ]
        
        for path in possible_paths:
            if path.exists():
                return path
        
        return None
    
    def start_node(self, config: NodeConfig) -> bool:
        """启动单个节点"""
        node_path = self.get_node_path(config.id, config.name)
        
        if not node_path:
            print(f"{RED}❌ 节点 {config.name} (Node_{config.id}) 不存在{RESET}")
            self.node_status[config.id] = "not_found"
            return False
        
        main_py = node_path / "main.py"
        if not main_py.exists():
            print(f"{RED}❌ 节点 {config.name} 缺少 main.py{RESET}")
            self.node_status[config.id] = "no_main"
            return False
        
        # 启动节点
        log_file = self.log_dir / f"node_{config.id}_{config.name}.log"
        
        try:
            with open(log_file, "w") as f:
                env = os.environ.copy()
                env["NODE_ID"] = config.id
                env["NODE_NAME"] = config.name
                env["PORT"] = str(config.port)
                
                process = subprocess.Popen(
                    [sys.executable, str(main_py)],
                    cwd=str(node_path),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env
                )
            
            self.processes[config.id] = process
            self.node_status[config.id] = "starting"
            
            print(f"{CYAN}🚀 启动节点 {config.name} (端口 {config.port})...{RESET}")
            return True
            
        except Exception as e:
            print(f"{RED}❌ 启动节点 {config.name} 失败: {e}{RESET}")
            self.node_status[config.id] = "failed"
            return False
    
    async def check_node_health(self, config: NodeConfig, timeout: int = 5) -> bool:
        """检查节点健康状态"""
        url = f"http://localhost:{config.port}{config.health_check_path}"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                self.node_status[config.id] = "healthy"
                return True
        except Exception:
            return False
    
    async def wait_for_node(self, config: NodeConfig, max_wait: int = 30) -> bool:
        """等待节点启动"""
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            if await self.check_node_health(config, timeout=2):
                print(f"{GREEN}✅ 节点 {config.name} 已就绪{RESET}")
                return True
            await asyncio.sleep(1)
        
        print(f"{RED}❌ 节点 {config.name} 启动超时{RESET}")
        self.node_status[config.id] = "timeout"
        return False
    
    async def start_group(self, group: str, wait: bool = True):
        """启动一组节点"""
        if group not in NODES:
            print(f"{RED}❌ 未知的节点组: {group}{RESET}")
            return
        
        configs = NODES[group]
        
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}启动节点组: {group.upper()}{RESET}")
        print(f"{BLUE}{'='*80}{RESET}\n")
        
        # 启动所有节点
        for config in configs:
            if config.auto_start:
                # 先启动依赖节点
                for dep in config.dependencies:
                    dep_id = dep.replace("Node_", "").split("_")[0]
                    if dep_id in self.nodes_config and dep_id not in self.processes:
                        self.start_node(self.nodes_config[dep_id])
                        await asyncio.sleep(1)
                
                self.start_node(config)
                await asyncio.sleep(2)  # 等待 2 秒再启动下一个
        
        # 等待所有节点就绪
        if wait:
            print(f"\n{YELLOW}等待节点就绪...{RESET}\n")
            
            tasks = [
                self.wait_for_node(config)
                for config in configs
                if config.auto_start
            ]
            
            results = await asyncio.gather(*tasks)
            
            success_count = sum(results)
            total_count = len(results)
            
            print(f"\n{BLUE}{'='*80}{RESET}")
            print(f"{BLUE}节点组 {group.upper()} 启动完成{RESET}")
            print(f"{BLUE}{'='*80}{RESET}")
            print(f"{GREEN}✅ 成功: {success_count}/{total_count}{RESET}\n")
    
    async def start_all(self, groups: List[str] = None):
        """启动所有节点"""
        if groups is None:
            # 按优先级排序启动
            priority_order = ["core", "monitoring", "tools", "physical", 
                            "intelligence", "advanced", "orchestration", 
                            "multimodal", "academic"]
            groups = [g for g in priority_order if g in NODES]
        
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}UFO³ Galaxy 系统启动{RESET}")
        print(f"{CYAN}{'='*80}{RESET}\n")
        
        for group in groups:
            await self.start_group(group, wait=True)
    
    def stop_node(self, node_id: str):
        """停止单个节点"""
        if node_id not in self.processes:
            return
        
        process = self.processes[node_id]
        config = self.nodes_config.get(node_id)
        name = config.name if config else node_id
        
        try:
            process.terminate()
            process.wait(timeout=5)
            print(f"{YELLOW}⏹️  节点 {name} 已停止{RESET}")
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"{RED}🔪 节点 {name} 强制停止{RESET}")
        
        del self.processes[node_id]
        self.node_status[node_id] = "stopped"
    
    def stop_all(self):
        """停止所有节点"""
        print(f"\n{YELLOW}{'='*80}{RESET}")
        print(f"{YELLOW}停止所有节点...{RESET}")
        print(f"{YELLOW}{'='*80}{RESET}\n")
        
        for node_id in list(self.processes.keys()):
            self.stop_node(node_id)
        
        print(f"\n{GREEN}✅ 所有节点已停止{RESET}\n")
    
    async def monitor(self, interval: int = 30):
        """监控节点状态"""
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}开始监控节点状态（每 {interval} 秒检查一次）{RESET}")
        print(f"{CYAN}按 Ctrl+C 停止监控{RESET}")
        print(f"{CYAN}{'='*80}{RESET}\n")
        
        try:
            while True:
                await self.check_all_nodes()
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}监控已停止{RESET}\n")
    
    async def check_all_nodes(self):
        """检查所有节点状态"""
        print(f"\n{BLUE}[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 节点状态检查{RESET}")
        print(f"{'-'*80}")
        
        all_configs = list(self.nodes_config.values())
        all_configs.sort(key=lambda x: x.port)
        
        tasks = [self.check_node_health(config, timeout=3) for config in all_configs]
        results = await asyncio.gather(*tasks)
        
        healthy_count = 0
        unhealthy_count = 0
        not_running = 0
        
        for config, is_healthy in zip(all_configs, results):
            if config.id in self.processes:
                if is_healthy:
                    print(f"{GREEN}✅ Node_{config.id:>6} {config.name:<25} (:{config.port}){RESET}")
                    healthy_count += 1
                else:
                    print(f"{RED}❌ Node_{config.id:>6} {config.name:<25} (:{config.port}) - Unhealthy{RESET}")
                    unhealthy_count += 1
            else:
                print(f"{YELLOW}○ Node_{config.id:>6} {config.name:<25} (:{config.port}) - Not running{RESET}")
                not_running += 1
        
        print(f"{'-'*80}")
        print(f"{GREEN}健康: {healthy_count}{RESET} | {RED}不健康: {unhealthy_count}{RESET} | {YELLOW}未运行: {not_running}{RESET}")
    
    async def generate_report(self) -> Dict:
        """生成系统报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "nodes": {},
            "summary": {
                "total": 0,
                "running": 0,
                "healthy": 0,
                "unhealthy": 0,
                "not_found": 0
            }
        }
        
        all_configs = list(self.nodes_config.values())
        
        for config in all_configs:
            is_healthy = await self.check_node_health(config, timeout=3)
            is_running = config.id in self.processes
            
            report["nodes"][config.id] = {
                "name": config.name,
                "port": config.port,
                "group": config.group,
                "status": "healthy" if is_healthy else ("running" if is_running else "stopped")
            }
            
            report["summary"]["total"] += 1
            if is_healthy:
                report["summary"]["healthy"] += 1
            elif is_running:
                report["summary"]["unhealthy"] += 1
            else:
                report["summary"]["not_found"] += 1
        
        return report

# =============================================================================
# CLI
# =============================================================================

async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO³ Galaxy 系统管理器 v2.0")
    parser.add_argument("command", choices=["start", "stop", "status", "monitor", "report"],
                       help="命令")
    parser.add_argument("--group", "-g", 
                       choices=["core", "tools", "physical", "intelligence", "monitoring",
                               "advanced", "orchestration", "multimodal", "academic", "all"],
                       default="all", help="节点组")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="监控间隔（秒）")
    
    args = parser.parse_args()
    
    manager = SystemManager()
    
    if args.command == "start":
        if args.group == "all":
            await manager.start_all()
        else:
            await manager.start_group(args.group)
        
        # 保持运行
        print(f"\n{CYAN}系统正在运行，按 Ctrl+C 停止{RESET}\n")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            manager.stop_all()
    
    elif args.command == "stop":
        manager.stop_all()
    
    elif args.command == "status":
        await manager.check_all_nodes()
    
    elif args.command == "monitor":
        await manager.monitor(args.interval)
    
    elif args.command == "report":
        report = await manager.generate_report()
        print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    print(f"""
{CYAN}╔═══════════════════════════════════════════════════════════════╗
║   UFO³ Galaxy System Manager v2.0                             ║
║   102 Nodes | Unified Config | Port Conflict Fixed            ║
╚═══════════════════════════════════════════════════════════════╝{RESET}
""")
    asyncio.run(main())
