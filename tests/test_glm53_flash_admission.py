"""GLM-5.3-Flash 落进仓库这件事,以及它牵动的三道闸。

为什么单独一个文件
------------------
这次改的不只是"型号清单里多一行"。GLM-5.3-Flash 同时踩到四处判据:

1. **型号与端点必须对得上**——本仓已经因为这件事踩过两次:``minimax-m2.7`` 大小写
   写错(registry 里没有那个拼写)→ 选路成功、请求 404;``glm-5.3`` 曾经只在编码
   套餐端点上,塞进通用端点条目会 404。两次的形状一样:**看起来接上了,其实没有**。
2. **海外端点是另一个域名**。``api.z.ai`` 与 ``open.bigmodel.cn`` 同构,型号名、
   OpenAI 兼容协议、Bearer 鉴权全一致,只有域名不同。
3. 于是它撞上 ``core.endpoint_admission``:换地址必须留痕。
4. 也撞上 ``core.egress_guard``:enforce 档下,官方海外域名不在白名单里的话,
   一次完全正当的调用会被自己的闸打死。

第 3 与第 4 条的取舍写在下面 ``TestOverrideIsRecordedNotBlessed`` 里 —— 那是这个
文件里最容易被读反的一处。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.multi_llm_router import PROVIDER_MODEL_MAP, PROVIDER_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = {spec["name"]: spec for spec in PROVIDER_REGISTRY}

#: 国内通用端点。glm-5.3 / glm-5.3-flash 都在这上面(2026-08-19 / 08-26 上线)。
GENERAL_BASE = "https://open.bigmodel.cn/api/paas/v4"
#: 海外同构端点。**不是**另一家 provider,只是同一家的另一个域名。
INTL_BASE = "https://api.z.ai/api/paas/v4"
#: 编码套餐专属端点。订阅制计费,与上面两条是不同的售卖路径。
CODING_BASE = "https://open.bigmodel.cn/api/coding/paas/v4"


def _lists(entries, item: str) -> bool:
    """``item`` 是不是 ``entries`` 里的一个**完整成员**。

    不写 ``item in entries``:CodeQL 的 "Incomplete URL substring sanitization"
    会把对着 URL/主机名的 ``in`` 一律当成子串净化来报,它分不清元组成员判断和
    字符串包含。这里要的本来就是精确相等,写明白既让告警消失,也让人不用猜。
    """
    return any(entry == item for entry in entries)


# ══════════════════════════════════════════════════════════════════════════
# A. 型号真的登记在了对的端点上
# ══════════════════════════════════════════════════════════════════════════


class TestGlm53OnTheGeneralEndpoint:
    """通用端点条目现在认 glm-5.3 与 glm-5.3-flash 两个型号。"""

    def test_flash_is_declared(self):
        assert _lists(_REGISTRY["zhipu"]["models"], "glm-5.3-flash")

    def test_flagship_is_declared(self):
        assert _lists(_REGISTRY["zhipu"]["models"], "glm-5.3")

    def test_the_entry_still_points_at_the_general_endpoint(self):
        """整条改动的成立前提就是这一句 —— 型号在通用端点上。条目本身要是指到了
        别处,上面两条"已登记"就成了假的。"""
        assert _REGISTRY["zhipu"]["base_url"] == GENERAL_BASE

    def test_flagship_became_the_default(self):
        """与 moonshot/qwen/minimax 同一个惯例:默认 = 该家当前旗舰。

        默认停在 glm-5.2 而清单里已经有 5.3,会让"这份表是不是新的"没法从一处看出来。
        """
        assert _REGISTRY["zhipu"]["default_model"] == "glm-5.3"

    def test_fast_tier_points_at_flash(self):
        per_task = {getattr(tt, "value", tt): m for tt, m in PROVIDER_MODEL_MAP["zhipu"].items()}
        assert per_task["fast_response"] == "glm-5.3-flash"

    def test_heavy_tier_points_at_the_flagship(self):
        per_task = {getattr(tt, "value", tt): m for tt, m in PROVIDER_MODEL_MAP["zhipu"].items()}
        assert per_task["reasoning"] == "glm-5.3"
        assert per_task["coding"] == "glm-5.3"

    def test_no_stale_5_2_slot_left_behind(self):
        """升级最常见的漏法是"清单升了、任务表忘了",表现是新型号加了却没人用。"""
        assert "glm-5.2" not in set(PROVIDER_MODEL_MAP["zhipu"].values())

    def test_the_old_flash_model_is_kept_not_purged(self):
        """glm-5.1-flash 没有被官方下线,只是不再是本仓的快档首选 —— 留在 models
        里作为该家自己的旧档回退,与 grok-4.5 同一个处理(不是 opus-4.8 那种
        "已作废,不该残留")。"""
        assert _lists(_REGISTRY["zhipu"]["models"], "glm-5.1-flash")


class TestCodingPlanIsStillADifferentThing:
    """通用端点认了 5.3 之后,最容易做错的下一步是"那 zhipu_coding 可以删了"。

    不能删:它是**同一款模型的另一条售卖路径**。base_url 不同(专属端点)、计费方式
    不同(订阅制月费,不是按 token)、使用范围不同(官方限定编码 agent 场景)。
    两条都留着,不是重复登记。
    """

    def test_it_still_exists(self):
        assert "zhipu_coding" in _REGISTRY

    def test_it_still_has_its_own_endpoint(self):
        assert _REGISTRY["zhipu_coding"]["base_url"] == CODING_BASE
        assert _REGISTRY["zhipu_coding"]["base_url"] != _REGISTRY["zhipu"]["base_url"]

    def test_it_also_serves_flash(self):
        assert _lists(_REGISTRY["zhipu_coding"]["models"], "glm-5.3-flash")

    def test_the_two_entries_do_not_share_a_key(self):
        """共用 env 名会让"配了聊天 key"静默等于"接了编码套餐订阅"。"""
        assert _REGISTRY["zhipu_coding"]["env_key"] != _REGISTRY["zhipu"]["env_key"]


# ══════════════════════════════════════════════════════════════════════════
# B. 海外端点:一条真的能用的路,而不是一句注释
# ══════════════════════════════════════════════════════════════════════════


class TestInternationalEndpointIsWiredEndToEnd:
    """把海外地址写进注释很容易,写进注释也**没有任何用** —— 用户改不了它。

    这一组钉的是"这条路每一段都通":registry 声明 → 短键映射 → 配置项登记 →
    明文回显 → 面板有输入框。断掉任何一段,表现都是"设了没反应",而这正是本仓
    OPENAI_API_BASE 早年踩过的那个坑(面板存了,重启后读不回来)。
    """

    def test_registry_declares_the_override_hooks(self):
        spec = _REGISTRY["zhipu"]
        assert spec.get("base_env") == "ZHIPU_API_BASE"
        assert spec.get("base_key") == "zhipu_base"

    def test_short_key_maps_to_the_same_env_name_in_the_router(self):
        from core.multi_llm_router import _PROVIDER_ENV_KEY_MAP

        assert _PROVIDER_ENV_KEY_MAP["zhipu_base"] == _REGISTRY["zhipu"]["base_env"]

    def test_the_credential_vault_agrees_with_the_router(self):
        """两处分别维护同一份短键→env 名映射(历史包袱,见 credential_vault 注释)。
        改一处忘另一处,Vault 这层就静默查不到值。"""
        from core.credential_vault import _ENV_MAPPING
        from core.multi_llm_router import _PROVIDER_ENV_KEY_MAP

        assert _ENV_MAPPING["zhipu_base"] == _PROVIDER_ENV_KEY_MAP["zhipu_base"]

    def test_the_switch_is_registered(self):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert "ZHIPU_API_BASE" in CONFIG_SCHEMA
        assert CONFIG_SCHEMA["ZHIPU_API_BASE"]["type"] == "url"

    def test_it_is_echoed_back_as_plaintext_not_treated_as_a_secret(self):
        """它是**地址**不是密钥。落进密钥那条路的话,面板只会拿到一个
        "已配置 / 未配置"的布尔,用户永远看不见自己填的是什么 —— 于是也没法发现
        自己填错了,或者被别人改过了。"""
        from core.routes.config import _NON_SECRET_MODEL_KEYS

        assert _lists(_NON_SECRET_MODEL_KEYS, "ZHIPU_API_BASE")

    def test_the_panel_offers_the_input(self):
        src = REPO_ROOT / "electron/renderer/panel/src/settings_inventory.ts"
        assert "ZHIPU_API_BASE" in src.read_text(encoding="utf-8")


class TestOverrideIsRecordedNotBlessed:
    """**这个文件里最容易被读反的一处。**

    指到官方海外端点是正当用法,所以出站白名单得认这个主机(否则 enforce 档会把
    正当调用打死)。但"白名单认它"绝不等于"换地址这件事不用留痕"——
    ``endpoint_admission`` 照样把它判成 ``overridden``。

    两道闸回答的是两个问题,合并任何一边都会出事:

    * 白名单跟着运行期覆盖值走 → 谁能设那个环境变量,谁就能给自己的窃取主机盖章;
    * 覆盖到官方备用域名就判 canonical → 报告里看不出地址被人动过。

    所以:**放行,并且如实说它被改了。**
    """

    def test_the_official_alternate_host_is_on_the_egress_allowlist(self):
        from core.egress_guard import allowlist

        assert _lists(allowlist(), "api.z.ai")

    def test_the_home_host_is_too(self):
        from core.egress_guard import allowlist

        assert _lists(allowlist(), "open.bigmodel.cn")

    def test_pointing_at_the_official_alternate_still_reads_as_overridden(self):
        from core.endpoint_admission import evaluate

        decision = evaluate("zhipu", INTL_BASE, source="env")
        assert decision.verdict == "overridden"
        assert decision.is_canonical is False

    def test_the_registered_address_reads_as_canonical(self):
        from core.endpoint_admission import evaluate

        assert evaluate("zhipu", GENERAL_BASE).verdict == "canonical"

    def test_a_lookalike_host_is_not_on_the_allowlist(self):
        """``alt_base_urls`` 只写官方地址。写宽了(比如顺手加个通配)等于把这道闸
        变成摆设 —— 这条盯的就是那种顺手。"""
        from core.egress_guard import allowlist

        entries = allowlist()
        for fake in ("api-z.ai", "z.ai.evil.com", "evil-bigmodel.cn"):
            assert not _lists(entries, fake)

    @pytest.mark.parametrize("mode_env", ["enforce"])
    def test_a_random_host_is_still_refused_under_enforce(self, mode_env, monkeypatch):
        """加了一个主机不能顺带把闸放松掉。"""
        from core import egress_guard as eg

        monkeypatch.setenv("GALAXY_EGRESS_MODE", mode_env)
        assert eg.evaluate("https://totally-unrelated.example.com/x").allowed is False


# ══════════════════════════════════════════════════════════════════════════
# C. alt_base_urls 这个字段本身的约束
# ══════════════════════════════════════════════════════════════════════════


class TestAltBaseUrlsField:
    def test_every_declared_alternate_is_https_and_parses(self):
        """推导白名单时取不出主机名的条目会**静默变成零贡献** —— 那时的表现是
        "白名单里少了一个",没人会想到是这里写错了。"""
        from core.egress_guard import host_of

        for spec in PROVIDER_REGISTRY:
            for url in spec.get("alt_base_urls") or []:
                assert url.startswith("https://"), f"{spec['name']} 的备用地址不是 https: {url!r}"
                assert host_of(url), f"{spec['name']} 的备用地址取不出主机名: {url!r}"

    def test_an_alternate_is_never_the_same_as_the_home_address(self):
        for spec in PROVIDER_REGISTRY:
            home = str(spec.get("base_url", "")).rstrip("/")
            for url in spec.get("alt_base_urls") or []:
                assert url.rstrip("/") != home, f"{spec['name']} 的备用地址与 base_url 重复"

    def test_alternates_do_not_silently_become_the_address_we_call(self):
        """备用地址**不参与选路**。请求永远发往 base_url,或发往被显式覆盖后的地址。

        这条用 registry 自己的声明来钉:``zhipu`` 的 base_url 必须仍是国内那个。
        如果哪天有人把 alt 接进了选路,这一句就会先响。
        """
        assert _REGISTRY["zhipu"]["base_url"] == GENERAL_BASE
        assert _lists(_REGISTRY["zhipu"]["alt_base_urls"], INTL_BASE)
