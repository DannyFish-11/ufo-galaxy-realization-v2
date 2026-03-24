"""
launcher/service_manager.py — Service lifecycle management.

Responsibilities:
- ServiceInfo dataclass: per-service runtime metadata
- ServiceManager: register, start, stop, and status-report all running services
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from .bootstrap import PROJECT_ROOT, SystemState, ServiceType, SystemConfig

logger = logging.getLogger("Galaxy")


@dataclass
class ServiceInfo:
    """服务信息"""
    name: str
    service_type: ServiceType
    status: str = "stopped"
    port: Optional[int] = None
    process: Optional[subprocess.Popen] = None
    start_time: Optional[datetime] = None
    error: Optional[str] = None


class ServiceManager:
    """服务管理器 - 统一管理所有服务"""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config
        self.services: Dict[str, ServiceInfo] = {}
        self.state = SystemState.INITIALIZING

    def register_service(
        self,
        name: str,
        service_type: ServiceType,
        port: Optional[int] = None,
    ) -> None:
        """注册服务"""
        self.services[name] = ServiceInfo(
            name=name,
            service_type=service_type,
            port=port,
        )

    async def start_service(
        self,
        name: str,
        command: List[str],
        cwd: Optional[Path] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> bool:
        """启动服务"""
        if name not in self.services:
            logger.error("服务未注册: %s", name)
            return False

        service = self.services[name]

        try:
            env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
            if extra_env:
                env.update(extra_env)
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd else str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            service.process = process
            service.status = "running"
            service.start_time = datetime.now()
            service.error = None

            logger.info("服务已启动: %s", name)
            return True

        except Exception as e:
            service.status = "error"
            service.error = str(e)
            logger.error("启动服务失败 %s: %s", name, e)
            return False

    def stop_service(self, name: str) -> bool:
        """停止服务"""
        if name not in self.services:
            return False

        service = self.services[name]

        if service.process:
            try:
                service.process.terminate()
                service.process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                service.process.kill()
            service.process = None

        service.status = "stopped"
        return True

    def stop_all(self) -> None:
        """停止所有服务"""
        for name in list(self.services.keys()):
            self.stop_service(name)

    def get_status(self) -> Dict[str, Any]:
        """获取所有服务状态"""
        return {
            name: {
                "type": service.service_type.value,
                "status": service.status,
                "port": service.port,
                "uptime": (
                    (datetime.now() - service.start_time).total_seconds()
                    if service.start_time
                    else 0
                ),
                "error": service.error,
            }
            for name, service in self.services.items()
        }
