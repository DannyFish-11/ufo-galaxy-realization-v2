"""
UFO Galaxy - 系统负载监控器
============================

真实的系统负载监控实现，替换简化版本

功能:
1. CPU 使用率监控
2. 内存使用率监控
3. 磁盘使用率监控
4. 网络流量监控
5. 进程监控
"""

import os
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 尝试导入 psutil，如果不可用则使用 /proc 文件系统
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not available, using /proc filesystem")


@dataclass
class CPUStats:
    """CPU 统计"""
    usage_percent: float = 0.0
    user_percent: float = 0.0
    system_percent: float = 0.0
    idle_percent: float = 0.0
    iowait_percent: float = 0.0
    core_count: int = 1
    per_core_usage: List[float] = field(default_factory=list)
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0
    load_avg_15m: float = 0.0


@dataclass
class MemoryStats:
    """内存统计"""
    total_bytes: int = 0
    available_bytes: int = 0
    used_bytes: int = 0
    usage_percent: float = 0.0
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0
    cached_bytes: int = 0
    buffers_bytes: int = 0


@dataclass
class DiskStats:
    """磁盘统计"""
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    usage_percent: float = 0.0
    read_bytes: int = 0
    write_bytes: int = 0
    read_count: int = 0
    write_count: int = 0


@dataclass
class NetworkStats:
    """网络统计"""
    bytes_sent: int = 0
    bytes_recv: int = 0
    packets_sent: int = 0
    packets_recv: int = 0
    errors_in: int = 0
    errors_out: int = 0
    drop_in: int = 0
    drop_out: int = 0
    connections_count: int = 0


@dataclass
class ProcessStats:
    """进程统计"""
    pid: int = 0
    name: str = ""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_rss: int = 0
    threads: int = 0
    status: str = ""


@dataclass
class SystemLoad:
    """系统负载综合信息"""
    timestamp: datetime = field(default_factory=datetime.now)
    cpu: CPUStats = field(default_factory=CPUStats)
    memory: MemoryStats = field(default_factory=MemoryStats)
    disk: DiskStats = field(default_factory=DiskStats)
    network: NetworkStats = field(default_factory=NetworkStats)
    top_processes: List[ProcessStats] = field(default_factory=list)
    
    def overall_load_score(self) -> float:
        """计算综合负载分数 (0-1)"""
        # 各指标权重
        cpu_weight = 0.35
        memory_weight = 0.30
        disk_weight = 0.15
        network_weight = 0.10
        iowait_weight = 0.10
        
        # 归一化各指标 (0-1)
        cpu_score = self.cpu.usage_percent / 100.0
        memory_score = self.memory.usage_percent / 100.0
        disk_score = self.disk.usage_percent / 100.0
        
        # 网络负载估算（基于连接数）
        network_score = min(self.network.connections_count / 1000.0, 1.0)
        
        # IO 等待
        iowait_score = self.cpu.iowait_percent / 100.0
        
        total_score = (
            cpu_score * cpu_weight +
            memory_score * memory_weight +
            disk_score * disk_weight +
            network_score * network_weight +
            iowait_score * iowait_weight
        )
        
        return round(total_score, 4)


class SystemLoadMonitor:
    """系统负载监控器"""
    
    def __init__(
        self,
        history_size: int = 100,
        sample_interval: float = 1.0
    ):
        self.history_size = history_size
        self.sample_interval = sample_interval
        
        # 历史记录
        self._cpu_history: deque = deque(maxlen=history_size)
        self._memory_history: deque = deque(maxlen=history_size)
        self._load_history: deque = deque(maxlen=history_size)
        
        # 上次采样数据（用于计算增量）
        self._last_cpu_times: Optional[Tuple] = None
        self._last_disk_io: Optional[Dict] = None
        self._last_net_io: Optional[Dict] = None
        self._last_sample_time: float = 0
        
        # 运行状态
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def get_cpu_stats(self) -> CPUStats:
        """获取 CPU 统计"""
        stats = CPUStats()
        
        if HAS_PSUTIL:
            # 使用 psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_times = psutil.cpu_times_percent(interval=0.1)
            load_avg = psutil.getloadavg()
            
            stats.usage_percent = cpu_percent
            stats.user_percent = cpu_times.user
            stats.system_percent = cpu_times.system
            stats.idle_percent = cpu_times.idle
            stats.iowait_percent = getattr(cpu_times, 'iowait', 0)
            stats.core_count = psutil.cpu_count()
            stats.per_core_usage = psutil.cpu_percent(percpu=True)
            stats.load_avg_1m = load_avg[0]
            stats.load_avg_5m = load_avg[1]
            stats.load_avg_15m = load_avg[2]
        else:
            # 使用 /proc 文件系统
            stats = self._get_cpu_from_proc()
        
        return stats
    
    def _get_cpu_from_proc(self) -> CPUStats:
        """从 /proc 获取 CPU 统计"""
        stats = CPUStats()
        
        try:
            # 读取 /proc/stat
            with open('/proc/stat', 'r') as f:
                line = f.readline()
                parts = line.split()
                
                if parts[0] == 'cpu':
                    user = int(parts[1])
                    nice = int(parts[2])
                    system = int(parts[3])
                    idle = int(parts[4])
                    iowait = int(parts[5]) if len(parts) > 5 else 0
                    
                    total = user + nice + system + idle + iowait
                    
                    if self._last_cpu_times:
                        last_user, last_nice, last_system, last_idle, last_iowait, last_total = self._last_cpu_times
                        
                        delta_total = total - last_total
                        if delta_total > 0:
                            stats.user_percent = ((user + nice) - (last_user + last_nice)) / delta_total * 100
                            stats.system_percent = (system - last_system) / delta_total * 100
                            stats.idle_percent = (idle - last_idle) / delta_total * 100
                            stats.iowait_percent = (iowait - last_iowait) / delta_total * 100
                            stats.usage_percent = 100 - stats.idle_percent
                    
                    self._last_cpu_times = (user, nice, system, idle, iowait, total)
            
            # 读取 /proc/loadavg
            with open('/proc/loadavg', 'r') as f:
                parts = f.readline().split()
                stats.load_avg_1m = float(parts[0])
                stats.load_avg_5m = float(parts[1])
                stats.load_avg_15m = float(parts[2])
            
            # 获取 CPU 核心数
            stats.core_count = os.cpu_count() or 1
            
        except Exception as e:
            logger.error(f"Error reading CPU stats from /proc: {e}")
        
        return stats
    
    def get_memory_stats(self) -> MemoryStats:
        """获取内存统计"""
        stats = MemoryStats()
        
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            stats.total_bytes = mem.total
            stats.available_bytes = mem.available
            stats.used_bytes = mem.used
            stats.usage_percent = mem.percent
            stats.cached_bytes = getattr(mem, 'cached', 0)
            stats.buffers_bytes = getattr(mem, 'buffers', 0)
            stats.swap_total = swap.total
            stats.swap_used = swap.used
            stats.swap_percent = swap.percent
        else:
            stats = self._get_memory_from_proc()
        
        return stats
    
    def _get_memory_from_proc(self) -> MemoryStats:
        """从 /proc 获取内存统计"""
        stats = MemoryStats()
        
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = {}
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip().split()[0]
                        meminfo[key] = int(value) * 1024  # KB to bytes
                
                stats.total_bytes = meminfo.get('MemTotal', 0)
                stats.available_bytes = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
                stats.used_bytes = stats.total_bytes - stats.available_bytes
                stats.usage_percent = (stats.used_bytes / stats.total_bytes * 100) if stats.total_bytes > 0 else 0
                stats.cached_bytes = meminfo.get('Cached', 0)
                stats.buffers_bytes = meminfo.get('Buffers', 0)
                stats.swap_total = meminfo.get('SwapTotal', 0)
                stats.swap_used = stats.swap_total - meminfo.get('SwapFree', 0)
                stats.swap_percent = (stats.swap_used / stats.swap_total * 100) if stats.swap_total > 0 else 0
        
        except Exception as e:
            logger.error(f"Error reading memory stats from /proc: {e}")
        
        return stats
    
    def get_disk_stats(self, path: str = '/') -> DiskStats:
        """获取磁盘统计"""
        stats = DiskStats()
        
        if HAS_PSUTIL:
            disk_usage = psutil.disk_usage(path)
            disk_io = psutil.disk_io_counters()
            
            stats.total_bytes = disk_usage.total
            stats.used_bytes = disk_usage.used
            stats.free_bytes = disk_usage.free
            stats.usage_percent = disk_usage.percent
            
            if disk_io:
                stats.read_bytes = disk_io.read_bytes
                stats.write_bytes = disk_io.write_bytes
                stats.read_count = disk_io.read_count
                stats.write_count = disk_io.write_count
        else:
            stats = self._get_disk_from_proc(path)
        
        return stats
    
    def _get_disk_from_proc(self, path: str = '/') -> DiskStats:
        """从 /proc 获取磁盘统计"""
        stats = DiskStats()
        
        try:
            # 使用 os.statvfs 获取磁盘使用情况
            st = os.statvfs(path)
            stats.total_bytes = st.f_blocks * st.f_frsize
            stats.free_bytes = st.f_bfree * st.f_frsize
            stats.used_bytes = stats.total_bytes - stats.free_bytes
            stats.usage_percent = (stats.used_bytes / stats.total_bytes * 100) if stats.total_bytes > 0 else 0
            
            # 读取 /proc/diskstats
            with open('/proc/diskstats', 'r') as f:
                total_read = 0
                total_write = 0
                for line in f:
                    parts = line.split()
                    if len(parts) >= 14:
                        # 第 6 列是读取扇区数，第 10 列是写入扇区数
                        total_read += int(parts[5]) * 512
                        total_write += int(parts[9]) * 512
                
                stats.read_bytes = total_read
                stats.write_bytes = total_write
        
        except Exception as e:
            logger.error(f"Error reading disk stats: {e}")
        
        return stats
    
    def get_network_stats(self) -> NetworkStats:
        """获取网络统计"""
        stats = NetworkStats()
        
        if HAS_PSUTIL:
            net_io = psutil.net_io_counters()
            connections = psutil.net_connections()
            
            stats.bytes_sent = net_io.bytes_sent
            stats.bytes_recv = net_io.bytes_recv
            stats.packets_sent = net_io.packets_sent
            stats.packets_recv = net_io.packets_recv
            stats.errors_in = net_io.errin
            stats.errors_out = net_io.errout
            stats.drop_in = net_io.dropin
            stats.drop_out = net_io.dropout
            stats.connections_count = len(connections)
        else:
            stats = self._get_network_from_proc()
        
        return stats
    
    def _get_network_from_proc(self) -> NetworkStats:
        """从 /proc 获取网络统计"""
        stats = NetworkStats()
        
        try:
            with open('/proc/net/dev', 'r') as f:
                lines = f.readlines()[2:]  # 跳过标题行
                
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 17:
                        # 累加所有接口的统计
                        stats.bytes_recv += int(parts[1])
                        stats.packets_recv += int(parts[2])
                        stats.errors_in += int(parts[3])
                        stats.drop_in += int(parts[4])
                        stats.bytes_sent += int(parts[9])
                        stats.packets_sent += int(parts[10])
                        stats.errors_out += int(parts[11])
                        stats.drop_out += int(parts[12])
            
            # 统计连接数
            with open('/proc/net/tcp', 'r') as f:
                stats.connections_count = len(f.readlines()) - 1
            with open('/proc/net/tcp6', 'r') as f:
                stats.connections_count += len(f.readlines()) - 1
        
        except Exception as e:
            logger.error(f"Error reading network stats from /proc: {e}")
        
        return stats
    
    def get_top_processes(self, n: int = 5) -> List[ProcessStats]:
        """获取 CPU 使用率最高的进程"""
        processes = []
        
        if HAS_PSUTIL:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info', 'num_threads', 'status']):
                try:
                    info = proc.info
                    processes.append(ProcessStats(
                        pid=info['pid'],
                        name=info['name'],
                        cpu_percent=info['cpu_percent'] or 0,
                        memory_percent=info['memory_percent'] or 0,
                        memory_rss=info['memory_info'].rss if info['memory_info'] else 0,
                        threads=info['num_threads'] or 0,
                        status=info['status'] or ''
                    ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            # 按 CPU 使用率排序
            processes.sort(key=lambda p: p.cpu_percent, reverse=True)
        
        return processes[:n]
    
    def get_system_load(self) -> SystemLoad:
        """获取完整的系统负载信息"""
        load = SystemLoad(
            timestamp=datetime.now(),
            cpu=self.get_cpu_stats(),
            memory=self.get_memory_stats(),
            disk=self.get_disk_stats(),
            network=self.get_network_stats(),
            top_processes=self.get_top_processes()
        )
        
        # 保存到历史
        self._load_history.append(load)
        
        return load
    
    def get_load_score(self) -> float:
        """获取当前负载分数 (0-1)"""
        load = self.get_system_load()
        return load.overall_load_score()
    
    def get_average_load(self, samples: int = 10) -> float:
        """获取平均负载分数"""
        if not self._load_history:
            return self.get_load_score()
        
        recent = list(self._load_history)[-samples:]
        return sum(l.overall_load_score() for l in recent) / len(recent)
    
    async def start_monitoring(self):
        """启动监控"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("System load monitoring started")
    
    async def stop_monitoring(self):
        """停止监控"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("System load monitoring stopped")
    
    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                self.get_system_load()
                await asyncio.sleep(self.sample_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(self.sample_interval)
    
    def export_stats(self) -> Dict[str, Any]:
        """导出统计信息"""
        load = self.get_system_load()
        return {
            'timestamp': load.timestamp.isoformat(),
            'overall_load_score': load.overall_load_score(),
            'cpu': {
                'usage_percent': load.cpu.usage_percent,
                'load_avg_1m': load.cpu.load_avg_1m,
                'core_count': load.cpu.core_count
            },
            'memory': {
                'usage_percent': load.memory.usage_percent,
                'total_gb': load.memory.total_bytes / (1024**3),
                'used_gb': load.memory.used_bytes / (1024**3)
            },
            'disk': {
                'usage_percent': load.disk.usage_percent,
                'total_gb': load.disk.total_bytes / (1024**3),
                'free_gb': load.disk.free_bytes / (1024**3)
            },
            'network': {
                'connections': load.network.connections_count,
                'bytes_sent': load.network.bytes_sent,
                'bytes_recv': load.network.bytes_recv
            }
        }


# 全局实例
_monitor: Optional[SystemLoadMonitor] = None


def get_monitor() -> SystemLoadMonitor:
    """获取全局监控器实例"""
    global _monitor
    if _monitor is None:
        _monitor = SystemLoadMonitor()
    return _monitor


def get_load() -> float:
    """获取当前负载分数（便捷函数）"""
    return get_monitor().get_load_score()


# 测试代码
async def test_system_load_monitor():
    """测试系统负载监控器"""
    print("=== 测试系统负载监控器 ===")
    print(f"psutil available: {HAS_PSUTIL}")
    
    monitor = SystemLoadMonitor()
    
    # 获取各项统计
    print("\n--- CPU Stats ---")
    cpu = monitor.get_cpu_stats()
    print(f"Usage: {cpu.usage_percent:.1f}%")
    print(f"Load Avg: {cpu.load_avg_1m:.2f}, {cpu.load_avg_5m:.2f}, {cpu.load_avg_15m:.2f}")
    print(f"Cores: {cpu.core_count}")
    
    print("\n--- Memory Stats ---")
    mem = monitor.get_memory_stats()
    print(f"Usage: {mem.usage_percent:.1f}%")
    print(f"Total: {mem.total_bytes / (1024**3):.2f} GB")
    print(f"Used: {mem.used_bytes / (1024**3):.2f} GB")
    
    print("\n--- Disk Stats ---")
    disk = monitor.get_disk_stats()
    print(f"Usage: {disk.usage_percent:.1f}%")
    print(f"Total: {disk.total_bytes / (1024**3):.2f} GB")
    print(f"Free: {disk.free_bytes / (1024**3):.2f} GB")
    
    print("\n--- Network Stats ---")
    net = monitor.get_network_stats()
    print(f"Connections: {net.connections_count}")
    print(f"Bytes Sent: {net.bytes_sent / (1024**2):.2f} MB")
    print(f"Bytes Recv: {net.bytes_recv / (1024**2):.2f} MB")
    
    print("\n--- Overall Load ---")
    load = monitor.get_system_load()
    print(f"Load Score: {load.overall_load_score():.4f}")
    
    print("\n--- Export Stats ---")
    import json
    print(json.dumps(monitor.export_stats(), indent=2))
    
    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(test_system_load_monitor())
