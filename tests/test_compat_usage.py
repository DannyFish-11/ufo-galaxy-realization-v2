"""旧面到底还有没有人用 —— 让退役日期有依据可定。

为什么这个文件存在
------------------
路线图 Q6("AIP v2 / 旧 REST 别名的退役日期定在哪天")挡着 C5 与 C6 两项,
而它挡在**没有数据**上:四条旧 REST 别名和三条兼容 WS 入口,此前只有一行
``logger.info``。日志会滚,没有任何一处能回答"上周有多少次调用、是谁在调"。

于是日期只能拍脑袋:定早了打死还在用的客户端,定晚了这些面继续常开 ——
而它们每一条都是攻击面。

这里钉三件事:
A. 用量真的被记下来了,而且是记在**汇合点**上(散到各路由必然漏一条,
   漏掉的那条会显示成"没人用",然后被据此退役掉);
B. "0 次"不许被读成"没人用" —— 这是这份数据里最容易读错、且读错后果最严重的一格;
C. 只发 Deprecation 不发 Sunset —— 日期还没定,而它正是这份数据要支撑的东西。
"""

from __future__ import annotations

import pytest

from core import compat_usage as cu


@pytest.fixture(autouse=True)
def _clean():
    cu.reset_usage()
    yield
    cu.reset_usage()


# ══════════════════════════════════════════════════════════════════════════
# A. 用量真的被记下来了
# ══════════════════════════════════════════════════════════════════════════


def test_a01_a_call_is_counted():
    cu.record_use("/api/devices/list")
    cu.record_use("/api/devices/list")
    entry = next(s for s in cu.usage_report()["surfaces"] if s["surface"] == "/api/devices/list")
    assert entry["calls"] == 2


def test_a02_client_hints_answer_who_not_just_how_many():
    """ "还在用的是谁"比"还有多少次"更能支撑退役决定 —— 知道是哪个 app 版本,
    才知道该先推谁升级。"""
    cu.record_use("/api/devices/register", client_hint="android/3.2.1")
    entry = next(s for s in cu.usage_report()["surfaces"] if s["surface"] == "/api/devices/register")
    assert entry["client_hints"] == ["android/3.2.1"]


def test_a03_client_hints_are_bounded():
    """客户端自报的字符串是**外部可控**的。无界收集等于给对面一个撑爆内存的开关。"""
    for i in range(cu.CLIENT_HINTS_MAX + 30):
        cu.record_use("/api/devices/register", client_hint=f"ua-{i}")
    entry = next(s for s in cu.usage_report()["surfaces"] if s["surface"] == "/api/devices/register")
    assert len(entry["client_hints"]) == cu.CLIENT_HINTS_MAX


def test_a04_an_unregistered_surface_is_surfaced_not_dropped():
    """没登记过的兼容面被调用了,本身就是要被看见的事实 —— 静默丢掉等于假装它不存在。"""
    cu.record_use("/api/devices/somethingelse")
    report = cu.usage_report()
    assert [u["surface"] for u in report["unregistered_surfaces"]] == ["/api/devices/somethingelse"]


def test_a05_recording_never_raises():
    """记账失败不该影响被记的那次调用。"""
    for bad in ("", None, 12345):
        cu.record_use(bad)  # type: ignore[arg-type]


def test_a06_the_ws_convergence_point_records():
    """WS 入口记在**汇合点**上,不在每条路由里各写一遍。

    那个处理器自己的 docstring 已经写了所有入口都收敛到它,
    "so message handling and ingress accounting cannot diverge per route" ——
    用量记账同理。
    """
    import inspect

    from galaxy_gateway.routes import websocket as ws

    body = inspect.getsource(ws._handle_android_ws)
    assert "record_use" in body
    assert 'ingress_classification == "compat"' in body


def test_a07_all_four_rest_aliases_go_through_one_exit():
    """四条 REST 别名共用一个出口 —— 各写一遍必然漏掉一条。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core/routes/compat.py").read_text(encoding="utf-8")
    for surface in (
        "/api/devices/register",
        "/api/devices/list",
        "/api/devices/heartbeat",
        "/api/devices/unregister",
    ):
        assert f'_legacy("{surface}"' in src or f'_legacy(\n            "{surface}"' in src, surface


# ══════════════════════════════════════════════════════════════════════════
# B. "0 次"不许被读成"没人用"
# ══════════════════════════════════════════════════════════════════════════


def test_b01_the_report_says_what_zero_means():
    """这份数据里最容易读错的一格。读错的后果正好是要防的那个:
    据此提前退役掉一个其实还在用的面。"""
    report = cu.usage_report()
    assert "不等于" in report["zero_means"]
    assert "galaxy_compat_surface_calls_total" in report["zero_means"]


def test_b02_the_report_carries_its_own_range():
    """计数在进程内、重启归零,所以"0 次"的射程只有本进程运行时长这么长。
    不带 since/uptime,这句话就没法被验证。"""
    report = cu.usage_report()
    assert report["since"] > 0
    assert report["uptime_seconds"] >= 0


def test_b03_never_used_and_never_seen_are_the_same_field_but_documented():
    """未被调用的面 calls=0、first_seen=None —— None 与 0 分开,
    让"这个进程从没见过它"看得出来。"""
    entry = next(s for s in cu.usage_report()["surfaces"] if s["surface"] == "/ws/ufo3/{device_id}")
    assert entry["calls"] == 0
    assert entry["first_seen"] is None


def test_b04_prometheus_is_the_durable_record():
    """跨重启留存靠外部时序库抓取,不靠进程内计数。这条钉住那份输出真的在。"""
    lines = cu.prometheus_lines()
    assert any(line.startswith("# TYPE galaxy_compat_surface_calls_total counter") for line in lines)
    assert any('surface="/api/devices/register"' in line for line in lines)


def test_b05_prometheus_output_is_emitted_by_the_gateway():
    import inspect

    from galaxy_gateway.observability import GatewayMetrics

    body = inspect.getsource(GatewayMetrics)
    assert "compat_usage" in body


# ══════════════════════════════════════════════════════════════════════════
# C. 只发 Deprecation,不发 Sunset
# ══════════════════════════════════════════════════════════════════════════


def test_c01_deprecation_header_is_sent():
    assert cu.deprecation_headers("/api/devices/list")["Deprecation"] == "true"


def test_c02_no_sunset_header_until_a_date_is_chosen():
    """发 Sunset 等于对外承诺一个日期,而那个日期正是这份数据要支撑的东西。
    先编一个贴上去再回头验证,顺序是反的 —— 而且对面会当真。"""
    assert cu.SUNSET_AT == ""
    assert "Sunset" not in cu.deprecation_headers("/api/devices/list")
    assert cu.usage_report()["sunset_at"] is None


def test_c03_a_chosen_date_does_get_sent(monkeypatch):
    """日期定下来之后不需要改代码结构 —— 填一个值就发。"""
    monkeypatch.setattr(cu, "SUNSET_AT", "Wed, 31 Dec 2026 23:59:59 GMT")
    assert cu.deprecation_headers("/api/devices/list")["Sunset"] == "Wed, 31 Dec 2026 23:59:59 GMT"


def test_c04_the_header_points_at_the_replacement():
    """只告诉对面"这条要没了"不够,得告诉它该改到哪儿去。"""
    assert "/api/v1/devices/register" in cu.deprecation_headers("/api/devices/register")["Link"]


def test_c05_an_unknown_surface_gets_no_invented_successor():
    """说不出规范路径就不说 —— 编一个出来会把对面指到不存在的地方。"""
    assert "Link" not in cu.deprecation_headers("/api/devices/whoknows")


def test_c06_the_diagnostics_endpoint_exists():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core/routes/diagnostics.py").read_text(encoding="utf-8")
    assert "/api/v1/compat/usage" in src
