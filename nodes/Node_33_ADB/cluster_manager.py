"""
Node 33: ADB 集群管理器
支持多设备自动发现、并行任务分发和状态同步。
"""
import asyncio
import logging
from typing import List, Dict, Any

class ADBClusterManager:
    def __init__(self):
        self.devices = {}
        self.logger = logging.getLogger("ADBCluster")

    async def discover_devices(self) -> List[str]:
        """发现所有连接的 ADB 设备"""
        process = await asyncio.create_subprocess_exec(
            'adb', 'devices',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        lines = stdout.decode().splitlines()
        new_devices = []
        for line in lines[1:]:
            if line.strip() and "device" in line:
                serial = line.split()[0]
                new_devices.append(serial)
        return new_devices

    async def parallel_execute(self, command: str, serials: List[str]) -> Dict[str, Any]:
        """在多个设备上并行执行命令"""
        tasks = []
        for serial in serials:
            tasks.append(self._run_cmd(serial, command))
        
        results = await asyncio.gather(*tasks)
        return dict(zip(serials, results))

    async def _run_cmd(self, serial: str, command: str) -> str:
        cmd = ["adb", "-s", serial, "shell", command]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode().strip() if not stderr else f"Error: {stderr.decode()}"

# 实例化
cluster_manager = ADBClusterManager()
