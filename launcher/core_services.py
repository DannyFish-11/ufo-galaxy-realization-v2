"""
launcher/core_services.py — Core service startup.

Responsibilities:
- CoreServiceLauncher: start Device Agent Manager, Device Status API,
  and Microsoft UFO integration.
"""

import logging
import sys
from typing import Dict

from .bootstrap import ServiceType, SystemConfig, print_status
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
                sys.executable,
                "-m",
                "uvicorn",
                "core.device_status_api:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.config.device_api_port),
                "--log-level",
                "warning",
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

    #: 三个核心服务的显示名。名字只此一处,调用方不另抄。
    SERVICE_LABELS = {
        "device_agent_manager": "Device Agent 管理器",
        "device_status_api": "设备状态 API",
        "microsoft_ufo_integration": "Microsoft UFO 集成",
    }

    def _recorded_status(self, key: str, started: bool) -> str:
        """这个服务**实际**是什么状态。

        不能只看 ``start_*`` 的返回值:``start_microsoft_ufo_integration`` 在
        "部分可用"时也返回 ``True``(它确实不算失败),于是调用方数出来是
        「3/3 就绪」—— 而日志里同时写着「微软 UFO 集成部分可用」。同一件事两处
        各说各的,屏幕上那句还是更好听的那个。

        真状态在 ``service_manager`` 里记着(``running`` / ``partial``),这里取它。
        """
        if not started:
            return "failed"
        svc = self.service_manager.services.get(key)
        return str(getattr(svc, "status", "") or "running")

    async def start_all(self) -> Dict[str, str]:
        """启动所有核心服务，**每一个都给出结果**。

        返回 ``{服务名: "running" / "partial" / "failed"}``。

        此前这里是三行 ``print_status("启动 X...", "step")`` **只报开始、不报结果** ——
        真跑实测,屏幕上就是三行 `▶ 启动 …` 挂在那儿,成没成一个字都没有。
        这三个都是秒级的,所以不需要"开始"那一行:直接给结论。
        """
        results: Dict[str, str] = {}

        started = await self.start_device_agent_manager()
        results["device_agent_manager"] = self._recorded_status("device_agent_manager", started)

        if self.config.enable_device_api:
            started = await self.start_device_status_api()
            results["device_status_api"] = self._recorded_status("device_status_api", started)

        started = await self.start_microsoft_ufo_integration()
        results["microsoft_ufo_integration"] = self._recorded_status("microsoft_ufo_integration", started)

        for key, status in results.items():
            label = self.SERVICE_LABELS.get(key, key)
            if status == "running":
                print_status(f"{label} 就绪", "success")
            elif status == "failed":
                print_status(f"{label} 未起来", "error")
            else:
                print_status(f"{label} 部分可用({status})", "warning")

        return results
