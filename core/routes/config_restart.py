"""哪些配置键「改了要重启才生效」—— 唯一的清单。

面板「保存」之后界面显示已保存、值也确实写进了环境变量和 ``.env``，但有一批键的**读取点在启动（或导入）时**：
进程里已经起好的东西不会再回头看它。没有这张表之前，面板上没有任何提示 —— 用户点了、看到「已保存」，
却什么都没变，只有下次启动才起作用。

这里只登记**从读取位置核实过**的键，每个写明为什么。没核实过的不登记：错标「要重启」和漏标一样会让人困惑。
``GET /api/config/all`` 与 ``GET /api/config/bundles`` 把它带给面板；面板只负责说出来，不另存一份。

判据：改了这个键之后，**已经在跑的进程**里有没有东西会立刻照新值办事？没有（或只有一部分）→ 登记。
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

RESTART_REQUIRED: Dict[str, str] = {
    # ── 声音 ──
    "GALAXY_VOICE": "语音循环与麦克风在启动时才决定起不起（语音输出的静音是即时的）",
    "GALAXY_LOCAL_AUDIO": "音频管线创建时读一次",
    # ── 感知与在场 ──
    "GALAXY_AMBIENT_LOOP": "常驻注意力循环在启动时决定起不起",
    # ── 多设备与网络 ──
    "GALAXY_CROSS_DEVICE_ENABLED": "网关的跨设备路由即时生效；系统运行模式、桌面在场的跨设备模式、消息总线等启动时才解析",
    "GALAXY_MASTER_BRAIN_ENABLED": "主脑与 worker 在启动时才拉起",
    "GALAXY_NATS_ENABLED": "内置消息总线在启动时才起",
    "GALAXY_LAN_DISCOVERY": "局域网发现在启动时才起",
    "GALAXY_MDNS": "mDNS 广播在网关启动时才注册",
    "GALAXY_REMOTE_DESKTOP": "启动时决定要不要自动开远程桌面（运行中另有要鉴权的接口和托盘可手动开）",
    "FEDERATION_ENABLED": "联邦在启动时才连对端",
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": "打开后整个进程一直生效，关掉要重启（结果在进程里缓存）",
    "GALAXY_TS_FUNNEL": "Tailscale Funnel 的开关在模块导入时读一次",
    "GALAXY_HF_MIRROR": "模型下载镜像在启动时设进环境",
    # ── 桌面操作与自治 ──
    "GALAXY_DURABLE_EXEC": "任务图单例在启动时按这个键决定要不要落盘与续跑",
}


def restart_reason(key: str) -> Optional[str]:
    """这个键改了要重启才生效就返回原因，否则 ``None``。"""
    return RESTART_REQUIRED.get(key)


def any_requires_restart(keys: Iterable[str]) -> bool:
    return any(k in RESTART_REQUIRED for k in keys)


__all__ = ["RESTART_REQUIRED", "any_requires_restart", "restart_reason"]
