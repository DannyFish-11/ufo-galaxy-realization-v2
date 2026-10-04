"""并进整档按钮的子开关:翻按钮时跟着主键一起写,而且判据是写死在清单里的。

``core/routes/config_bundles.py`` 的 ``members`` 说「这个键和主键是同一件事的另一面」。这个文件守:

1. 清单(``panel_switch_policy`` 的 ``member``)与 ``CONFIG_BUNDLES`` 的 ``members`` 互相核对 —— 不会一边说并进来了、
   另一边不知道;
2. 写入语义:主键关 → 成员全写 false;主键开 → 成员回到登记表默认(**不替用户打开 opt-in**);
3. 一次写完(同一次 ``update_config``),不会出现「主键写了、成员没写」的中间态;
4. 「没并」的几个反例确实没并 —— 它们各有一个隐私/花费/暴露面的理由(见模块说明);
5. 成员相对主键偏离时,档位显示「有偏离」,而不是悄悄两处各说各话。
"""

from __future__ import annotations

import asyncio
import os

import pytest

from core.routes import config as cfg
from core.routes.config_bundles import (
    CONFIG_BUNDLES,
    bundle_writes,
    expected_member_value,
    member_keys,
    owned_keys,
)
from core.routes.config_schema_registry import CONFIG_SCHEMA
from core.routes.panel_switch_policy import MEMBER, PANEL, SWITCH_POLICY

# 看着像成员、其实不是 —— 每一个的理由在 config_bundles 模块说明里。
NOT_MEMBERS = (
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION",  # 只要回声消除、不让模型听见自己在放什么:特意拆开的隐私选择
    "GALAXY_VOICE",  # 听 / 朗读 / 本机外放是三个方向
    "GALAXY_SPEAK",
    "GALAXY_LOCAL_AUDIO",
    "GALAXY_NATIVE_AUDIO_CHAT",  # 每轮发不发录音:token 花费决定
    "GALAXY_MASTER_BRAIN_ENABLED",  # 默认关的 opt-in:按钮「开」不能替人打开
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL",
    "FEDERATION_ENABLED",
    "GALAXY_TS_FUNNEL",
    "GALAXY_ACTIVE_PERCEPTION",
    "GALAXY_PROACTIVE_SCREEN",
)


def _bundle(key: str) -> dict:
    return next(b for b in CONFIG_BUNDLES if b["key"] == key)


def _all_members() -> list:
    return [k for b in CONFIG_BUNDLES for k in member_keys(b)]


class TestThePolicyAndTheBundlesAgree:
    def test_every_member_is_a_hidden_boolean_the_policy_calls_a_member(self) -> None:
        for key in _all_members():
            assert CONFIG_SCHEMA[key]["type"] == "boolean", f"{key} 不是布尔,不能并进开关"
            assert (
                SWITCH_POLICY[key].disposition == MEMBER
            ), f"{key} 是某一档的成员,清单里却说它是 {SWITCH_POLICY[key].disposition}"

    def test_every_policy_member_is_claimed_by_exactly_one_bundle(self) -> None:
        claimed = _all_members()
        assert len(claimed) == len(set(claimed)), "同一个键被两档同时认作成员"
        assert sorted(claimed) == sorted(k for k, p in SWITCH_POLICY.items() if p.disposition == MEMBER)

    def test_a_member_is_owned_by_the_bundle_that_claims_it(self) -> None:
        for bundle in CONFIG_BUNDLES:
            owned = set(owned_keys(bundle, CONFIG_SCHEMA.keys()))
            for key in member_keys(bundle):
                assert key in owned, f"{bundle['key']} 的成员 {key} 不在它的 owns 里"
                assert key != bundle["primary"]

    def test_only_a_two_state_bundle_has_members(self) -> None:
        """三档的自主没有「关」,成员的「关 → false」对它没有意思。"""
        for bundle in CONFIG_BUNDLES:
            if member_keys(bundle):
                assert CONFIG_SCHEMA[bundle["primary"]]["type"] == "boolean", bundle["key"]

    @pytest.mark.parametrize("key", NOT_MEMBERS)
    def test_things_that_look_like_members_but_are_not_are_not(self, key: str) -> None:
        assert key not in _all_members()
        assert SWITCH_POLICY[key].disposition != MEMBER

    def test_the_cross_device_family_collapses_into_one_button(self) -> None:
        assert set(member_keys(_bundle("cross_device"))) == {
            "GALAXY_ONBOARDING_ENABLED",
            "GALAXY_LAN_DISCOVERY",
            "GALAXY_MDNS",
            "GALAXY_NATS_ENABLED",
        }
        assert SWITCH_POLICY["GALAXY_CROSS_DEVICE_ENABLED"].disposition == PANEL, "主键本身不隐藏"


class TestWhatFlippingTheButtonWrites:
    def test_off_writes_false_to_the_primary_and_every_member(self) -> None:
        bundle = _bundle("cross_device")
        writes = bundle_writes(bundle, "false", CONFIG_SCHEMA)
        assert writes == {k: "false" for k in (bundle["primary"], *member_keys(bundle))}

    def test_on_returns_members_to_their_registry_default_and_never_opts_anyone_in(self) -> None:
        for bundle in CONFIG_BUNDLES:
            writes = bundle_writes(bundle, "true", CONFIG_SCHEMA)
            assert writes[bundle["primary"]] == "true"
            for key in member_keys(bundle):
                assert writes[key] == CONFIG_SCHEMA[key]["default"], key

    def test_a_three_state_primary_writes_only_itself(self) -> None:
        auto = _bundle("autonomy")
        assert bundle_writes(auto, "autonomous", CONFIG_SCHEMA) == {"GALAXY_AUTONOMY": "autonomous"}

    def test_the_expected_value_has_one_definition(self) -> None:
        assert expected_member_value("false", "true") == "false"
        assert expected_member_value("true", "true") == "true"
        assert expected_member_value("true", "false") == "false", "opt-in 成员:按钮开了它也还是默认关"


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """``update_config`` 直接写 ``os.environ``(当次即时生效),所以这里必须整个还原 ——
    只靠 ``monkeypatch.delenv`` 不够:键本来不在环境里时它什么都不记,写进去的值就会一直留着,
    把同一个进程里后面的测试(比如设备接入平面认 ``GALAXY_ONBOARDING_ENABLED``)带红。"""
    saved = dict(os.environ)
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    for bundle in CONFIG_BUNDLES:
        # 整个 owns 都清掉:别的测试/conftest 留在环境里的键会被数成「手改过」。
        for key in owned_keys(bundle, CONFIG_SCHEMA.keys()):
            os.environ.pop(key, None)
    yield tmp_path / ".env"
    os.environ.clear()
    os.environ.update(saved)


class TestTheEndpointWritesThemTogether:
    def test_turning_cross_device_off_turns_its_family_off_in_one_write(self, isolated_env, monkeypatch) -> None:
        state = asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value="false")))["bundle"]
        for key in (
            "GALAXY_CROSS_DEVICE_ENABLED",
            "GALAXY_ONBOARDING_ENABLED",
            "GALAXY_LAN_DISCOVERY",
            "GALAXY_MDNS",
            "GALAXY_NATS_ENABLED",
        ):
            assert os.environ[key] == "false", key
        written = isolated_env.read_text(encoding="utf-8")
        assert "GALAXY_NATS_ENABLED=false" in written and "GALAXY_MDNS=false" in written
        assert state["value"] == "false"
        assert state["overrides"] == 0, "按钮自己写的不算「手改过」"

    def test_turning_it_back_on_restores_defaults_without_enabling_opt_ins(self, isolated_env) -> None:
        asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value="false")))
        state = asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value="true")))["bundle"]
        assert os.environ["GALAXY_CROSS_DEVICE_ENABLED"] == "true"
        assert os.environ["GALAXY_NATS_ENABLED"] == "true"
        assert os.environ["GALAXY_LAN_DISCOVERY"] == "true"
        assert "GALAXY_MASTER_BRAIN_ENABLED" not in os.environ, "主脑是 opt-in,按钮不碰"
        assert "FEDERATION_ENABLED" not in os.environ
        assert state["overrides"] == 0

    def test_the_omnimodal_button_carries_the_ambient_session_preference(self, isolated_env) -> None:
        asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="omnimodal", value="false")))
        assert os.environ["GALAXY_AMBIENT_LOOP"] == "false"
        assert os.environ["GALAXY_AMBIENT_SHARE_SESSION"] == "false"
        asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="omnimodal", value="true")))
        assert os.environ["GALAXY_AMBIENT_SHARE_SESSION"] == "true"

    def test_a_member_hand_edited_against_the_primary_shows_up_as_a_deviation(self, isolated_env, monkeypatch) -> None:
        asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value="false")))
        monkeypatch.setenv("GALAXY_MDNS", "true")  # 绕过面板:主键关着,它却开着
        assert _bundle_overrides("cross_device") == 1
        asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value="true")))
        monkeypatch.setenv("GALAXY_MDNS", "false")  # 主键开着,它却被手改成关
        assert _bundle_overrides("cross_device") == 1


def _bundle_overrides(key: str) -> int:
    return cfg._bundle_state(_bundle(key))["overrides"]
