"""
UFO³ Galaxy - 智能节点启动器
=============================

根据依赖关系智能启动节点，支持故障恢复和自动重启

作者：Manus AI
日期：2026-01-23
"""

import json
import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict

# ANSI 颜色代码
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

class SmartLauncher:
    def __init__(self, config_file: str = "node_dependencies.json"):
        self.config_file = config_file
        self.config = self._load_config()
        self.processes = {}  # node_name -> subprocess.Popen
        self.startup_times = {}  # node_name -> timestamp
        self.retry_counts = defaultdict(int)  # node_name -> retry_count
        self.max_retries = 3
        
    def _load_config(self) -> Dict:
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            print(f"{RED}错误: 配置文件 {self.config_file} 不存在{RESET}")
            sys.exit(1)
        
        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _get_startup_order(self, group: str = None) -> List[str]:
        """
        根据依赖关系和优先级计算启动顺序
        使用拓扑排序
        """
        nodes = self.config["nodes"]
        
        # 过滤节点
        if group:
            filtered_nodes = {
                name: info for name, info in nodes.items()
                if info["group"] == group
            }
        else:
            filtered_nodes = nodes
        
        # 构建依赖图
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        
        for node_name, node_info in filtered_nodes.items():
            in_degree[node_name] = 0
        
        for node_name, node_info in filtered_nodes.items():
            for dep in node_info["dependencies"]:
                if dep in filtered_nodes:
                    graph[dep].append(node_name)
                    in_degree[node_name] += 1
        
        # 拓扑排序
        queue = []
        for node_name in filtered_nodes:
            if in_degree[node_name] == 0:
                priority = filtered_nodes[node_name]["priority"]
                queue.append((priority, node_name))
        
        queue.sort()  # 按优先级排序
        
        result = []
        while queue:
            _, node_name = queue.pop(0)
            result.append(node_name)
            
            for neighbor in graph[node_name]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    priority = filtered_nodes[neighbor]["priority"]
                    queue.append((priority, neighbor))
                    queue.sort()
        
        # 检查循环依赖
        if len(result) != len(filtered_nodes):
            print(f"{RED}错误: 检测到循环依赖{RESET}")
            sys.exit(1)
        
        return result
    
    def _start_node(self, node_name: str) -> bool:
        """启动单个节点"""
        node_info = self.config["nodes"][node_name]
        node_path = Path("nodes") / node_name / "main.py"
        
        if not node_path.exists():
            print(f"{YELLOW}警告: {node_name} 的 main.py 不存在，跳过{RESET}")
            return False
        
        try:
            # 启动节点
            process = subprocess.Popen(
                [sys.executable, str(node_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
            self.processes[node_name] = process
            self.startup_times[node_name] = time.time()
            
            print(f"{GREEN}✓{RESET} {node_name} (端口 {node_info['port']}) - {node_info['description']}")
            return True
            
        except Exception as e:
            print(f"{RED}✗{RESET} {node_name} 启动失败: {e}")
            return False
    
    def _check_node_health(self, node_name: str) -> bool:
        """检查节点是否健康运行"""
        if node_name not in self.processes:
            return False
        
        process = self.processes[node_name]
        
        # 检查进程是否还在运行
        if process.poll() is not None:
            return False
        
        # TODO: 可以添加 HTTP 健康检查
        return True
    
    def start_group(self, group: str):
        """启动指定分组的所有节点"""
        if group not in self.config["groups"]:
            print(f"{RED}错误: 分组 {group} 不存在{RESET}")
            return
        
        group_info = self.config["groups"][group]
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}启动 {group_info['name']}{RESET}")
        print(f"{BLUE}{group_info['description']}{RESET}")
        print(f"{BLUE}{'='*80}{RESET}\n")
        
        startup_order = self._get_startup_order(group)
        startup_delay = group_info["startup_delay"]
        
        for node_name in startup_order:
            node_info = self.config["nodes"][node_name]
            
            # 检查依赖是否已启动
            for dep in node_info["dependencies"]:
                if dep not in self.processes or not self._check_node_health(dep):
                    print(f"{YELLOW}警告: {node_name} 的依赖 {dep} 未运行，跳过{RESET}")
                    continue
            
            # 启动节点
            self._start_node(node_name)
            
            # 等待节点启动
            time.sleep(startup_delay)
    
    def start_all(self):
        """启动所有节点"""
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}启动完整系统{RESET}")
        print(f"{BLUE}{'='*80}{RESET}\n")
        
        # 按分组顺序启动
        group_order = ["core", "academic", "development", "extended"]
        
        for group in group_order:
            if group in self.config["groups"]:
                self.start_group(group)
                print()
    
    def stop_all(self):
        """停止所有节点"""
        print(f"\n{YELLOW}正在停止所有节点...{RESET}\n")
        
        for node_name, process in self.processes.items():
            try:
                if os.name == 'nt':
                    # Windows
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    # Unix/Linux
                    process.terminate()
                
                print(f"{GREEN}✓{RESET} 已停止 {node_name}")
            except Exception as e:
                print(f"{RED}✗{RESET} 停止 {node_name} 失败: {e}")
        
        # 等待所有进程结束
        for process in self.processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        self.processes.clear()
        print(f"\n{GREEN}所有节点已停止{RESET}")
    
    def monitor(self):
        """监控所有节点，自动重启失败的节点"""
        print(f"\n{CYAN}开始监控节点...{RESET}")
        print(f"{CYAN}按 Ctrl+C 停止监控{RESET}\n")
        
        try:
            while True:
                time.sleep(10)  # 每 10 秒检查一次
                
                for node_name in list(self.processes.keys()):
                    if not self._check_node_health(node_name):
                        print(f"{RED}✗{RESET} {node_name} 已停止运行")
                        
                        # 检查重试次数
                        if self.retry_counts[node_name] < self.max_retries:
                            print(f"{YELLOW}尝试重启 {node_name} (第 {self.retry_counts[node_name] + 1} 次)...{RESET}")
                            
                            # 移除旧进程
                            del self.processes[node_name]
                            
                            # 重启节点
                            if self._start_node(node_name):
                                self.retry_counts[node_name] += 1
                            else:
                                print(f"{RED}重启 {node_name} 失败{RESET}")
                        else:
                            print(f"{RED}{node_name} 已达到最大重试次数，放弃重启{RESET}")
        
        except KeyboardInterrupt:
            print(f"\n{YELLOW}监控已停止{RESET}")
    
    def status(self):
        """显示所有节点的状态"""
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}节点状态{RESET}")
        print(f"{BLUE}{'='*80}{RESET}\n")
        
        for node_name, node_info in self.config["nodes"].items():
            if node_name in self.processes:
                if self._check_node_health(node_name):
                    status = f"{GREEN}✓ 运行中{RESET}"
                    uptime = int(time.time() - self.startup_times[node_name])
                    status += f" (运行时间: {uptime}s)"
                else:
                    status = f"{RED}✗ 已停止{RESET}"
            else:
                status = f"{YELLOW}○ 未启动{RESET}"
            
            print(f"{node_name:35} {status}")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print(f"""
{BLUE}UFO³ Galaxy - 智能节点启动器{RESET}

用法:
  python smart_launcher.py <命令> [选项]

命令:
  start <group>   启动指定分组的节点
                  可选分组: core, academic, development, extended, all
  
  stop            停止所有节点
  
  status          显示所有节点的状态
  
  monitor         监控所有节点，自动重启失败的节点

示例:
  python smart_launcher.py start core
  python smart_launcher.py start all
  python smart_launcher.py status
  python smart_launcher.py monitor
        """)
        sys.exit(0)
    
    command = sys.argv[1]
    launcher = SmartLauncher()
    
    if command == "start":
        if len(sys.argv) < 3:
            print(f"{RED}错误: 请指定要启动的分组{RESET}")
            print(f"可选分组: core, academic, development, extended, all")
            sys.exit(1)
        
        group = sys.argv[2]
        
        if group == "all":
            launcher.start_all()
        else:
            launcher.start_group(group)
        
        print(f"\n{GREEN}{'='*80}{RESET}")
        print(f"{GREEN}启动完成！{RESET}")
        print(f"{GREEN}{'='*80}{RESET}\n")
        print(f"查看状态: python smart_launcher.py status")
        print(f"启动监控: python smart_launcher.py monitor")
        print(f"停止所有节点: python smart_launcher.py stop")
        print()
        
        # 保持运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            launcher.stop_all()
    
    elif command == "stop":
        launcher.stop_all()
    
    elif command == "status":
        launcher.status()
    
    elif command == "monitor":
        launcher.start_all()
        launcher.monitor()
        launcher.stop_all()
    
    else:
        print(f"{RED}错误: 未知命令 {command}{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()
