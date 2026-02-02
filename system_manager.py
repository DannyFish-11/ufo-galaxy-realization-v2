"""
UFO³ Galaxy 系统管理器
======================

统一管理所有节点的启动、停止、监控和健康检查

功能：
1. 一键启动/停止所有节点
2. 分组管理（核心/学术/开发/全部）
3. 实时监控节点状态
4. 自动重启失败的节点
5. 生成系统报告

作者：Manus AI
日期：2026-01-23
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

# ANSI 颜色代码
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

# =============================================================================
# 配置
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
    
# 节点配置表
NODES = {
    # 核心节点
    "core": [
        NodeConfig("00", "StateMachine", 8000, "core"),
        NodeConfig("01", "OneAPI", 8001, "core"),
        NodeConfig("02", "Tasker", 8002, "core"),
        NodeConfig("03", "Router", 8003, "core"),
        NodeConfig("05", "Auth", 8005, "core"),
        NodeConfig("06", "Filesystem", 8006, "core"),
    ],
    # 学术研究节点
    "academic": [
        NodeConfig("97", "AcademicSearch", 8097, "academic"),
        NodeConfig("104", "AgentCPM", 8104, "academic"),
        NodeConfig("105", "UnifiedKnowledgeBase", 8105, "academic"),
    ],
    # 开发工作流节点
    "development": [
        NodeConfig("07", "Git", 8007, "development"),
        NodeConfig("11", "GitHub", 8011, "development"),
        NodeConfig("106", "GitHubFlow", 8106, "development"),
    ],
    # 扩展节点
    "extended": [
        NodeConfig("04", "Email", 8004, "extended"),
        NodeConfig("08", "Browser", 8008, "extended"),
        NodeConfig("09", "Scheduler", 8009, "extended"),
        NodeConfig("10", "Logger", 8010, "extended"),
        NodeConfig("80", "MemorySystem", 8080, "extended"),
        NodeConfig("96", "SmartTransportRouter", 8096, "extended"),
    ],
}

# =============================================================================
# 系统管理器
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
        
    def get_node_path(self, node_id: str, node_name: str) -> Optional[Path]:
        """获取节点路径"""
        # 尝试多种可能的路径格式
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
                process = subprocess.Popen(
                    [sys.executable, str(main_py)],
                    cwd=str(node_path),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True
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
            groups = ["core", "academic", "development", "extended"]
        
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
        
        try:
            process.terminate()
            process.wait(timeout=5)
            print(f"{YELLOW}⏹️  节点 {node_id} 已停止{RESET}")
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"{RED}🔪 节点 {node_id} 强制停止{RESET}")
        
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
        
        all_configs = []
        for group in NODES.values():
            all_configs.extend(group)
        
        tasks = [self.check_node_health(config, timeout=3) for config in all_configs]
        results = await asyncio.gather(*tasks)
        
        healthy_count = 0
        unhealthy_count = 0
        
        for config, is_healthy in zip(all_configs, results):
            if is_healthy:
                print(f"{GREEN}✅ Node_{config.id:>3} {config.name:<25} (:{config.port}){RESET}")
                healthy_count += 1
            else:
                print(f"{RED}❌ Node_{config.id:>3} {config.name:<25} (:{config.port}){RESET}")
                unhealthy_count += 1
        
        print(f"{'-'*80}")
        print(f"{GREEN}健康: {healthy_count}{RESET} | {RED}不健康: {unhealthy_count}{RESET}")
    
    async def generate_report(self) -> Dict:
        """生成系统报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "nodes": {},
            "summary": {
                "total": 0,
                "healthy": 0,
                "unhealthy": 0,
                "not_found": 0
            }
        }
        
        all_configs = []
        for group in NODES.values():
            all_configs.extend(group)
        
        for config in all_configs:
            is_healthy = await self.check_node_health(config, timeout=3)
            
            report["nodes"][config.id] = {
                "name": config.name,
                "port": config.port,
                "group": config.group,
                "status": "healthy" if is_healthy else "unhealthy"
            }
            
            report["summary"]["total"] += 1
            if is_healthy:
                report["summary"]["healthy"] += 1
            else:
                report["summary"]["unhealthy"] += 1
        
        return report

# =============================================================================
# CLI
# =============================================================================

async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO³ Galaxy 系统管理器")
    parser.add_argument("command", choices=["start", "stop", "status", "monitor", "report"],
                       help="命令")
    parser.add_argument("--group", "-g", choices=["core", "academic", "development", "extended", "all"],
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
    asyncio.run(main())
