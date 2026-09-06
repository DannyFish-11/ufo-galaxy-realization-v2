"""在设置页填完保存,**该生效的必须当场生效** —— 不能要重启,更不能不说。

## 这道门挡的是什么

保存配置那一步会决定要不要热刷新路由器。以前的判据是 ``category == "llm"``。

分类是给**人看的**:设置页按"人想干什么"分九类,"这个键属于哪一档"和"这个键
会不会影响 provider 注册"是两个不同的问题,而这里问了错的那一个。漏掉的是一整类
真事:

* ``OLLAMA_URL``            —— 本机 Ollama 的地址,分类 agent
* ``GALAXY_LOCAL_OPENAI_URL``     —— 本地推理服务,分类 agent
* ``GALAXY_REASONING_OPENAI_URL`` —— 推理位那台,分类 agent

三个都是 ``_auto_discover_providers()`` **注册时才读**的键。在面板上填好、保存
成功、值也落了盘,而路由器根本不会重新注册这一家 —— 要重启进程才生效,面板
一个字都不说。最刺眼的是同一家 Ollama 自己跟自己不一致:改型号
(``OLLAMA_MODEL``,llm 类)会刷新,改地址(``OLLAMA_URL``,agent 类)不会。

现在判据换成"这个键会不会影响注册",名单在
``core.multi_llm_router.keys_that_change_registration()``,而且**大部分是从
PROVIDER_REGISTRY 推导的** —— 新加一家厂商不必回来改名单。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """真起一个 app 打真接口 —— 判据是"保存之后有没有安排刷新",不是源码里写了什么。

    **这个 fixture 必须把三样东西全部隔离掉**,一样漏了都会污染开发机:

    * ``ENV_FILE``   保存接口真的会写仓库根目录的 ``.env``。它的路径是按模块位置
      算的,``monkeypatch.chdir`` 挡不住 —— 第一版就是这么漏的,跑完之后仓库根多
      出一个 27KB 的 ``.env``,把 ``GALAXY_ENABLE_VOICE_DUPLEX`` 之类的默认值全顶
      掉了,于是**另一个测试文件单独跑也开始红**,而红的原因跟它自己毫无关系。
    * ``runtime/secrets.env``  密钥走的是另一条路(ConfigService.set_secret)。
    * ``os.environ``  保存成功后会 ``os.environ.update()``,进程内立刻生效。

    三样都还原,这个文件才只证明它想证明的那件事。
    """
    import os

    from core.routes import config as route

    monkeypatch.setattr(route, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(
        route,
        "_write_env_file_with",
        lambda overrides=None, exclude=None: (tmp_path / ".env").write_text("", encoding="utf-8"),
    )

    class _NoOpSecrets:
        def set_secret(self, key, value):  # noqa: D102
            (tmp_path / "secrets.env").write_text(f"{key}=stored\n", encoding="utf-8")

        def delete_secret(self, key):  # noqa: D102
            pass

    import core.config_service as cs

    monkeypatch.setattr(cs, "ConfigService", lambda *a, **k: _NoOpSecrets())

    before = dict(os.environ)
    app = FastAPI()
    app.include_router(route.router)  # router 自带 /api/config 前缀
    try:
        with TestClient(app) as c:
            yield c
    finally:
        os.environ.clear()
        os.environ.update(before)


def _save(client, key: str, value: str) -> dict:
    r = client.post("/api/config", json={"config": {key: value}})
    assert r.status_code == 200, r.text
    return r.json()


class TestTheKeysThatChangeRegistrationAllTriggerARefresh:
    @pytest.mark.parametrize(
        "key,value",
        [
            ("OLLAMA_URL", "http://127.0.0.1:11434"),
            ("GALAXY_LOCAL_OPENAI_URL", "http://127.0.0.1:8080/v1"),
            ("GALAXY_REASONING_OPENAI_URL", "http://127.0.0.1:1919/v1"),
            ("GALAXY_LOCAL_OPENAI_MODEL", "some-model"),
            ("OPENAI_API_KEY", "sk-x"),
            ("META_API_KEY", "sk-x"),
            ("ONEAPI_URL", "http://127.0.0.1:3000"),
        ],
    )
    def test_it_schedules_a_refresh(self, client, key, value):
        body = _save(client, key, value)
        assert body["router_refreshed"] == "scheduled", (
            f"改了「{key}」却没安排刷新 —— 用户填完保存成功,路由器却还用着旧的," "要重启才生效,而面板不会告诉他这件事"
        )

    def test_a_setting_that_cannot_affect_registration_does_not_refresh(self, client):
        """反面保险:不能靠"一律刷新"通过上面那批。

        刷新会做真实网络探测,每次保存都刷等于把设置页拖慢,而且大多数键根本
        与 provider 注册无关。
        """
        body = _save(client, "GALAXY_CU_MAX_STEPS", "12")
        assert body["router_refreshed"] is None, "与注册无关的键也触发了刷新"


class TestTheListIsDerivedNotHandMaintained:
    def test_every_vendor_key_in_the_registry_is_covered_automatically(self):
        """新加一家厂商不该还要回来改一份名单 —— 那份名单迟早会漏。"""
        from core.multi_llm_router import keys_that_change_registration
        from core.provider_registry import PROVIDER_REGISTRY

        covered = keys_that_change_registration()
        missing = []
        for entry in PROVIDER_REGISTRY:
            for field in ("env_key", "base_env"):
                if entry.get(field) and entry[field] not in covered:
                    missing.append(entry[field])
            missing += [a for a in (entry.get("alt_env") or ()) if a not in covered]
        assert not missing, f"这些厂商键不会触发刷新:{missing}"

    def test_the_special_branches_are_covered_too(self):
        """推导不出来的那几支(本机 Ollama / 本地 OpenAI / OneAPI / HF)要显式列。"""
        from core.multi_llm_router import keys_that_change_registration

        covered = keys_that_change_registration()
        for key in (
            "OLLAMA_URL",
            "OLLAMA_MODEL",
            "ONEAPI_URL",
            "GALAXY_LOCAL_OPENAI_URL",
            "GALAXY_REASONING_OPENAI_URL",
            "HF_API_TOKEN",
        ):
            assert key in covered, f"{key} 会改变注册结果,却不在名单里"

    def test_the_list_does_not_swallow_unrelated_keys(self):
        """名单越长,保存配置时被无谓触发的刷新越多。"""
        from core.multi_llm_router import keys_that_change_registration

        covered = keys_that_change_registration()
        for key in ("GALAXY_AUTONOMY", "GALAXY_CU_MAX_STEPS", "GALAXY_MEMORY_BACKENDS"):
            assert key not in covered


class TestVendorSettingsLiveWithTheVendorKeys:
    def test_the_responses_switch_sits_in_the_supplier_section(self):
        """「让这几家走 Responses 接口」说的是厂商的事,该和密钥在同一档里。

        它上一版放在 agent 类 —— 用户要在"智能体与模型"里找一个纯粹的厂商设置,
        而"供应商与密钥"就在旁边。
        """
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert CONFIG_SCHEMA["GALAXY_RESPONSES_PROVIDERS"]["category"] == "llm"

    def test_every_vendor_env_key_is_in_the_supplier_section(self):
        """18 家的密钥必须都在那一档里,一个不漏 —— 否则用户得满设置页找。"""
        from core.provider_registry import PROVIDER_REGISTRY
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        llm = {k for k, v in CONFIG_SCHEMA.items() if v.get("category") == "llm"}
        stray = [e["env_key"] for e in PROVIDER_REGISTRY if e.get("env_key") and e["env_key"] not in llm]
        assert not stray, f"这些厂商密钥不在「供应商与密钥」那一档:{stray}"
