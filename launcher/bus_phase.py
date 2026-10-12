"""启动横幅「消息总线」那一行:总线、tailnet、局域网发现三件事的如实说法。

从 ``launcher/services.py`` 挪出来(那边有行数预算)。

**本地模式**(只用这台电脑,``core.system_mode.cross_device_requested()`` 为假):

* 不起 NATS 是**对的状态**,不是降级。所有者 Windows 真机日志里它被画成 ⚠、算进了
  「就绪 · 7 正常 · 4 降级」,还在降级栏里挂着「如需跨设备:……」—— 一个按设计就该这样的
  状态,每次开机都被当成毛病报一遍。
* 不入 tailnet、不往局域网广播 ``_galaxy._tcp``。本地模式没有别的设备要来找这台电脑;
  广播只会把一台「只用本机」的电脑暴露给同一 Wi-Fi 下的所有人(真机日志里还多出一条
  原因为空的「mDNS: failed to start:」)。

**跨设备模式**照旧:三件都做,起不来如实降级(NATS 起不来时进程内总线接管单机语义)。
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

#: 横幅明细的一行:(名称, 内容, 状态)
Detail = Tuple[str, str, str]


def _nats_rows(res: dict, cross_device: bool) -> Tuple[str, str, List[Detail], Optional[str]]:
    """按 ``start_nats()`` 的结构化真实结果说话 —— 不把「没抛异常」当成「起来了」。

    (旧代码 ``try: await start_nats()`` 不抛即成功:``NATSBus.connect()`` 失败时只返回
    ``{"success": False}``,nats-server.exe 被 WDAC 拦下时横幅照打「✓ 消息总线」—— 假绿。)
    """
    if res.get("ok"):
        url = res.get("url") or "已连接"
        return url, "ok", [("NATS Bus", url, "ok")], None
    if res.get("disabled") and not cross_device:
        return (
            "进程内总线(本地模式用不到 NATS)",
            "ok",
            [("NATS Bus", f"未启用:{res.get('reason') or '本地模式'}", "info")],
            None,
        )
    if res.get("disabled"):
        # 跨设备模式下却被显式关掉 —— 那是一个配置意图,但跨设备分发确实用不了,如实标注影响。
        return (
            "单机模式正常(进程内总线)· 没起 NATS,跨设备分发不可用",
            "warn",
            [
                ("NATS Bus", f"未启用:{res.get('reason') or '按配置关闭'}", "info"),
                ("影响", "跨设备任务分发/集群 mesh 不可用;单机进程内总线正常工作", "info"),
            ],
            "如需跨设备分发:去掉 GALAXY_NATS_ENABLED=false 并确保 nats-server 可运行",
        )
    # 语气是「单机模式正常」:NATS 起不来不是单机故障 —— 进程内总线已接管全部单机语义。
    err = res.get("error") or "未知原因"
    hint = res.get("hint") or (
        "检查 nats-server 是否可运行(手动执行 nats-server -v 验证);"
        "单机使用可设 GALAXY_NATS_ENABLED=false 明确关闭此项"
    )
    return (
        f"单机模式正常(进程内总线)· NATS 未启动:{err[:60]},仅跨设备分发不可用",
        "warn",
        [
            ("NATS Bus", f"未启动:{err}", "warn"),
            ("降级", "已自动切换进程内总线 —— 单机功能全部正常;仅跨设备任务分发/集群 mesh 不可用", "info"),
            ("修复", hint, "info"),
        ],
        hint,
    )


async def _network_rows(svc: Any) -> List[Detail]:
    """跨设备模式才做的两件:这台电脑入 tailnet、在局域网发布自己。"""
    bus_details: List[Detail] = []
    try:
        ts_ip = await svc.start_tailscale()
        bus_details.append(("Tailscale", ts_ip or "已连接", "ok"))
        # PR-PEER-RELAY: 显示对等中继态(本机已宣告 / 各 peer 经哪条中继)。
        try:
            from core.tailscale_manager import TailscaleManager

            rs = TailscaleManager().get_relay_status()
            if rs.get("advertise_relay_enabled"):
                via = rs.get("self_relay")
                bus_details.append(("对等中继", ("已宣告（本机充当私有中继）" if not via else f"经 {via}"), "ok"))
        except Exception:  # noqa: BLE001 — 中继态只是一行附注
            pass
    except Exception:  # noqa: BLE001 — 没装 / 没入成,横幅如实说
        bus_details.extend(svc.tailnet.not_on_tailnet_details())
    bus_details.append(svc.tailnet.start_lan_discovery())
    return bus_details


async def bus_phase(svc: Any) -> Tuple[str, str, List[Detail], Optional[str]]:
    """「消息总线」这一阶段:``(一行的值, 状态, 明细, 降级时的专属修复建议)``。"""
    from core.system_mode import cross_device_requested

    cross_device = cross_device_requested()
    try:
        res = await svc.start_nats()
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "url": "", "error": str(exc), "hint": "", "disabled": False}
    value, status, details, hint = _nats_rows(res, cross_device)
    if cross_device:
        details.extend(await _network_rows(svc))
    else:
        details.append(("局域网发现", "本地模式不入网、不广播(只用这台电脑;打开「跨设备」才会)", "info"))
    return value, status, details, hint
