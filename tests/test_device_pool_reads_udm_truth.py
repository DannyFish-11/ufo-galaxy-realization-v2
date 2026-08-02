"""调度池的**读路径**必须服从 UDM(SSOT),不能只看自己的本地副本。

## 修的是什么(P3-3 读路径统一)

``core/unified/device_manager.py`` 顶部的架构声明写得很清楚:

    Downstream structures (device_registry, device_pool_manager, etc.) are
    compatibility / scheduling layers only and must NOT act as parallel
    canonical truth sources.

``DevicePoolManager`` 的**写**路径确实遵守了 —— ``register_device`` /
``unregister_device`` 都先 write-through 到 UDM 再改本地池记录(见
``_udm_write_register``)。但**读**路径从来没问过 UDM,于是两边会分叉。

实测复现(改之前,四行就够):

    pool.register_device("dev-A")                 # UDM: ONLINE,池子:有记录
    udm.update_device_status("dev-A", OFFLINE)    # 唯一合法的状态写路径
    udm.get_online_devices()                      # → []        UDM 知道它离线了
    pool.list_devices(eligible_only=True)         # → ['dev-A'] 池子不知道
    pool.select_device()                          # → 'dev-A'   照样往那儿派活

后果是任务被派到系统**明知已离线**的设备上。写统一了、读没统一,是最难受的
半截状态:写入口越规范,读路径读到的陈旧副本就越显眼。

## 修法

``_is_eligible()`` 是两条读路径(``list_devices(eligible_only=True)`` 与
``select_device()``)唯一的收敛点,把 SSOT 判据加在那里,顺序是"先问真相、
再问本地经验"。

判据刻意设计成**只否决、不批准**:

* UDM 明确说这台设备 offline / error / disconnected → 否决;
* UDM 里**查不到**这台设备 → 不否决(``register_device`` 的 write-through 是
  best-effort,UDM 写失败时仍保留本地池记录以维持调度;这时再否决等于
  "UDM 一抖动整个调度停摆");
* UDM 本身不可用 → 不否决,同上。

宁可漏否决,不可误否决 —— 误否决的症状是"设备明明在线却永远调度不到",
比派活到离线设备更难归因。
"""

from __future__ import annotations

import pytest

from core.device_pool_manager import DevicePoolManager, get_device_pool_manager
from core.unified.device_manager import get_unified_device_manager
from core.unified.models import UnifiedDeviceStatus


@pytest.fixture
def pool_and_udm():
    """每条用例用**独立**的池实例,但 UDM 是进程级单例(设计如此)。

    设备 id 带用例专属后缀,避免用例之间互相看到对方的设备 —— UDM 单例的状态
    是跨用例存活的,这一点不能假装不存在。
    """
    pool = DevicePoolManager()
    yield pool, get_unified_device_manager()


def test_udm_offline_removes_device_from_eligible_list(pool_and_udm):
    """核心回归:UDM 说离线,池子的可用列表里就不该再有它。"""
    pool, udm = pool_and_udm
    pool.register_device("p33-a", capabilities=["screenshot"], device_type="android")
    pool.register_device("p33-b", capabilities=["screenshot"], device_type="android")

    both = {d["device_id"] for d in pool.list_devices(eligible_only=True)}
    assert {"p33-a", "p33-b"} <= both, f"前置条件不成立:两台都该是可用的,实际 {both}"

    udm.update_device_status("p33-a", UnifiedDeviceStatus.OFFLINE)

    now = {d["device_id"] for d in pool.list_devices(eligible_only=True)}
    assert "p33-a" not in now, "UDM 已判离线,池子仍把它列为可用 —— 读路径没跟上 SSOT"
    assert "p33-b" in now, "只该剔掉离线那台,不该误伤在线的"


def test_udm_offline_device_is_never_selected(pool_and_udm):
    """比列表更要紧的一条:**不能把活派过去**。

    列表只是展示,``select_device()`` 的返回值会真的被拿去派任务。
    """
    pool, udm = pool_and_udm
    device_id = "p33-selectable"
    pool.register_device(device_id, capabilities=["p33-cap"], device_type="p33-type")

    # 前置条件:能被选中。用专属的 type + capability 把候选集收窄到这一台,
    # 不依赖"池子里只有它" —— DevicePoolManager 是进程级单例,别的用例注册的
    # 设备仍在里面。
    picked = {pool.select_device(device_type="p33-type", required_capabilities=["p33-cap"]) for _ in range(5)}
    assert picked == {device_id}, f"前置条件不成立,期望只能选到 {device_id},实际 {picked}"

    udm.update_device_status(device_id, UnifiedDeviceStatus.OFFLINE)

    # 多抽几次:轮转/自适应策略下"抽一次没抽到"证明不了"永远抽不到"。
    after = {pool.select_device(device_type="p33-type", required_capabilities=["p33-cap"]) for _ in range(10)}
    assert device_id not in after, f"UDM 已判离线,仍被选中派活(10 次抽样得到 {after})"
    assert after == {None}, f"候选集里本就只有这一台,离线后应当无设备可选,实际 {after}"


@pytest.mark.parametrize("status", ["offline", "error", "disconnected"])
def test_all_non_dispatchable_statuses_are_vetoed(pool_and_udm, status):
    """三种"收不了活"的状态都要否决,不只是 offline。"""
    pool, udm = pool_and_udm
    device_id = f"p33-status-{status}"
    pool.register_device(device_id, device_type="android")

    udm.update_device_status(device_id, UnifiedDeviceStatus(status))

    assert DevicePoolManager._udm_vetoes(device_id), f"UDM 状态 {status} 应当被否决"


@pytest.mark.parametrize("status", ["online", "busy", "initializing"])
def test_dispatchable_statuses_are_not_vetoed(pool_and_udm, status):
    """反面:这些状态不该被否决。

    ``busy`` / ``initializing`` 尤其重要 —— 把它们误判成不可用,症状是"设备明明
    在线却永远调度不到",比派活到离线设备更难归因。
    """
    pool, udm = pool_and_udm
    device_id = f"p33-ok-{status}"
    pool.register_device(device_id, device_type="android")

    udm.update_device_status(device_id, UnifiedDeviceStatus(status))

    assert not DevicePoolManager._udm_vetoes(device_id), f"UDM 状态 {status} 不该被否决"


def test_unknown_device_is_not_vetoed():
    """降级路径:UDM 里查不到 → **不否决**。

    ``register_device`` 的 UDM write-through 是 best-effort(写失败时仍保留本地池
    记录以维持调度,见其 docstring)。这种情况下再把设备否决掉,等于"UDM 一抖动,
    整个调度停摆" —— 那比原来的分叉更糟。
    """
    assert not DevicePoolManager._udm_vetoes("p33-never-registered-anywhere")


def test_veto_survives_udm_being_unavailable(monkeypatch):
    """UDM 本身炸了也不能否决 —— 否则一个不相关的故障会让调度全停。"""

    def _boom():
        raise RuntimeError("UDM 不可用(模拟)")

    monkeypatch.setattr("core.unified.device_manager.get_unified_device_manager", _boom)

    assert not DevicePoolManager._udm_vetoes("p33-anything")


def test_veto_list_only_names_statuses_that_exist():
    """守卫自检:否决名单里的字符串必须是真实存在的 ``UnifiedDeviceStatus`` 值。

    写错一个字母(比如 "offine")不会有任何报错 —— 它只是永远匹配不上,否决静默
    失效,而这个文件里其它用例**照样全绿**(它们用的是正确拼写)。这条把名单本身钉住。
    """
    valid = {s.value for s in UnifiedDeviceStatus}
    unknown = set(DevicePoolManager._UDM_NOT_DISPATCHABLE) - valid
    assert not unknown, f"否决名单里有 UnifiedDeviceStatus 中不存在的值:{unknown}"


def test_singleton_accessor_still_works():
    """``get_device_pool_manager()`` 是仓库里的既有入口,不能因为本次改动坏掉。"""
    assert isinstance(get_device_pool_manager(), DevicePoolManager)
