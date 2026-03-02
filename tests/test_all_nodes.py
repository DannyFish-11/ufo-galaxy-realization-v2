#!/usr/bin/env python3
"""
UFO Galaxy 70-Node Complete Test Suite
======================================
测试所有 70 个节点的基本功能
"""

import asyncio
import subprocess
import sys
import time
import os
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@dataclass
class NodeInfo:
    """节点信息"""
    id: str
    name: str
    port: int
    layer: str
    status: str = "unknown"
    message: str = ""

# 完整的 70 节点定义
ALL_NODES = [
    # Layer 0: Kernel (12 nodes)
    NodeInfo("00", "StateMachine", 8000, "L0_Kernel"),
    NodeInfo("01", "OneAPI", 8001, "L0_Kernel"),
    NodeInfo("02", "Tasker", 8002, "L0_Kernel"),
    NodeInfo("03", "SecretVault", 8003, "L0_Kernel"),
    NodeInfo("04", "Router", 8004, "L0_Kernel"),
    NodeInfo("05", "Auth", 8005, "L0_Kernel"),
    NodeInfo("64", "Telemetry", 8064, "L0_Kernel"),
    NodeInfo("65", "LoggerCentral", 8065, "L0_Kernel"),
    NodeInfo("66", "ConfigManager", 8066, "L0_Kernel"),
    NodeInfo("67", "HealthMonitor", 8067, "L0_Kernel"),
    NodeInfo("68", "Security", 8068, "L0_Kernel"),
    NodeInfo("69", "BackupRestore", 8069, "L0_Kernel"),
    
    # Layer 1: Gateway (14 nodes)
    NodeInfo("50", "Transformer", 8050, "L1_Gateway"),
    NodeInfo("51", "QuantumDispatcher", 8051, "L1_Gateway"),
    NodeInfo("52", "QiskitSimulator", 8052, "L1_Gateway"),
    NodeInfo("53", "GraphLogic", 8053, "L1_Gateway"),
    NodeInfo("54", "SymbolicMath", 8054, "L1_Gateway"),
    NodeInfo("55", "Simulation", 8055, "L1_Gateway"),
    NodeInfo("56", "AgentSwarm", 8056, "L1_Gateway"),
    NodeInfo("57", "QuantumCloud", 8057, "L1_Gateway"),
    NodeInfo("58", "ModelRouter", 8058, "L1_Gateway"),
    NodeInfo("59", "CausalInference", 8059, "L1_Gateway"),
    NodeInfo("60", "TemporalLogic", 8060, "L1_Gateway"),
    NodeInfo("61", "GeometricReasoning", 8061, "L1_Gateway"),
    NodeInfo("62", "ProbabilisticProgramming", 8062, "L1_Gateway"),
    NodeInfo("63", "GameTheory", 8063, "L1_Gateway"),
    
    # Layer 2: Tools (27 nodes, including 7 reserved)
    NodeInfo("06", "Filesystem", 8006, "L2_Tools"),
    NodeInfo("07", "Git", 8007, "L2_Tools"),
    NodeInfo("08", "Fetch", 8008, "L2_Tools"),
    NodeInfo("09", "Search", 8009, "L2_Tools"),
    NodeInfo("10", "Slack", 8010, "L2_Tools"),
    NodeInfo("11", "GitHub", 8011, "L2_Tools"),
    NodeInfo("12", "Postgres", 8012, "L2_Tools"),
    NodeInfo("13", "SQLite", 8013, "L2_Tools"),
    NodeInfo("14", "FFmpeg", 8014, "L2_Tools"),
    NodeInfo("15", "OCR", 8015, "L2_Tools"),
    NodeInfo("16", "Email", 8016, "L2_Tools"),
    NodeInfo("17", "EdgeTTS", 8017, "L2_Tools"),
    NodeInfo("18", "DeepL", 8018, "L2_Tools"),
    NodeInfo("19", "Crypto", 8019, "L2_Tools"),
    NodeInfo("20", "Qdrant", 8020, "L2_Tools"),
    NodeInfo("21", "Notion", 8021, "L2_Tools"),
    NodeInfo("22", "BraveSearch", 8022, "L2_Tools"),
    NodeInfo("23", "Time", 8123, "L2_Tools"),
    NodeInfo("24", "Weather", 8024, "L2_Tools"),
    NodeInfo("25", "GoogleSearch", 8025, "L2_Tools"),
    NodeInfo("26", "Reserved", 8026, "L2_Tools"),
    NodeInfo("27", "Reserved", 8027, "L2_Tools"),
    NodeInfo("28", "Reserved", 8028, "L2_Tools"),
    NodeInfo("29", "Reserved", 8029, "L2_Tools"),
    NodeInfo("30", "Reserved", 8030, "L2_Tools"),
    NodeInfo("31", "Reserved", 8031, "L2_Tools"),
    NodeInfo("32", "Reserved", 8032, "L2_Tools"),
    
    # Layer 3: Physical (17 nodes)
    NodeInfo("33", "ADB", 8033, "L3_Physical"),
    NodeInfo("34", "Scrcpy", 8034, "L3_Physical"),
    NodeInfo("35", "AppleScript", 8035, "L3_Physical"),
    NodeInfo("36", "UIAWindows", 8036, "L3_Physical"),
    NodeInfo("37", "LinuxDBus", 8037, "L3_Physical"),
    NodeInfo("38", "BLE", 8038, "L3_Physical"),
    NodeInfo("39", "SSH", 8039, "L3_Physical"),
    NodeInfo("40", "SFTP", 8040, "L3_Physical"),
    NodeInfo("41", "MQTT", 8041, "L3_Physical"),
    NodeInfo("42", "CANbus", 8042, "L3_Physical"),
    NodeInfo("43", "MAVLink", 8043, "L3_Physical"),
    NodeInfo("44", "NFC", 8044, "L3_Physical"),
    NodeInfo("45", "DesktopAuto", 8045, "L3_Physical"),
    NodeInfo("46", "Camera", 8046, "L3_Physical"),
    NodeInfo("47", "Audio", 8047, "L3_Physical"),
    NodeInfo("48", "Serial", 8048, "L3_Physical"),
    NodeInfo("49", "OctoPrint", 8049, "L3_Physical"),
]

# 核心节点（需要实际启动测试）
CORE_NODES = ["00", "50", "58", "33", "68"]

class NodeTester:
    """节点测试器"""
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.results: Dict[str, Tuple[bool, str]] = {}
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def get_node_dir(self, node_id: str) -> str:
        """获取节点目录"""
        nodes_dir = os.path.join(self.base_dir, "nodes")
        for d in os.listdir(nodes_dir):
            if d.startswith(f"Node_{node_id}_"):
                return os.path.join(nodes_dir, d)
        return ""
    
    def check_node_files(self, node: NodeInfo) -> Tuple[bool, str]:
        """检查节点文件完整性"""
        node_dir = self.get_node_dir(node.id)
        if not node_dir or not os.path.exists(node_dir):
            return False, f"目录不存在"
        
        main_py = os.path.join(node_dir, "main.py")
        if not os.path.exists(main_py):
            return False, f"main.py 不存在"
        
        dockerfile = os.path.join(node_dir, "Dockerfile")
        if not os.path.exists(dockerfile):
            return False, f"Dockerfile 不存在"
        
        # 检查 main.py 语法
        try:
            with open(main_py, 'r') as f:
                code = f.read()
            compile(code, main_py, 'exec')
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        
        return True, "文件完整"
    
    async def start_node(self, node_id: str, port: int) -> bool:
        """启动节点"""
        node_dir = self.get_node_dir(node_id)
        if not node_dir:
            return False
        
        main_py = os.path.join(node_dir, "main.py")
        env = os.environ.copy()
        env["USE_MOCK_DRIVERS"] = "true"
        env["REDIS_URL"] = ""  # 使用内存模式
        
        try:
            process = subprocess.Popen(
                [sys.executable, main_py],
                cwd=node_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.processes[node_id] = process
            
            # 等待启动
            await asyncio.sleep(1.5)
            
            # 检查是否存活
            if process.poll() is not None:
                return False
            
            return True
        except Exception as e:
            print(f"启动 Node {node_id} 失败: {e}")
            return False
    
    async def check_health(self, port: int) -> Tuple[bool, dict]:
        """检查节点健康状态"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
                if resp.status_code == 200:
                    return True, resp.json()
                return False, {"error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return False, {"error": str(e)}
    
    def stop_all(self):
        """停止所有节点"""
        for node_id, process in self.processes.items():
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                process.kill()
        self.processes.clear()

async def run_tests():
    """运行完整测试"""
    print("╔" + "═" * 60 + "╗")
    print("║" + " UFO Galaxy 70-Node Complete Test Suite ".center(60) + "║")
    print("╚" + "═" * 60 + "╝")
    print()
    
    tester = NodeTester()
    
    # 统计
    total = len(ALL_NODES)
    passed = 0
    failed = 0
    
    # 按层级分组
    layers = {
        "L0_Kernel": [],
        "L1_Gateway": [],
        "L2_Tools": [],
        "L3_Physical": []
    }
    
    for node in ALL_NODES:
        layers[node.layer].append(node)
    
    # ==========================================
    # 测试 1: 文件完整性检查
    # ==========================================
    print("=" * 62)
    print("📁 Test 1: File Integrity Check (所有 70 节点)")
    print("=" * 62)
    
    file_passed = 0
    file_failed = 0
    
    for layer_name, nodes in layers.items():
        print(f"\n  [{layer_name}] ({len(nodes)} nodes)")
        for node in nodes:
            success, msg = tester.check_node_files(node)
            if success:
                print(f"    ✅ Node {node.id} ({node.name}): {msg}")
                file_passed += 1
            else:
                print(f"    ❌ Node {node.id} ({node.name}): {msg}")
                file_failed += 1
    
    print(f"\n  📊 文件检查结果: {file_passed}/{total} 通过")
    
    # ==========================================
    # 测试 2: 核心节点启动测试
    # ==========================================
    print("\n" + "=" * 62)
    print("🚀 Test 2: Core Node Startup Test (核心节点)")
    print("=" * 62)
    
    core_nodes_info = [n for n in ALL_NODES if n.id in CORE_NODES]
    
    print("\n  启动核心节点...")
    startup_results = []
    
    for node in core_nodes_info:
        success = await tester.start_node(node.id, node.port)
        if success:
            print(f"    ✅ Node {node.id} ({node.name}) 启动成功")
            startup_results.append((node, True))
        else:
            print(f"    ❌ Node {node.id} ({node.name}) 启动失败")
            startup_results.append((node, False))
    
    # ==========================================
    # 测试 3: 健康检查
    # ==========================================
    print("\n" + "=" * 62)
    print("💓 Test 3: Health Check (核心节点)")
    print("=" * 62)
    
    await asyncio.sleep(1)  # 等待节点完全启动
    
    health_passed = 0
    for node, started in startup_results:
        if started:
            success, data = await tester.check_health(node.port)
            if success:
                status = data.get("status", "unknown")
                print(f"    ✅ Node {node.id} ({node.name}): {status}")
                health_passed += 1
            else:
                print(f"    ❌ Node {node.id} ({node.name}): {data.get('error', 'unknown')}")
        else:
            print(f"    ⏭️  Node {node.id} ({node.name}): 跳过 (未启动)")
    
    # ==========================================
    # 测试 4: 功能测试
    # ==========================================
    print("\n" + "=" * 62)
    print("🧪 Test 4: Functional Tests")
    print("=" * 62)
    
    import httpx
    func_passed = 0
    func_total = 0
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 4.1 状态机测试
        func_total += 1
        print("\n  4.1 State Machine Lock Test")
        try:
            resp = await client.post("http://localhost:8000/lock/acquire", json={
                "resource": "test_resource",
                "holder": "test_holder"
            })
            if resp.status_code == 200 and resp.json().get("success"):
                print("      ✅ 锁获取成功")
                func_passed += 1
                # 释放锁
                await client.post("http://localhost:8000/lock/release", json={
                    "resource": "test_resource",
                    "holder": "test_holder"
                })
            else:
                print("      ❌ 锁获取失败")
        except Exception as e:
            print(f"      ❌ 错误: {e}")
        
        # 4.2 模型路由测试
        func_total += 1
        print("\n  4.2 Model Router Test")
        try:
            resp = await client.post("http://localhost:8058/route", json={
                "prompt": "Hello world",
                "session_id": "test"
            })
            if resp.status_code == 200:
                data = resp.json()
                model = data.get("selected_model", "unknown")
                print(f"      ✅ 路由成功: {model}")
                func_passed += 1
            else:
                print("      ❌ 路由失败")
        except Exception as e:
            print(f"      ❌ 错误: {e}")
        
        # 4.3 硬件仲裁测试
        func_total += 1
        print("\n  4.3 Hardware Arbitration Test")
        try:
            resp = await client.post("http://localhost:8050/execute", json={
                "target": "adb",
                "command": "shell",
                "args": ["echo", "test"]
            })
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") or "execution_path" in data:
                    print("      ✅ 硬件请求处理成功")
                    func_passed += 1
                else:
                    print("      ❌ 硬件请求处理失败")
            else:
                print("      ❌ HTTP 错误")
        except Exception as e:
            print(f"      ❌ 错误: {e}")
        
        # 4.4 ADB 模拟测试
        func_total += 1
        print("\n  4.4 ADB Mock Test")
        try:
            resp = await client.get("http://localhost:8033/health")
            if resp.status_code == 200:
                print("      ✅ ADB 节点响应正常")
                func_passed += 1
            else:
                print("      ❌ ADB 节点无响应")
        except Exception as e:
            print(f"      ❌ 错误: {e}")
    
    # ==========================================
    # 清理
    # ==========================================
    print("\n" + "=" * 62)
    print("🛑 Stopping nodes...")
    tester.stop_all()
    
    # ==========================================
    # 汇总报告
    # ==========================================
    print("\n" + "=" * 62)
    print("📊 FINAL REPORT")
    print("=" * 62)
    
    print(f"""
  ┌─────────────────────────────────────────┐
  │  UFO Galaxy 70-Node Test Results        │
  ├─────────────────────────────────────────┤
  │  Total Nodes:        {total:>3}                │
  │  File Check Passed:  {file_passed:>3} / {total:<3}           │
  │  Core Startup:       {sum(1 for _, s in startup_results if s):>3} / {len(CORE_NODES):<3}           │
  │  Health Check:       {health_passed:>3} / {len(CORE_NODES):<3}           │
  │  Functional Tests:   {func_passed:>3} / {func_total:<3}           │
  ├─────────────────────────────────────────┤
  │  Layer Distribution:                    │
  │    L0 Kernel:   {len(layers['L0_Kernel']):>2} nodes              │
  │    L1 Gateway:  {len(layers['L1_Gateway']):>2} nodes              │
  │    L2 Tools:    {len(layers['L2_Tools']):>2} nodes              │
  │    L3 Physical: {len(layers['L3_Physical']):>2} nodes              │
  └─────────────────────────────────────────┘
""")
    
    # 计算总体通过率
    total_tests = total + len(CORE_NODES) * 2 + func_total
    total_passed = file_passed + sum(1 for _, s in startup_results if s) + health_passed + func_passed
    pass_rate = (total_passed / total_tests) * 100
    
    if pass_rate >= 90:
        print(f"  🎉 Overall Pass Rate: {pass_rate:.1f}% - EXCELLENT!")
    elif pass_rate >= 70:
        print(f"  ✅ Overall Pass Rate: {pass_rate:.1f}% - GOOD")
    else:
        print(f"  ⚠️  Overall Pass Rate: {pass_rate:.1f}% - NEEDS ATTENTION")
    
    print("\n" + "=" * 62)
    print(f"  Test completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)
    
    return pass_rate >= 70

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
