"""协议漂移必须**被记下来**,而不是悄悄归到一个看起来正常的默认值。

## 修的是什么(P3-2 的运行时那一半)

三端(V2 / 安卓 / 手表)靠事先约好的字段取值通信。V2 侧此前对漂移有两种处理,
都不好 —— 实测(改之前,``AndroidDevice.from_registration``)::

    缺 platform 字段      → DevicePlatform.ANDROID   ← 没报却被当成安卓
    platform='wearos'     → ValueError               ← 手表仓的取值,枚举里没有

**前者是凭空造事实。** 同一个函数上面几行就写着 PR-7A 的纪律 ——「没报能力 →
NONE,不给乐观默认」—— 这条纪律没覆盖到 platform / device_type。

**后者会让注册在半路炸掉。** 调用方若吞掉异常,表现就是设备**静默注册不上**,
而且没有任何地方留下"我见过一个不认识的取值"的记录 —— 最难查的那种漂移。
注意 ``wearos`` 不是我随手编的:那正是手表仓库这一侧的平台名。

## 修法

新增 ``core/protocol_drift_registry.py``:缺失 / 不认识一律归 UNKNOWN,并**带着
原始字符串**登记。原始字符串是关键 —— 只记"有漂移"而不记"漂移成了什么",
排查时等于没记,而这个字符串正是去对面仓库里搜的唯一线索。

消息类型那一层仓库早就这么做了(``UNKNOWN_MESSAGE_TYPE``,见 android_bridge),
字段层此前缺了这一环,这里补齐。
"""

from __future__ import annotations

from enum import Enum

import pytest

from core.protocol_drift_registry import (
    MAX_DISTINCT_ENTRIES,
    MAX_RAW_VALUE_CHARS,
    REASON_ABSENT,
    REASON_UNRECOGNIZED,
    coerce_protocol_enum,
    drift_entries,
    drift_summary,
    has_unrecognized_drift,
    reset_protocol_drift_registry,
)


class Color(str, Enum):
    RED = "red"
    UNKNOWN = "unknown"


class NoUnknown(str, Enum):
    RED = "red"


@pytest.fixture(autouse=True)
def clean_registry():
    """登记表是进程级的,每条用例前后都清干净。

    不清就会把假漂移留给后面的用例 —— 这个会话刚修过的治理自评就是栽在这种
    跨用例污染上。
    """
    reset_protocol_drift_registry()
    yield
    reset_protocol_drift_registry()


def _coerce(raw, **kw):
    return coerce_protocol_enum(Color, raw, surface="probe", field_name="color", **kw)


# ── 三种情形 ────────────────────────────────────────────────────────────


def test_known_value_passes_through_and_is_not_recorded():
    """认识的取值原样返回,且**不该**留下漂移记录 —— 否则登记表会被正常流量淹没。"""
    assert _coerce("red") is Color.RED
    assert drift_entries() == []
    assert has_unrecognized_drift() is False


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_absent_value_becomes_unknown_not_an_optimistic_default(absent):
    """缺失 → UNKNOWN,并记 ``absent``。

    这条对应的是真实缺陷:设备**没报**平台,却被记成"安卓"。不给乐观默认。
    """
    assert _coerce(absent) is Color.UNKNOWN

    entries = drift_entries()
    assert len(entries) == 1
    assert entries[0]["reason"] == REASON_ABSENT


def test_unrecognized_value_becomes_unknown_and_keeps_the_raw_string():
    """不认识 → UNKNOWN,**且原始字符串必须留下来**。

    只记"有漂移"而不记"漂移成了什么",排查时等于没记 —— 那个字符串是去对面
    仓库里搜的唯一线索。
    """
    assert _coerce("chartreuse", device_id="dev-9") is Color.UNKNOWN

    entries = drift_entries()
    assert len(entries) == 1
    assert entries[0]["reason"] == REASON_UNRECOGNIZED
    assert entries[0]["raw_value"] == "chartreuse", "原始取值没被记下来"
    assert entries[0]["last_device_id"] == "dev-9"
    assert has_unrecognized_drift() is True


def test_absent_alone_is_not_reported_as_a_forked_contract():
    """``absent`` 不算契约分叉。

    缺字段多半只是对面版本旧、还没开始发;取值不认识才说明双方的取值集合已经
    分叉了。两者混为一谈会让"分叉"这个信号失去意义。
    """
    _coerce(None)
    assert has_unrecognized_drift() is False, "仅仅是字段缺失,不该被判为契约分叉"


def test_enum_member_passes_through():
    """已经是枚举成员时原样返回(调用方可能已经转过一次)。"""
    assert _coerce(Color.RED) is Color.RED
    assert drift_entries() == []


# ── 有界性 ──────────────────────────────────────────────────────────────


def test_repeated_bad_value_is_counted_not_duplicated():
    """同一个坏值重复出现只累计计数。

    对面可能重连风暴式地反复发同一个坏值;每次新增一条记录会把内存吃光。
    """
    for _ in range(50):
        _coerce("chartreuse")

    entries = drift_entries()
    assert len(entries) == 1
    assert entries[0]["count"] == 50


def test_registry_is_bounded_and_says_so():
    """ "每次都不同"的坏值不能把登记表撑爆,而且截断必须**如实上报**。

    只封顶不上报,等于让上限把问题规模悄悄抹平 —— 看到的 distinct 数会显得很
    正常,实际早就溢出了。
    """
    for i in range(MAX_DISTINCT_ENTRIES + 25):
        _coerce(f"bogus-{i}")

    summary = drift_summary()
    assert summary["distinct_entries"] == MAX_DISTINCT_ENTRIES
    assert summary["truncated"] is True, "溢出了却没说"
    assert summary["dropped_events"] == 25
    assert summary["total_events"] == MAX_DISTINCT_ENTRIES + 25, "总量必须仍然准确,不能被上限吃掉"


def test_absurdly_long_raw_value_is_truncated():
    """对面可能发一个超长字符串,不能原样存进来。"""
    _coerce("x" * (MAX_RAW_VALUE_CHARS * 3))

    raw = drift_entries()[0]["raw_value"]
    assert len(raw) <= MAX_RAW_VALUE_CHARS + 1, f"原始值没截断,长度 {len(raw)}"


# ── 我们自己的契约没定义好时,要响亮地失败 ──────────────────────────────


def test_enum_without_unknown_member_fails_loudly():
    """枚举没有 UNKNOWN 成员 → 抛 LookupError。

    这属于**我们自己的**契约没准备好承接漂移,应当在开发期响亮失败,而不是
    运行时悄悄兜住 —— 兜住的话,这个字段的漂移就永远没人知道。
    """
    with pytest.raises(LookupError, match="UNKNOWN"):
        coerce_protocol_enum(NoUnknown, "whatever", surface="probe", field_name="c")


# ── 真实解析点的端到端回归 ──────────────────────────────────────────────


def test_android_registration_no_longer_invents_a_platform():
    """真实缺陷回归①:设备没报平台,不得被记成安卓。"""
    from galaxy_gateway.android.models import AndroidDevice, DevicePlatform

    device = AndroidDevice.from_registration({"device_id": "drift-a"})

    assert device.platform is DevicePlatform.UNKNOWN, "设备没报平台,却被凭空记成了某个具体平台"


def test_android_registration_survives_an_unknown_platform():
    """真实缺陷回归②:手表侧的 ``wearos`` 不再让注册解析抛异常。

    改之前:``ValueError: 'wearos' is not a valid DevicePlatform``。
    """
    from galaxy_gateway.android.models import AndroidDevice, DevicePlatform

    device = AndroidDevice.from_registration({"device_id": "drift-b", "platform": "wearos"})

    assert device.platform is DevicePlatform.UNKNOWN
    assert any(
        e["raw_value"] == "wearos" and e["reason"] == REASON_UNRECOGNIZED for e in drift_entries()
    ), "不认识的平台值没有被登记 —— 漂移发生了却查不到"


def test_android_registration_still_accepts_known_values():
    """不能为了兜住漂移就把正常路径也一起降级。"""
    from galaxy_gateway.android.models import AndroidDevice, DevicePlatform

    device = AndroidDevice.from_registration(
        {"device_id": "drift-c", "platform": "android", "device_type": "android_phone"}
    )

    assert device.platform is DevicePlatform.ANDROID
    assert drift_entries() == [], "两个字段都如实上报了,不该产生任何漂移记录"


def test_partially_reported_registration_records_only_the_missing_field():
    """只报了一半时,登记的必须**恰好**是缺的那个字段。

    第一版这条用例我自己只给了 ``platform`` 就断言"零记录",结果被如实报红 ——
    ``device_type`` 缺失被登记了,而那正是修复应有的行为。留下这条,把"缺哪个记
    哪个"这个精度钉住:记多了会淹没真信号,记少了等于漏报。
    """
    from galaxy_gateway.android.models import AndroidDevice

    AndroidDevice.from_registration({"device_id": "drift-d", "platform": "android"})

    entries = drift_entries()
    assert [e["field"] for e in entries] == ["device_type"], f"应当只登记缺失的 device_type,实际 {entries}"
    assert entries[0]["reason"] == REASON_ABSENT
