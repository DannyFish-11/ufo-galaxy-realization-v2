"""面板「模型服务商」目录：每家厂商都有一张卡、每个密钥键都有归属、密钥值一个字都不外露。

被修的问题
----------
旧面板里有一份带中文名的厂商目录（``ModelsTab``），新面板重写时被整个删掉；各家的 API Key 退化成
「全部设置」第 12 段里 35 行裸环境变量名。用户只看得到「我的模型服务」（自定义端点），就以为各家厂商
没法填 —— 后端明明有，面板上却找不到。

这里把「后端有它 ⇒ 面板上有地方填」钉成测试：

* ``PROVIDER_REGISTRY`` 里每一家都有展示信息（中文名、分组）—— 多一家而没人写展示信息，就红；
* 「供应商与密钥」这一类里的每个配置键，要么被某张卡认领，要么明确列为「留在细调页」—— 不允许没人管；
* 卡片认领的键，后端 ``CONFIG_SCHEMA`` 必须认得（否则 ``POST /api/config`` 400）；
* **目录接口不下发密钥**：把一串像样的假密钥放进环境，整份 JSON 里不得出现它（也不得出现它的前缀）。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.provider_catalog import (
    CATALOG_LEFTOVER_KEYS,
    GROUPS,
    build_catalog,
    owned_config_keys,
)
from core.provider_registry import PROVIDER_REGISTRY
from core.routes.config_schema_registry import CONFIG_SCHEMA

FAKE_SECRET = "sk-test-SUPERSECRET-0123456789abcdef"


def _by_id(catalog: dict) -> dict:
    return {v["id"]: v for v in catalog["vendors"]}


class TestEveryVendorHasACard:
    def test_every_registry_vendor_has_a_card(self):
        cards = _by_id(build_catalog({}))
        missing = [e["name"] for e in PROVIDER_REGISTRY if e["name"] not in cards]
        assert not missing, f"这些直连厂商在面板上没有卡片: {missing}"

    def test_every_registry_vendor_has_presentation(self):
        """不写展示信息就会退化成显示英文 id、掉进「聚合与自建」—— 用户找不到它。"""
        from core.provider_catalog import _PRESENTATION

        missing = [e["name"] for e in PROVIDER_REGISTRY if e["name"] not in _PRESENTATION]
        assert not missing, f"这些厂商没有中文名/分组: {missing}"

    def test_every_group_used_is_declared(self):
        declared = {g["id"] for g in GROUPS}
        used = {v["group"] for v in build_catalog({})["vendors"]}
        assert used <= declared, f"卡片用了没声明的分组: {used - declared}"

    def test_card_ids_are_unique(self):
        ids = [v["id"] for v in build_catalog({})["vendors"]]
        assert len(ids) == len(set(ids))


class TestEveryKeyHasAHome:
    def test_every_llm_category_key_is_owned_or_declared_leftover(self):
        """「供应商与密钥」类里的每个键：被卡片认领，或明确留在细调页。"""
        owned = owned_config_keys()
        orphans = sorted(
            k
            for k, meta in CONFIG_SCHEMA.items()
            if meta.get("category") == "llm" and k not in owned and k not in CATALOG_LEFTOVER_KEYS
        )
        assert not orphans, (
            f"这些键既没被任何厂商卡认领、也没列为留在细调页的键: {orphans}。"
            "新加一家厂商就在 core/provider_catalog.py 里写它的展示信息。"
        )

    def test_owned_keys_are_known_to_the_config_endpoint(self):
        unknown = sorted(k for k in owned_config_keys() if k not in CONFIG_SCHEMA)
        assert not unknown, f"卡片认领了后端不认识的键（POST /api/config 会 400）: {unknown}"

    def test_leftovers_are_real_keys(self):
        unknown = sorted(k for k in CATALOG_LEFTOVER_KEYS if k not in CONFIG_SCHEMA)
        assert not unknown, f"留在细调页的键不存在: {unknown}"

    def test_owned_and_leftover_do_not_overlap(self):
        both = owned_config_keys() & CATALOG_LEFTOVER_KEYS
        assert not both, f"同一个键既被认领又被列为留下: {sorted(both)}"

    def test_aliases_are_part_of_the_card(self):
        """GEMINI_API_KEY / DASHSCOPE_API_KEY / SONAR_API_KEY 是别名：填过也认，且「清除」要能找到它。"""
        cards = _by_id(build_catalog({"GEMINI_API_KEY": "FAKE_gemini_key_0123456789"}))
        google = cards["google"]
        assert google["configured"] is True
        assert google["key_state"] == {"GOOGLE_API_KEY": False, "GEMINI_API_KEY": True}


class TestConfiguredIsHonest:
    def test_empty_env_configures_nothing(self):
        assert build_catalog({})["configured_count"] == 0

    def test_a_key_marks_only_its_vendor(self):
        cards = _by_id(build_catalog({"DEEPSEEK_API_KEY": "sk-real-looking-value"}))
        assert cards["deepseek"]["configured"] is True
        assert not any(v["configured"] for k, v in cards.items() if k != "deepseek")

    @pytest.mark.parametrize("placeholder", ["your_openai_key_here", "change_me", "<paste>", "xxx", "sk-YOUR-KEY", ""])
    def test_placeholders_do_not_count_as_configured(self, placeholder):
        assert _by_id(build_catalog({"OPENAI_API_KEY": placeholder}))["openai"]["configured"] is False

    def test_url_only_entries_count_by_their_url(self):
        cards = _by_id(build_catalog({"LOCAL_VLLM_URL": "http://127.0.0.1:8000/v1"}))
        assert cards["vllm"]["configured"] is True
        assert cards["ollama"]["configured"] is False

    def test_coding_plan_is_opt_in_and_the_rest_are_not(self):
        cards = _by_id(build_catalog({}))
        assert cards["zhipu_coding"]["opt_in"] is True
        assert cards["zhipu_coding"]["roles"] == []
        assert cards["openai"]["opt_in"] is False and cards["openai"]["roles"]

    def test_unknown_router_state_is_none_not_false(self):
        """没问到路由器 ≠ 路由器说没有。前者是 None，面板据此不画「在线/离线」。"""
        card = _by_id(build_catalog({}, router=None))["openai"]
        assert card["live"] == {"registered": None, "available": None}


class TestNoSecretEverLeaves:
    def test_catalog_json_never_contains_the_key_value(self):
        env = {e["env_key"]: FAKE_SECRET for e in PROVIDER_REGISTRY}
        env.update({"ONEAPI_API_KEY": FAKE_SECRET, "HF_API_TOKEN": FAKE_SECRET, "NOVITA_API_KEY": FAKE_SECRET})
        dumped = json.dumps(build_catalog(env), ensure_ascii=False)
        assert FAKE_SECRET not in dumped
        assert "SUPERSECRET" not in dumped
        assert "sk-test" not in dumped

    def test_non_secret_urls_are_shown_but_keys_are_only_booleans(self):
        env = {"OPENAI_API_KEY": FAKE_SECRET, "OPENAI_API_BASE": "https://relay.example/v1"}
        card = _by_id(build_catalog(env))["openai"]
        assert card["url_envs"][0]["value"] == "https://relay.example/v1"
        assert card["key_state"] == {"OPENAI_API_KEY": True}
        assert all(isinstance(v, bool) for v in card["key_state"].values())


class TestEndpoint:
    @pytest.fixture()
    def client(self):
        from core.routes import models as models_route

        app = FastAPI()
        app.include_router(models_route.router)
        return TestClient(app)

    def test_endpoint_serves_the_catalog(self, client, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", FAKE_SECRET)
        r = client.get("/api/v1/models/providers")
        assert r.status_code == 200
        body = r.json()
        assert len(body["vendors"]) >= len(PROVIDER_REGISTRY)
        assert FAKE_SECRET not in r.text
        groq = next(v for v in body["vendors"] if v["id"] == "groq")
        assert groq["configured"] is True
        assert "GROQ_API_KEY" in body["owned_keys"]
