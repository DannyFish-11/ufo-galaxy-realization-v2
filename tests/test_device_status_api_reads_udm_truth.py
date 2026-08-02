"""面板要查的 :8766 设备状态接口,读的必须是 UDM 的真相。

## 修的是什么(P3-3 读路径统一,第二处)

``core/device_status_api.py`` 是一个**活的** HTTP 服务:``launcher/core_services.py``
用 uvicorn 把它起在 :8766,``unified_launcher.py`` 的就绪横幅里也列着它。它的
文件头与 ``core/unified/device_manager.py:22`` 都写明本模块是
"compatibility layer,不得作为平行真相源"。

写路径确实遵守了 —— ``register_device`` / ``update_device_status`` 都先
write-through 到 UDM。但**读路径一次都没提过 UDM**(改之前全文件 grep
``unified`` 命中 0 次):``get_device_status`` / ``get_all_devices`` /
``get_devices_by_category`` / ``get_online_devices`` / ``get_status_summary``
全都直接遍历本地 ``self._devices``。

后果比调度池那处更直观:**UDM 明知已离线的设备,面板上照样显示在线**。这正是
"存了/看到的不是真相"那一类症状 —— 而且是用户直接看得见的那一面。

## 修法

与 ``core.device_registry.list_devices`` 保持一致(那边早就这么做了,这里复用
同一套路,不另起炉灶):每个读方法开头把 UDM 的在线状态刷进本地缓存。

判据**只覆盖、不臆造**:UDM 有记录就以它为准;UDM 查不到这台设备则保持本地值
(write-through 是 best-effort,凭空改成离线等于制造假信息);UDM 整体不可用就
跳过,展示面不该因为 SSOT 抖动而全空。
"""

from __future__ import annotations

import pytest

from core.device_status_api import DeviceCategory, DeviceState, DeviceStatusManager
from core.unified.device_manager import get_unified_device_manager
from core.unified.models import UnifiedDeviceStatus


@pytest.fixture
def manager():
    """``DeviceStatusManager`` 是单例,用完把本用例注册的设备清掉。

    不清理就会把假设备留给后面的用例 —— 这个会话里刚修过的
    ``test_completeness_review_needs_durable_evidence`` 讲的就是这种污染。
    """
    mgr = DeviceStatusManager()
    registered: list[str] = []
    original_register = mgr.register_device

    def tracking_register(device_state: DeviceState) -> bool:
        registered.append(device_state.device_id)
        return original_register(device_state)

    mgr.register_device = tracking_register  # type: ignore[method-assign]
    try:
        yield mgr
    finally:
        mgr.register_device = original_register  # type: ignore[method-assign]
        for did in registered:
            mgr._devices.pop(did, None)
            mgr._status_history.pop(did, None)


def _register(mgr: DeviceStatusManager, device_id: str) -> None:
    mgr.register_device(
        DeviceState(
            device_id=device_id,
            device_name=device_id,
            device_type="android",
            category=DeviceCategory.MOBILE,
            is_online=True,
        )
    )


async def test_udm_offline_is_reflected_in_single_device_read(manager):
    """核心回归:UDM 判离线后,单设备查询不能还说在线。"""
    _register(manager, "dsa-single")
    assert manager.get_device_status("dsa-single")["is_online"] is True, "前置条件不成立"

    get_unified_device_manager().update_device_status("dsa-single", UnifiedDeviceStatus.OFFLINE)

    assert (
        manager.get_device_status("dsa-single")["is_online"] is False
    ), "UDM 已判离线,:8766 仍报在线 —— 读路径没跟上 SSOT"


async def test_udm_offline_device_drops_out_of_online_list(manager):
    """在线列表是面板最常用的那个,必须跟着 UDM 走。"""
    _register(manager, "dsa-a")
    _register(manager, "dsa-b")

    online = {d["device_id"] for d in manager.get_online_devices()}
    assert {"dsa-a", "dsa-b"} <= online, f"前置条件不成立,实际 {online}"

    get_unified_device_manager().update_device_status("dsa-a", UnifiedDeviceStatus.OFFLINE)

    online = {d["device_id"] for d in manager.get_online_devices()}
    assert "dsa-a" not in online, "UDM 已判离线,仍出现在在线列表里"
    assert "dsa-b" in online, "只该剔掉离线那台,不该误伤在线的"


async def test_summary_counts_follow_udm(manager):
    """摘要里的在线计数同样不能自成一套。"""
    _register(manager, "dsa-sum-1")
    before = manager.get_status_summary()["online_devices"]

    get_unified_device_manager().update_device_status("dsa-sum-1", UnifiedDeviceStatus.OFFLINE)

    after = manager.get_status_summary()["online_devices"]
    assert after == before - 1, f"摘要在线数没跟着 UDM 变化(前 {before} 后 {after})"


async def test_udm_back_online_is_reflected_too(manager):
    """反向也要跟:UDM 判回在线,展示面得跟着回来。

    只单向覆盖(离线时覆盖、恢复时不覆盖)会造成设备"一旦掉线就再也不显示在线",
    那是另一种假信息。
    """
    _register(manager, "dsa-flap")
    udm = get_unified_device_manager()

    udm.update_device_status("dsa-flap", UnifiedDeviceStatus.OFFLINE)
    assert manager.get_device_status("dsa-flap")["is_online"] is False

    udm.update_device_status("dsa-flap", UnifiedDeviceStatus.ONLINE)
    assert manager.get_device_status("dsa-flap")["is_online"] is True, "UDM 判回在线,展示面却卡在离线"


async def test_device_unknown_to_udm_keeps_local_value(manager):
    """降级路径:UDM 里没有这台设备时,保持本地值,不凭空改成离线。

    write-through 是 best-effort(UDM 写失败时仍保留本地记录以维持展示)。
    这时把它改成离线,等于制造一条 UDM 从没说过的假信息。

    构造方式:正常注册(本地缓存与 UDM 都有),再把它**只从 UDM 注销**。这样
    留下的正是要测的那个状态 —— 本地有记录、UDM 查不到 —— 而且全程只用公开
    API。第一版我图省事直接写 ``manager._devices[id] = ...``,被
    ``scripts/audit_udm_write_paths.py`` 如实判为"绕过 SSOT 的直写"并让
    ssot-udm-conformance 门变红。**那个门抓对了**:测试也不该示范绕过写路径的
    写法,否则就是在给后来者背书。
    """
    device_id = "dsa-unknown-to-udm"
    _register(manager, device_id)
    assert manager.get_device_status(device_id)["is_online"] is True, "前置条件不成立"

    get_unified_device_manager().unregister_device(device_id)

    assert manager.get_device_status(device_id)["is_online"] is True, "UDM 里查不到的设备被凭空判成了离线"


async def test_udm_unavailable_does_not_wipe_the_display(manager, monkeypatch):
    """UDM 整体不可用时跳过覆盖 —— 展示面不该因为 SSOT 抖动而全空。"""

    def _boom():
        raise RuntimeError("UDM 不可用(模拟)")

    _register(manager, "dsa-resilient")
    monkeypatch.setattr("core.unified.device_manager.get_unified_device_manager", _boom)

    assert manager.get_device_status("dsa-resilient")["is_online"] is True


def test_offline_status_set_only_names_real_statuses():
    """守卫自检:离线名单里的字符串必须是真实存在的 ``UnifiedDeviceStatus`` 值。

    拼错一个字母不会报错,只会让覆盖静默失效,而本文件其它用例(用的是正确拼写)
    照样全绿。
    """
    valid = {s.value for s in UnifiedDeviceStatus}
    unknown = set(DeviceStatusManager._UDM_OFFLINE_STATUSES) - valid
    assert not unknown, f"离线名单里有 UnifiedDeviceStatus 中不存在的值:{unknown}"
