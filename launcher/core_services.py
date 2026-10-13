"""
launcher/core_services.py — Core service startup.

Responsibilities:
- CoreServiceLauncher: start Device Agent Manager, Device Status API,
  and desktop automation (System API / UIA incl. Microsoft UFO / GUI).
"""

import asyncio
import logging
import sys
from typing import Any, Dict, List, Tuple

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
        """启动桌面自动化(含微软 UFO):说清这台机器上系统接口 / 控件 / 坐标各能用什么(core.desktop_automation)。

        服务键名沿用旧的 ``microsoft_ufo_integration``(别处按它取状态);显示名见 ``SERVICE_LABELS``。
        """
        self.service_manager.register_service("microsoft_ufo_integration", ServiceType.CORE)

        try:
            from core.desktop_automation import summary_line
            from core.microsoft_ufo_integration import GalaxyIntegrationService

            await GalaxyIntegrationService().initialize()
            # 探测要载 comtypes / 建 UIA 管理器:放到旁边线程,不占事件循环
            state, line = await asyncio.to_thread(summary_line)
            if state == "partial":
                logger.warning("桌面自动化动不了手(%s)", line)
            else:
                logger.info("桌面自动化:%s", line)
            # running = 能动手;partial = Windows 上却一条路都没有;info = 这台没有 Windows 桌面(不算降级)
            self.service_manager.services["microsoft_ufo_integration"].status = state
            self.desktop_automation_line = line
            return True
        except Exception as e:
            logger.error("桌面自动化启动失败: %s", e)
            return False

    @staticmethod
    def banner(results: Any) -> Tuple[str, str, List[Tuple[str, str, str]]]:
        """启动横幅「核心服务」那一段:(一句话, 状态, 逐行明细)。

        数的是**真实状态**,不是 ``start_*`` 的返回值 —— 原先「部分可用」也返回 True,数出来是「3/3 就绪」,而日志里
        同时写着「部分可用」。``info`` = 不适用(桌面自动化在没有 Windows 桌面的机器上):不算进分母、不算降级。
        """
        r = results if isinstance(results, dict) else {}
        items = [
            ("Device Agent 管理器", r.get("device_agent_manager", "failed")),
            ("设备状态 API :8766", r.get("device_status_api", "failed")),
            ("桌面自动化", r.get("microsoft_ufo_integration", "failed")),
        ]
        word = {
            "running": ("就绪", "ok"),
            "failed": ("未起来", "warn"),
            "info": ("不适用(这台没有 Windows 桌面)", "info"),
        }
        scored = [v for _, v in items if v != "info"]
        up = sum(1 for v in scored if v == "running")
        part = sum(1 for v in scored if v not in ("running", "failed"))
        status = "ok" if up == len(scored) else ("warn" if up or part else "fail")
        summary = f"{up}/{len(scored)} 就绪" + (f" · {part} 个部分可用" if part else "")
        return summary, status, [(n, *word.get(v, (f"部分可用({v})", "warn"))) for n, v in items]

    #: 三个核心服务的显示名。名字只此一处,调用方不另抄。
    SERVICE_LABELS = {
        "device_agent_manager": "Device Agent 管理器",
        "device_status_api": "设备状态 API",
        "microsoft_ufo_integration": "桌面自动化",
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

        返回 ``{服务名: "running" / "partial" / "failed" / "info"}``。
        ``info`` = 不适用(比如桌面自动化在没有 Windows 桌面的机器上),不算降级。

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
            elif status == "info":  # 桌面自动化:这台没有 Windows 桌面 —— 不适用,不是降级
                print_status(f"{label} 不适用(这台没有 Windows 桌面)", "info")
            else:
                print_status(f"{label} 部分可用({status})", "warning")

        return results
