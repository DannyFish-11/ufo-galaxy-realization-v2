"""启动横幅「消息总线」那一行:总线、tailnet、局域网发现三件事的如实说法。

从 ``launcher/services.py`` 挪出来(那边有行数预算)。

三件事各看各的,**都不是「跨设备」开关的附属品**(那个开关只说这台电脑作为设备进不进网络):

* **NATS 总线**:电脑加入设备网络(跨设备模式)或开了任务派发才起。都没有时不起是**对的状态**,
  不是降级 —— 所有者 Windows 真机日志里它被画成 ⚠、算进「降级」,一个按设计就该这样的状态每次开机
  都被当成毛病报一遍。
* **局域网发现(mDNS 广播 ``_galaxy._tcp``)**:一直做(``GALAXY_MDNS=0`` 可关)。手表、手机靠它在同一
  Wi-Fi 下找到智能体,与电脑自己进不进网络无关。
* **自建内网(tailnet)**:配了 headscale(或电脑在跨设备模式)就入网 —— 手表出门直连连的就是它。
  两样都没有时不碰 Tailscale,横幅只给一行说明,不报警告。
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
            "进程内总线(没加入设备网络、也没开任务派发,用不到 NATS)",
            "ok",
            [("NATS Bus", f"未启用:{res.get('reason') or '本地模式'}", "info")],
            None,
        )
    if res.get("disabled"):
        # 跨设备模式下却被显式关掉 —— 那是一个配置意图,但 NATS 上的那部分确实用不了,如实标注影响。
        return (
            "进程内总线 · 没起 NATS,NATS worker 派发与多机 mesh 不可用",
            "warn",
            [
                ("NATS Bus", f"未启用:{res.get('reason') or '按配置关闭'}", "info"),
                ("影响", "NATS worker 派发 / 多机 mesh 不可用;设备经网关照常协调", "info"),
            ],
            "如需 NATS worker / 多机 mesh:去掉 GALAXY_NATS_ENABLED=false 并确保 nats-server 可运行",
        )
    # 语气是「单机模式正常」:NATS 起不来不是单机故障 —— 进程内总线已接管全部单机语义。
    err = res.get("error") or "未知原因"
    hint = res.get("hint") or (
        "检查 nats-server 是否可运行(手动执行 nats-server -v 验证);"
        "单机使用可设 GALAXY_NATS_ENABLED=false 明确关闭此项"
    )
    return (
        f"进程内总线 · NATS 未启动:{err[:60]},仅 NATS worker 派发与多机 mesh 不可用",
        "warn",
        [
            ("NATS Bus", f"未启动:{err}", "warn"),
            (
                "降级",
                "已自动切换进程内总线 —— 本机功能与经网关的设备协调都正常;仅 NATS worker 派发 / 多机 mesh 不可用",
                "info",
            ),
            ("修复", hint, "info"),
        ],
        hint,
    )


async def _tailnet_rows(svc: Any) -> List[Detail]:
    """这台电脑入 tailnet:入成了说地址,没入成说原因与下一步。"""
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
    return bus_details


async def _network_rows(svc: Any, cross_device: bool) -> List[Detail]:
    """入 tailnet 与局域网发现 —— 不看「跨设备」开关能不能做,只看有没有要做的理由。"""
    if cross_device or svc.tailnet.wanted():
        bus_details = await _tailnet_rows(svc)
    else:
        bus_details = [
            ("Tailscale", "没配自建 tailnet,不入网(在家同一 Wi-Fi 下手表照常连;出门直连要先配 headscale)", "info")
        ]
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
    details.extend(await _network_rows(svc, cross_device))
    return value, status, details, hint
