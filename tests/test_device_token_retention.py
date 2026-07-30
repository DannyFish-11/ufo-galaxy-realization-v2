"""设备 token 注册表的保留期 / 上限行为测试。

被修的真实缺陷
--------------
``_by_hash`` 此前**无界增长**:``issue()`` 对同一 device_id 每次都新增一条记录(轮换),
``revoke_device()`` 只把 ``revoked`` 置 True、从不删除,而 ``_persist()`` 每次把全表重写
一遍。于是一台反复重装/换机的设备会永久留下 N 条记录 —— 存储文件单调增长,每次发放的
落盘开销也随总条数线性上升。

这里最要紧的一条不变量
----------------------
**淘汰只能动已吊销的记录,永不能动未吊销的。** 删掉一条还在用的记录等于悄悄把那台设备
踢下线,而且症状是"设备突然连不上、日志里什么都没有" —— 比存储增长严重得多。所以本文件
花最多篇幅在这一条上:活跃凭证在保留期清理、超上限收敛、以及"活跃记录本身就超上限"三种
情形下都必须依然可用。
"""

from __future__ import annotations

import time

import pytest

from core.device_token_registry import DeviceTokenRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """每个用例一个独立存储文件,避免用例间互相看到对方的记录。"""
    monkeypatch.setenv("GALAXY_DEVICE_TOKEN_STORE", str(tmp_path / "device_tokens.json"))
    monkeypatch.delenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", raising=False)
    return DeviceTokenRegistry()


class TestRetentionOfRevokedRecords:
    def test_revoked_records_are_kept_within_the_retention_window(self, registry):
        """保留期内不清 —— 已吊销记录的价值就是审计:``list_devices`` 要能显示
        "这台设备的凭证曾在什么时候被吊销"。"""
        for i in range(5):
            registry.issue("dev-1", name=f"phone-try-{i}")
            registry.revoke_device("dev-1")
        assert len(registry._by_hash) == 5
        assert all(d["revoked"] for d in registry.list_devices())

    def test_revoked_records_are_purged_once_the_window_passes(self, registry, monkeypatch):
        registry.issue("dev-1")
        registry.revoke_device("dev-1")
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "0")
        assert registry.prune() == 1
        assert len(registry._by_hash) == 0

    def test_retention_is_measured_from_revocation_not_issuance(self, registry, monkeypatch):
        """按吊销时刻计时:一条发放很久、刚刚才被吊销的记录,不该立刻消失 ——
        刚吊销的那条恰恰是审计最想看到的。"""
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "1")
        registry.issue("dev-old")
        for rec in registry._by_hash.values():
            rec["issued_at"] = time.time() - 90 * 86400  # 90 天前发放
        registry.revoke_device("dev-old")  # 但是刚刚才吊销
        assert registry.prune() == 0
        assert len(registry._by_hash) == 1

    def test_missing_revoked_at_falls_back_to_issued_at(self, registry, monkeypatch):
        """手改过存储/老版本数据可能缺 revoked_at。不能因为字段缺失就永远清不掉,
        也不能因此把记录误判成"刚吊销"而永久堆积。"""
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "1")
        registry.issue("dev-legacy")
        for rec in registry._by_hash.values():
            rec["revoked"] = True
            rec["revoked_at"] = None
            rec["issued_at"] = time.time() - 90 * 86400
        assert registry.prune() == 1


class TestLiveCredentialsAreNeverEvicted:
    """这一组是最重要的:淘汰逻辑绝不能让一台在用的设备突然掉线。"""

    def test_retention_purge_leaves_live_tokens_usable(self, registry, monkeypatch):
        live = registry.issue("dev-live", name="in use")
        registry.issue("dev-gone")
        registry.revoke_device("dev-gone")

        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "0")
        registry.prune()

        assert registry.verify(live) is not None, "在用凭证被清掉了 —— 设备会突然掉线"

    def test_cap_evicts_revoked_records_only(self, registry, monkeypatch):
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", "3")
        live = registry.issue("dev-live")
        for i in range(5):
            registry.issue(f"dev-old-{i}")
            registry.revoke_device(f"dev-old-{i}")

        assert registry.verify(live) is not None
        assert len(registry._by_hash) <= 3

    def test_live_records_beyond_the_cap_are_kept_and_warned_about(self, registry, monkeypatch, caplog):
        """活跃记录本身就超上限时:一条都不能删,而且必须**看得见** ——
        静默地把存储涨下去、或者静默删一条 working 凭证,两种都不可接受。"""
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", "3")
        with caplog.at_level("WARNING"):
            tokens = [registry.issue(f"dev-live-{i}") for i in range(5)]

        assert len(registry._by_hash) == 5, "未吊销记录一条都不能被淘汰"
        assert all(registry.verify(t) is not None for t in tokens)
        assert "不会自动淘汰在用凭证" in caplog.text

    def test_oldest_revoked_are_evicted_first(self, registry, monkeypatch):
        """超上限时先淘汰最老的已吊销记录,保留较近的(审计价值随时间衰减)。"""
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", "2")
        for i in range(4):
            registry.issue(f"dev-{i}")
            registry.revoke_device(f"dev-{i}")
            for rec in registry._by_hash.values():
                if rec["device_id"] == f"dev-{i}":
                    rec["revoked_at"] = 1000.0 + i  # 递增:i 越大越新

        remaining = {r["device_id"] for r in registry.list_devices()}
        assert len(remaining) <= 2
        assert "dev-0" not in remaining, "最老的应先被淘汰"


class TestPruningIsWiredIn:
    def test_issue_prunes_so_growth_is_bounded(self, registry, monkeypatch):
        """发放是唯一的增长点,清理必须挂在那里 —— 否则要等到有人显式调 prune()
        才收敛,而生产上没人会去调。"""
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "0")
        for i in range(20):
            registry.issue("dev-reinstall", name=f"try-{i}")
            registry.revoke_device("dev-reinstall")
        # 每轮发放时都会清掉上一轮那条刚吊销的记录(保留期 0)
        assert len(registry._by_hash) <= 2, f"发放路径没有收敛,现有 {len(registry._by_hash)} 条"

    def test_load_prunes_on_restart(self, tmp_path, monkeypatch):
        """进程重启是清理的自然时机;不该非得等到下一次发放。"""
        store = tmp_path / "device_tokens.json"
        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_STORE", str(store))
        monkeypatch.delenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", raising=False)

        first = DeviceTokenRegistry()
        first.issue("dev-1")
        first.revoke_device("dev-1")
        assert len(first._by_hash) == 1

        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", "0")
        reloaded = DeviceTokenRegistry()  # 重新从磁盘加载
        assert len(reloaded._by_hash) == 0


class TestConfigParsing:
    @pytest.mark.parametrize("bad", ["abc", "", "  "])
    def test_bad_retention_value_falls_back_to_default(self, monkeypatch, bad):
        from core.device_token_registry import _DEFAULT_RETENTION_DAYS, _retention_seconds

        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_RETENTION_DAYS", bad)
        assert _retention_seconds() == pytest.approx(_DEFAULT_RETENTION_DAYS * 86400.0)

    @pytest.mark.parametrize("bad", ["abc", "", "  "])
    def test_bad_cap_value_falls_back_to_default(self, monkeypatch, bad):
        from core.device_token_registry import _DEFAULT_MAX_RECORDS, _max_records

        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", bad)
        assert _max_records() == _DEFAULT_MAX_RECORDS

    def test_cap_of_zero_is_clamped_to_one(self, monkeypatch):
        """上限 0 会让每次发放都立刻自我淘汰 —— 收敛到 1,不接受"发了就没了"。"""
        from core.device_token_registry import _max_records

        monkeypatch.setenv("GALAXY_DEVICE_TOKEN_MAX_RECORDS", "0")
        assert _max_records() == 1
