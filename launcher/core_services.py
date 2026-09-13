"""
launcher/core_services.py — Core service startup.

Responsibilities:
- CoreServiceLauncher: start Device Agent Manager, Device Status API,
  and Microsoft UFO integration.
"""

import asyncio
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
        改成直接给结论。

        为什么改成并发(所有者:"整体的速度和节奏有点奇怪")
        ------------------------------------------------
        上一版这段的注释写着"这三个都是秒级的"。实测把这句话推翻了 ——
        ``logs/lumiv.log`` 里 ``[PHASE-TIMING] 核心服务`` 冷启是 **10.22s**、
        热启是 **0.09s**,而那 10 秒里有 9 秒卡在 ``microsoft_ufo_integration``
        那一条:它降级时要 ``import pyautogui``,首次触碰这条依赖链(Pillow /
        Xlib / pyscreeze)是冷盘 I/O,Windows 上还要过一遍杀软。

        三条彼此独立,却一个等一个 —— 于是最慢那条把另外两条也拖住了。
        改成 ``gather`` 之后耗时从"求和"变成"取最大"。

        注意这里**不是**把注释改成"这三个可能很慢"就算完:那样只是把假话换成
        真话,时间照样浪费。判据在
        ``tests/test_startup_rhythm.py::TestCoreServicesDoNotQueueUp``。
        """
        results: Dict[str, str] = {}

        starters = [("device_agent_manager", self.start_device_agent_manager())]
        if self.config.enable_device_api:
            starters.append(("device_status_api", self.start_device_status_api()))
        starters.append(("microsoft_ufo_integration", self.start_microsoft_ufo_integration()))

        outcomes = await asyncio.gather(*(coro for _key, coro in starters), return_exceptions=True)
        for (key, _coro), outcome in zip(starters, outcomes):
            if isinstance(outcome, BaseException):
                # 一条炸了不许把另外两条的结论也带走 —— 照实记成 failed 并留痕。
                logger.warning("核心服务 %s 启动时抛了异常(非致命,记为 failed): %s", key, outcome)
                results[key] = "failed"
                continue
            results[key] = self._recorded_status(key, bool(outcome))

        for key, status in results.items():
            label = self.SERVICE_LABELS.get(key, key)
            if status == "running":
                print_status(f"{label} 就绪", "success")
            elif status == "failed":
                print_status(f"{label} 未起来", "error")
            else:
                print_status(f"{label} 部分可用({status})", "warning")

        return results
