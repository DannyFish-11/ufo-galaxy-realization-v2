"""
launcher/core_services.py — Core service startup.

Responsibilities:
- CoreServiceLauncher: start Device Agent Manager, Device Status API,
  and Microsoft UFO integration.
"""

import sys
import logging
from typing import Dict

from .bootstrap import print_status, ServiceType, SystemConfig
from .service_manager import ServiceManager

logger = logging.getLogger("Galaxy")


class CoreServiceLauncher:
    """核心服务启动器"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig) -> None:
        self.service_manager = service_manager
        self.config = config

    async def start_device_agent_manager(self) -> bool:
        """启动 Device Agent 管理器"""
        self.service_manager.register_service("device_agent_manager", ServiceType.CORE)

        try:
            from core.device_agent_manager import DeviceAgentManager
            manager = DeviceAgentManager()
            await manager.initialize()
            logger.info("Device Agent 管理器已初始化")
            self.service_manager.services["device_agent_manager"].status = "running"
            return True
        except Exception as e:
            logger.error("Device Agent 管理器启动失败: %s", e)
            return False

    async def start_device_status_api(self) -> bool:
        """启动设备状态 API"""
        self.service_manager.register_service(
            "device_status_api",
            ServiceType.API,
            port=self.config.device_api_port,
        )

        return await self.service_manager.start_service(
            "device_status_api",
            [
                sys.executable, "-m", "uvicorn", "core.device_status_api:app",
                "--host", "0.0.0.0",
                "--port", str(self.config.device_api_port),
                "--log-level", "warning",
            ],
        )

    async def start_microsoft_ufo_integration(self) -> bool:
        """启动微软 UFO 集成"""
        self.service_manager.register_service("microsoft_ufo_integration", ServiceType.CORE)

        try:
            from core.microsoft_ufo_integration import GalaxyIntegrationService
            integration = GalaxyIntegrationService()
            result = await integration.initialize()
            result = {
                "success": result,
                "message": "Galaxy Integration initialized" if result else "Galaxy Integration failed",
            }

            if result.get("success"):
                logger.info("微软 UFO 集成已初始化")
                self.service_manager.services["microsoft_ufo_integration"].status = "running"
                return True
            else:
                logger.warning("微软 UFO 集成部分可用: %s", result.get("message"))
                self.service_manager.services["microsoft_ufo_integration"].status = "partial"
                return True
        except Exception as e:
            logger.error("微软 UFO 集成启动失败: %s", e)
            return False

    async def start_all(self) -> Dict[str, bool]:
        """启动所有核心服务"""
        results: Dict[str, bool] = {}

        print_status("启动 Device Agent 管理器...", "step")
        results["device_agent_manager"] = await self.start_device_agent_manager()

        if self.config.enable_device_api:
            print_status("启动设备状态 API...", "step")
            results["device_status_api"] = await self.start_device_status_api()

        print_status("启动微软 UFO 集成...", "step")
        results["microsoft_ufo_integration"] = await self.start_microsoft_ufo_integration()

        return results
