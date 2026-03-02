#!/usr/bin/env python3
"""
UFO³ Galaxy 智能启动器
支持按需启动、分组管理、健康检查

特性:
1. 按需启动 - 只启动需要的节点
2. 分组管理 - 核心/扩展/可选
3. 依赖管理 - 自动启动依赖节点
4. 健康检查 - 确保节点正常运行
5. 优雅停止 - 正确关闭所有节点
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
from enum import Enum

# =============================================================================
# Configuration
# =============================================================================

NODES_DIR = Path(__file__).parent / "nodes"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 节点分组
class NodeGroup(str, Enum):
    CORE = "core"           # 核心节点（必须启动）
    EXTENDED = "extended"   # 扩展节点（按需启动）
    OPTIONAL = "optional"   # 可选节点（默认不启动）

# 节点配置
NODE_CONFIG = {
    # 核心系统 (必须)
    "00": {"name": "StateMachine", "group": NodeGroup.CORE, "port": 8000, "deps": []},
    "01": {"name": "OneAPI", "group": NodeGroup.CORE, "port": 8001, "deps": []},
    "02": {"name": "Tasker", "group": NodeGroup.CORE, "port": 8002, "deps": ["00"]},
    "03": {"name": "Router", "group": NodeGroup.CORE, "port": 8003, "deps": ["00"]},
    "04": {"name": "Email", "group": NodeGroup.EXTENDED, "port": 8004, "deps": []},
    "05": {"name": "Auth", "group": NodeGroup.CORE, "port": 8005, "deps": []},
    "06": {"name": "Filesystem", "group": NodeGroup.CORE, "port": 8006, "deps": []},
    "07": {"name": "Git", "group": NodeGroup.EXTENDED, "port": 8007, "deps": []},
    "08": {"name": "Calendar", "group": NodeGroup.EXTENDED, "port": 8008, "deps": []},
    "09": {"name": "Sandbox", "group": NodeGroup.EXTENDED, "port": 8009, "deps": []},
    
    # 第三方服务
    "10": {"name": "Slack", "group": NodeGroup.OPTIONAL, "port": 8010, "deps": []},
    "11": {"name": "GitHub", "group": NodeGroup.EXTENDED, "port": 8011, "deps": []},
    "12": {"name": "Postgres", "group": NodeGroup.EXTENDED, "port": 8012, "deps": []},
    "13": {"name": "SQLite", "group": NodeGroup.EXTENDED, "port": 8013, "deps": []},
    "14": {"name": "Elasticsearch", "group": NodeGroup.OPTIONAL, "port": 8014, "deps": []},
    "15": {"name": "OCR", "group": NodeGroup.EXTENDED, "port": 8015, "deps": []},
    "16": {"name": "Email", "group": NodeGroup.EXTENDED, "port": 8016, "deps": []},
    "17": {"name": "Crypto", "group": NodeGroup.EXTENDED, "port": 8017, "deps": []},
    "18": {"name": "DeepL", "group": NodeGroup.OPTIONAL, "port": 8018, "deps": []},
    "19": {"name": "EdgeTTS", "group": NodeGroup.EXTENDED, "port": 8019, "deps": []},
    "20": {"name": "S3", "group": NodeGroup.OPTIONAL, "port": 8020, "deps": []},
    "21": {"name": "Notion", "group": NodeGroup.OPTIONAL, "port": 8021, "deps": []},
    "22": {"name": "BraveSearch", "group": NodeGroup.EXTENDED, "port": 8022, "deps": []},
    "23": {"name": "Time", "group": NodeGroup.EXTENDED, "port": 8123, "deps": []},
    "24": {"name": "Weather", "group": NodeGroup.EXTENDED, "port": 8024, "deps": []},
    "25": {"name": "GoogleSearch", "group": NodeGroup.OPTIONAL, "port": 8025, "deps": []},
    
    # 硬件控制
    "28": {"name": "LinuxDBus", "group": NodeGroup.OPTIONAL, "port": 8028, "deps": []},
    "29": {"name": "SSH", "group": NodeGroup.EXTENDED, "port": 8029, "deps": []},
    "30": {"name": "SFTP", "group": NodeGroup.EXTENDED, "port": 8030, "deps": []},
    "31": {"name": "MQTT", "group": NodeGroup.OPTIONAL, "port": 8031, "deps": []},
    "32": {"name": "CANbus", "group": NodeGroup.OPTIONAL, "port": 8032, "deps": []},
    "33": {"name": "ADB", "group": NodeGroup.EXTENDED, "port": 8033, "deps": []},
    "34": {"name": "BLE", "group": NodeGroup.OPTIONAL, "port": 8034, "deps": []},
    "35": {"name": "NFC", "group": NodeGroup.OPTIONAL, "port": 8035, "deps": []},
    "36": {"name": "Camera", "group": NodeGroup.OPTIONAL, "port": 8036, "deps": []},
    "37": {"name": "Audio", "group": NodeGroup.OPTIONAL, "port": 8037, "deps": []},
    "38": {"name": "Serial", "group": NodeGroup.OPTIONAL, "port": 8038, "deps": []},
    
    # 智能推理
    "50": {"name": "Transformer", "group": NodeGroup.EXTENDED, "port": 8050, "deps": ["01"]},
    "51": {"name": "NLU", "group": NodeGroup.EXTENDED, "port": 8051, "deps": ["01"]},
    "52": {"name": "Qiskit", "group": NodeGroup.OPTIONAL, "port": 8052, "deps": []},
    "53": {"name": "GraphLogic", "group": NodeGroup.OPTIONAL, "port": 8053, "deps": []},
    "54": {"name": "SymbolicMath", "group": NodeGroup.OPTIONAL, "port": 8054, "deps": []},
    "56": {"name": "MultiAgent", "group": NodeGroup.OPTIONAL, "port": 8056, "deps": ["01"]},
    "57": {"name": "ReinforcementLearning", "group": NodeGroup.OPTIONAL, "port": 8057, "deps": []},
    "58": {"name": "NeuralArchSearch", "group": NodeGroup.OPTIONAL, "port": 8058, "deps": []},
    "59": {"name": "FederatedLearning", "group": NodeGroup.OPTIONAL, "port": 8059, "deps": []},
    "62": {"name": "ProbabilisticProgramming", "group": NodeGroup.OPTIONAL, "port": 8062, "deps": []},
    
    # 云服务
    "64": {"name": "Telemetry", "group": NodeGroup.EXTENDED, "port": 8064, "deps": []},
    
    # 免疫系统
    "65": {"name": "LoggerCentral", "group": NodeGroup.CORE, "port": 8065, "deps": []},
    "66": {"name": "AuditLog", "group": NodeGroup.EXTENDED, "port": 8066, "deps": ["65"]},
    "67": {"name": "HealthMonitor", "group": NodeGroup.CORE, "port": 8067, "deps": ["65"]},
    "68": {"name": "Security", "group": NodeGroup.EXTENDED, "port": 8068, "deps": ["65"]},
    "69": {"name": "BackupRestore", "group": NodeGroup.EXTENDED, "port": 8069, "deps": []},
    
    # 高级功能
    "70": {"name": "BambuLab", "group": NodeGroup.OPTIONAL, "port": 8070, "deps": []},
    "71": {"name": "MediaGen", "group": NodeGroup.OPTIONAL, "port": 8071, "deps": []},
    "72": {"name": "KnowledgeBase", "group": NodeGroup.EXTENDED, "port": 8072, "deps": []},
    "73": {"name": "Learning", "group": NodeGroup.EXTENDED, "port": 8073, "deps": []},
    "74": {"name": "DigitalTwin", "group": NodeGroup.OPTIONAL, "port": 8074, "deps": []},
    
    # 新增节点
    "79": {"name": "LocalLLM", "group": NodeGroup.CORE, "port": 8079, "deps": []},
    "80": {"name": "MemorySystem", "group": NodeGroup.CORE, "port": 8080, "deps": []},
}

# =============================================================================
# Node Manager
# =============================================================================

class NodeManager:
    """节点管理器"""
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running_nodes: Set[str] = set()
        self.http_client = httpx.AsyncClient(timeout=5)
    
    def get_node_dir(self, node_id: str) -> Optional[Path]:
        """获取节点目录"""
        config = NODE_CONFIG.get(node_id)
        if not config:
            return None
        
        # 尝试多种命名格式
        patterns = [
            f"Node_{node_id}_{config['name']}",
            f"Node_{node_id}",
        ]
        
        for pattern in patterns:
            node_dir = NODES_DIR / pattern
            if node_dir.exists():
                return node_dir
        
        return None
    
    def start_node(self, node_id: str) -> bool:
        """启动单个节点"""
        if node_id in self.running_nodes:
            print(f"  ⚠️  Node {node_id} already running")
            return True
        
        config = NODE_CONFIG.get(node_id)
        if not config:
            print(f"  ❌ Node {node_id} not found in config")
            return False
        
        node_dir = self.get_node_dir(node_id)
        if not node_dir:
            print(f"  ❌ Node {node_id} directory not found")
            return False
        
        main_file = node_dir / "main.py"
        if not main_file.exists():
            print(f"  ❌ Node {node_id} main.py not found")
            return False
        
        # 启动节点
        log_file = LOG_DIR / f"node_{node_id}.log"
        
        try:
            env = os.environ.copy()
            env["NODE_ID"] = node_id
            env["NODE_NAME"] = config["name"]
            env["PORT"] = str(config["port"])
            
            log_handle = open(log_file, "w")
            process = subprocess.Popen(
                [sys.executable, str(main_file)],
                cwd=str(node_dir),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            
            self.processes[node_id] = process
            self.running_nodes.add(node_id)
            
            print(f"  ✅ Node {node_id} ({config['name']}) started on port {config['port']}")
            return True
        
        except Exception as e:
            print(f"  ❌ Failed to start Node {node_id}: {e}")
            return False
    
    async def check_node_health(self, node_id: str) -> bool:
        """检查节点健康状态"""
        config = NODE_CONFIG.get(node_id)
        if not config:
            return False
        
        try:
            response = await self.http_client.get(f"http://localhost:{config['port']}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def wait_for_node(self, node_id: str, timeout: int = 10) -> bool:
        """等待节点启动"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if await self.check_node_health(node_id):
                return True
            await asyncio.sleep(0.5)
        
        return False
    
    def stop_node(self, node_id: str):
        """停止单个节点"""
        if node_id not in self.running_nodes:
            return
        
        process = self.processes.get(node_id)
        if process:
            try:
                # 发送 SIGTERM
                process.terminate()
                
                # 等待 5 秒
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 强制杀死
                    process.kill()
                    process.wait()
                
                print(f"  ✅ Node {node_id} stopped")
            except Exception as e:
                print(f"  ⚠️  Error stopping Node {node_id}: {e}")
        
        self.running_nodes.discard(node_id)
        self.processes.pop(node_id, None)
    
    def stop_all(self):
        """停止所有节点"""
        print("\n🛑 Stopping all nodes...")
        
        for node_id in list(self.running_nodes):
            self.stop_node(node_id)
        
        print("✅ All nodes stopped")
    
    async def start_group(self, group: NodeGroup, check_health: bool = True):
        """启动节点组"""
        print(f"\n🚀 Starting {group.value} nodes...")
        
        # 获取该组的所有节点
        nodes_to_start = [
            node_id for node_id, config in NODE_CONFIG.items()
            if config["group"] == group
        ]
        
        # 启动节点
        for node_id in nodes_to_start:
            config = NODE_CONFIG[node_id]
            
            # 先启动依赖节点
            for dep_id in config["deps"]:
                if dep_id not in self.running_nodes:
                    self.start_node(dep_id)
                    if check_health:
                        await self.wait_for_node(dep_id)
            
            # 启动当前节点
            self.start_node(node_id)
            
            # 健康检查
            if check_health:
                if await self.wait_for_node(node_id):
                    print(f"    ✓ Health check passed")
                else:
                    print(f"    ⚠️  Health check failed (may need more time)")
    
    async def start_nodes(self, node_ids: List[str], check_health: bool = True):
        """启动指定节点"""
        print(f"\n🚀 Starting specified nodes...")
        
        for node_id in node_ids:
            if node_id not in NODE_CONFIG:
                print(f"  ❌ Node {node_id} not found")
                continue
            
            config = NODE_CONFIG[node_id]
            
            # 先启动依赖节点
            for dep_id in config["deps"]:
                if dep_id not in self.running_nodes:
                    self.start_node(dep_id)
                    if check_health:
                        await self.wait_for_node(dep_id)
            
            # 启动当前节点
            self.start_node(node_id)
            
            # 健康检查
            if check_health:
                if await self.wait_for_node(node_id):
                    print(f"    ✓ Health check passed")
                else:
                    print(f"    ⚠️  Health check failed")
    
    async def status(self):
        """显示节点状态"""
        print("\n📊 Node Status:")
        print(f"{'ID':<4} {'Name':<25} {'Group':<10} {'Port':<6} {'Status':<10}")
        print("-" * 65)
        
        for node_id, config in sorted(NODE_CONFIG.items()):
            status = "🟢 Running" if node_id in self.running_nodes else "⚫ Stopped"
            
            if node_id in self.running_nodes:
                healthy = await self.check_node_health(node_id)
                status = "🟢 Healthy" if healthy else "🟡 Unhealthy"
            
            print(f"{node_id:<4} {config['name']:<25} {config['group'].value:<10} {config['port']:<6} {status}")
        
        print(f"\nTotal: {len(self.running_nodes)}/{len(NODE_CONFIG)} nodes running")

# =============================================================================
# CLI
# =============================================================================

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO³ Galaxy Launcher")
    parser.add_argument("command", choices=["start", "stop", "restart", "status"], help="Command to execute")
    parser.add_argument("--group", choices=["core", "extended", "optional", "all"], default="core", help="Node group to start")
    parser.add_argument("--nodes", nargs="+", help="Specific node IDs to start")
    parser.add_argument("--no-health-check", action="store_true", help="Skip health checks")
    
    args = parser.parse_args()
    
    manager = NodeManager()
    
    # 信号处理
    def signal_handler(sig, frame):
        print("\n\n⚠️  Received interrupt signal")
        manager.stop_all()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.command == "start":
            if args.nodes:
                # 启动指定节点
                await manager.start_nodes(args.nodes, not args.no_health_check)
            else:
                # 启动节点组
                if args.group == "all":
                    for group in [NodeGroup.CORE, NodeGroup.EXTENDED, NodeGroup.OPTIONAL]:
                        await manager.start_group(group, not args.no_health_check)
                else:
                    await manager.start_group(NodeGroup(args.group), not args.no_health_check)
            
            print("\n✅ Startup complete")
            print("📝 Logs: logs/")
            print("🛑 Press Ctrl+C to stop all nodes")
            
            # 保持运行
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass
        
        elif args.command == "stop":
            manager.stop_all()
        
        elif args.command == "restart":
            manager.stop_all()
            await asyncio.sleep(2)
            
            if args.nodes:
                await manager.start_nodes(args.nodes, not args.no_health_check)
            else:
                await manager.start_group(NodeGroup(args.group), not args.no_health_check)
        
        elif args.command == "status":
            await manager.status()
    
    finally:
        await manager.http_client.aclose()

if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════╗
║   UFO³ Galaxy Intelligent Launcher    ║
║   75 Nodes | On-Demand | Optimized    ║
╚═══════════════════════════════════════╝
""")
    
    asyncio.run(main())
