"""「我的模型服务」：不改仓库加一家，而且必须自己证明它能用。

## 这一整套要挡的是什么

在它之前，加一家模型厂商只有改 ``core/provider_registry.py`` 一条路 —— 每加一个
端点都要动仓库、跑 CI、再发一次版。唯一的例外是 OneAPI，而它被钉死成"只能有一个"。

但"能加"只是一半。另一半是**加完之后你怎么知道它真的能用**。这个仓库反复栽的
就是这一类：注册成功、选路成功、面板显示绿色，一直到真发请求那一刻才失败。所以
这里所有断言都对着**一个真的 OpenAI 兼容网关**跑，不打桩：打桩能证明代码按我
以为的方式执行，证明不了它接的东西真的会答。

## 三种状态是三件事，不准抹平

* ``live``       两步都过，型号表来自网关本身
* ``declared``   网关不开放 /models（有意的也常见），但用户自己列了型号且试调过
* ``unverified`` 没过，并且 state_reason 说明**卡在哪一步**
"""

from __future__ import annotations

import socket
import tempfile
import threading
from pathlib import Path
from typing import Iterator

import pytest
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

GOOD_KEY = "sk-correct-key"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _build_gateway(*, expose_models: bool) -> FastAPI:
    """一个真的 OpenAI 兼容网关。

    ``expose_models=False`` 复现一类真实存在的网关：有意不开放 /models，
    但 /chat/completions 完全正常。那种网关必须能用「自己列型号」这条路接上。
    """
    app = FastAPI()

    def _check(auth: str) -> None:
        if auth != f"Bearer {GOOD_KEY}":
            raise HTTPException(status_code=401, detail="bad key")

    if expose_models:

        @app.get("/v1/models")
        def models(authorization: str = Header(default="")):  # noqa: ANN202
            _check(authorization)
            return {"data": [{"id": "gw-fast"}, {"id": "gw-smart"}]}

    @app.post("/v1/chat/completions")
    def chat(body: dict, authorization: str = Header(default="")):  # noqa: ANN202
        _check(authorization)
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    return app


class _Gateway:
    def __init__(self, expose_models: bool = True) -> None:
        self.port = _free_port()
        cfg = uvicorn.Config(
            _build_gateway(expose_models=expose_models), host="127.0.0.1", port=self.port, log_level="error"
        )
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def __enter__(self) -> "_Gateway":
        self.thread.start()
        import time

        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("测试网关没起来")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture()
def store(monkeypatch) -> Iterator[None]:
    """把存储指到临时目录 —— 绝不碰开发机上真的 runtime/user_providers.json。"""
    import core.user_providers as up

    monkeypatch.setattr(up, "STORE_FILE", Path(tempfile.mkdtemp()) / "user_providers.json")
    yield


@pytest.fixture()
def client(store) -> Iterator[TestClient]:
    from core.routes import user_providers as route

    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as c:
        yield c


class TestTheNameCannotShadowABuiltInVendor:
    """一个叫 openai 的用户条目会把真 OpenAI 顶掉。

    那不只是"覆盖了一个配置"——密钥和每一次对话的全文会照常发去新地址，而且
    一切看起来都正常工作。这正是 core/endpoint_admission.py 开头警告的那条路。
    """

    @pytest.mark.parametrize("taken", ["openai", "anthropic", "deepseek", "oneapi", "ollama"])
    def test_reserved_names_are_refused(self, client, taken):
        r = client.post("/api/v1/providers/user", json={"id": taken, "base_url": "https://x.example.com/v1"})
        assert r.status_code == 400, f"「{taken}」被收下了 —— 它会顶掉一个内置提供商"

    @pytest.mark.parametrize("bad", ["Bad Name", "../etc", "a" * 40, "", "has/slash"])
    def test_malformed_ids_are_refused(self, bad, store):
        from core.user_providers import ProviderIdRejected, validate_id

        with pytest.raises(ProviderIdRejected):
            validate_id(bad)

    def test_uppercase_is_normalised_and_still_findable_by_either_spelling(self, client):
        """大写会被归一成小写 —— 那就必须**两种写法都能找回来**。

        这条是上面那批参数化里长出来的:``UPPER`` 本来被写在"应当拒绝"那一列,
        实际却通过了,因为 validate_id 会静默转小写。转小写本身没问题(id 是个
        技术标识符,显示名在 label 里),真正的问题是**查找那一侧照原样匹配** ——
        用 MyGW 建的端点,面板按同一个名字点删除会 404,像是它鬼上身。
        """
        created = client.post(
            "/api/v1/providers/user", json={"id": "MyGW", "base_url": "https://x.example.com/v1"}
        ).json()
        assert created["id"] == "mygw"

        assert client.post("/api/v1/providers/user/MyGW/verify").status_code == 200, "按原大小写验证时找不到它"
        assert client.delete("/api/v1/providers/user/MyGW").status_code == 200, "按原大小写删除时找不到它"
        assert client.get("/api/v1/providers/user").json()["providers"] == []

    def test_a_normal_name_is_accepted(self, client):
        r = client.post("/api/v1/providers/user", json={"id": "my-gw", "base_url": "https://x.example.com/v1"})
        assert r.status_code == 200, "正常名字被误伤了 —— 上面那些拒绝可能是因为整条路都拒"


class TestVerificationTellsTheTruthAboutARealGateway:
    def test_wrong_key_is_unverified_and_says_which_step(self, client):
        with _Gateway() as gw:
            client.post(
                "/api/v1/providers/user",
                json={"id": "gw", "base_url": gw.base_url, "api_key": "sk-WRONG"},
            )
            body = client.post("/api/v1/providers/user/gw/verify").json()

        assert body["state"] == "unverified"
        assert "401" in body["state_reason"], f"没说清卡在哪一步：{body['state_reason']!r}"
        assert not body["models"], "没验过却报出了型号 —— 那些型号是哪来的？"

    def test_right_key_goes_live_with_the_gateways_own_models(self, client):
        with _Gateway() as gw:
            client.post(
                "/api/v1/providers/user",
                json={"id": "gw", "base_url": gw.base_url, "api_key": GOOD_KEY},
            )
            body = client.post("/api/v1/providers/user/gw/verify").json()

        assert body["state"] == "live"
        assert body["models"] == ["gw-fast", "gw-smart"], "型号表不是网关给的那份"
        assert body["state_reason"] == ""

    def test_a_gateway_without_models_endpoint_still_works_if_you_list_them(self, client):
        """有意不开放 /models 的网关：自己列型号那条路必须走得通，且状态是 declared 不是 live。"""
        with _Gateway(expose_models=False) as gw:
            client.post(
                "/api/v1/providers/user",
                json={
                    "id": "gw",
                    "base_url": gw.base_url,
                    "api_key": GOOD_KEY,
                    "models": ["hand-listed-model"],
                },
            )
            body = client.post("/api/v1/providers/user/gw/verify").json()

        assert body["state"] == "declared", (
            f"状态是 {body['state']!r}。「型号是网关自己报的」与「型号是人手填的」"
            "是两件事，抹平了就没人知道这份清单可不可信。"
        )
        assert body["models"] == ["hand-listed-model"]

    def test_listing_is_not_enough_the_probe_must_also_pass(self, client):
        """只列不试是不够的 —— 一堆网关的 /models 是静态清单，Key 过期照样列得出来。

        这里让 /models 通、/chat/completions 不通，断言结论必须是没过。
        """
        app = FastAPI()

        @app.get("/v1/models")
        def models():  # noqa: ANN202
            return {"data": [{"id": "listed-but-dead"}]}

        @app.post("/v1/chat/completions")
        def chat(body: dict):  # noqa: ANN202
            raise HTTPException(status_code=503, detail="upstream down")

        port = _free_port()
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(cfg)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        import time

        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        try:
            client.post("/api/v1/providers/user", json={"id": "gw", "base_url": f"http://127.0.0.1:{port}/v1"})
            body = client.post("/api/v1/providers/user/gw/verify").json()
        finally:
            server.should_exit = True
            t.join(timeout=5)

        assert body["state"] == "unverified", "列得出型号就判通过 —— 那只证明它会列，没证明它会答"
        assert "503" in body["state_reason"]


class TestTheKeyNeverComesBackOut:
    def test_response_carries_no_key_and_no_length(self, client):
        r = client.post(
            "/api/v1/providers/user",
            json={"id": "gw", "base_url": "https://x.example.com/v1", "api_key": "sk-super-secret-value"},
        ).json()
        blob = repr(r)
        assert "api_key" not in r, "响应里带了 api_key 字段"
        assert "sk-super-secret-value" not in blob, "密钥被回显了"
        assert r["has_key"] is True, "「填过没有」要表达得出来，否则用户没法判断自己存没存上"

    def test_deleting_a_provider_also_drops_its_key(self, client):
        from core.user_providers import api_key_for

        client.post(
            "/api/v1/providers/user",
            json={"id": "gw", "base_url": "https://x.example.com/v1", "api_key": "sk-to-be-deleted"},
        )
        assert api_key_for("gw")
        client.delete("/api/v1/providers/user/gw")
        assert not api_key_for("gw"), "端点删了，密钥还留在 vault 里"


class TestOnlyVerifiedEndpointsGetToRoute:
    def test_an_unverified_endpoint_stays_out_of_the_candidate_pool(self, client):
        from core.user_providers import routable_providers

        client.post("/api/v1/providers/user", json={"id": "gw", "base_url": "https://x.example.com/v1"})
        assert [p.id for p in routable_providers()] == [], (
            "没验过的端点进了候选池 —— 选中它，失败会推迟到真发请求那一刻，" "而用户看到的只是「它怎么不回话」。"
        )

    def test_changing_the_address_invalidates_the_previous_verdict(self, client):
        """地址或 Key 改了，上一次的「已验证」就不再作数。

        让它继续显示 live 是最坏的一种谎：绿灯指的是另一个地址。
        """
        with _Gateway() as gw:
            client.post(
                "/api/v1/providers/user",
                json={"id": "gw", "base_url": gw.base_url, "api_key": GOOD_KEY},
            )
            assert client.post("/api/v1/providers/user/gw/verify").json()["state"] == "live"
            moved = client.post(
                "/api/v1/providers/user",
                json={"id": "gw", "base_url": "https://somewhere-else.example.com/v1"},
            ).json()

        assert moved["state"] == "unverified", "地址换了，状态还留在 live"
        assert not moved["models"], "地址换了，型号表还是旧地址那份"

    def test_a_verified_endpoint_actually_reaches_the_router(self, client, monkeypatch):
        """端到端最后一环：验过之后，路由器真的把它当成一个可选提供商。"""
        with _Gateway() as gw:
            client.post(
                "/api/v1/providers/user",
                json={"id": "gw", "base_url": gw.base_url, "api_key": GOOD_KEY},
            )
            client.post("/api/v1/providers/user/gw/verify")

            from core.multi_llm_router import MultiLLMRouter

            router = MultiLLMRouter()

        assert "gw" in router.providers, "验过的端点没进路由器 —— 面板显示能用，实际选不到它"
        cfg = router.providers["gw"]
        assert cfg.default_model == "gw-fast"
        assert cfg.source_type == "user", "来源没标出来 —— 诊断时分不清这是内置厂商还是用户加的"
        assert "gw" in router.adapters


class TestThePanelIsActuallyWiredToThoseEndpoints:
    """面板那一段必须真的打这四个端点，而不是长得像。

    后端做好、路由挂上、面板画了一个漂亮的表单 —— 但按钮什么都不做。这在本仓
    发生过(「喂文件」那个按钮拿到 pickFiles 的结果之后什么都没干，接了整整一轮
    才被发现)。所以这里按**源码**核一遍接线，端点路径写全串(不许拼接)，
    这样搜索和这道门都能找到它。
    """

    PANEL_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/providers/user",
        ],
    )
    def test_transport_names_the_endpoint_in_full(self, path):
        src = (self.PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
        assert path in src, f"transport.ts 里找不到 {path} —— 面板没在打这个端点，或者路径被拼接拆碎了"

    @pytest.mark.parametrize(
        "verb", ["fetchUserProviders", "saveUserProvider", "verifyUserProvider", "deleteUserProvider"]
    )
    def test_main_actually_calls_each_transport_function(self, verb):
        src = (self.PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        assert f"{verb}(" in src, f"main.ts 里没有调用 {verb} —— 那它就是个没接线的按钮"

    def test_the_section_is_mounted_into_the_settings_page(self):
        main = (self.PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        settings = (self.PANEL_SRC / "ui/settings.ts").read_text(encoding="utf-8")
        assert "createUserProviders(" in main, "main.ts 没有创建这一段"
        assert "topSection: userProviders.root" in main, "创建了但没交给设置页 —— 那它永远不会出现在屏幕上"
        assert "cb.topSection" in settings, "设置页没有把它挂进 body"

    def test_all_three_states_have_their_own_styling(self):
        """live / declared / unverified 必须长得不一样。

        把「网关自己报的型号」和「你自己敲的型号」画成同一个绿点，敲错一个字时
        人会以为是系统坏了。
        """
        css = (self.PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        for state in ("live", "declared", "unverified"):
            assert f"data-state='{state}'" in css, f"{state} 这一态没有自己的样式 —— 三种状态被画成了同一件事"


class TestEveryProtocolTheBackendAcceptsIsReachableFromThePanel:
    """后端认的协议，界面上必须选得到。

    这一条是补的：第一版面板把 protocol 写死成 'openai'，而后端一直也认
    'anthropic'。那不是"少做了一个功能"，是**后端有能力、界面上够不着** ——
    一个 Claude 兼容的网关加不进来，而且从界面上完全看不出为什么。

    它是本仓最怕那种缺陷的镜像：不是"看起来接上了其实没有"，而是
    "其实有，但没有任何入口"。两者都靠肉眼发现不了，所以都要有门。

    修法不是在前端也列一份名单（那就成了第二处权威，后端增减协议时会悄悄错开
    且不报错），而是让后端把名单一起返回、前端照着画。
    """

    PANEL_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"

    def test_the_list_endpoint_publishes_the_supported_protocols(self, client):
        body = client.get("/api/v1/providers/user").json()
        from core.user_providers import SUPPORTED_PROTOCOLS

        assert body.get("supported_protocols") == list(SUPPORTED_PROTOCOLS), (
            "列表端点没有把「支持哪些协议」发出去 —— 那前端只能自己写死一份，"
            "而写死的那份会在后端增减协议时悄悄错开。"
        )

    def test_the_panel_reads_that_list_instead_of_hardcoding_one(self):
        transport = (self.PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
        ui = (self.PANEL_SRC / "ui/user_providers.ts").read_text(encoding="utf-8")

        assert "supported_protocols" in transport, "transport.ts 没有读后端给的协议名单"
        assert "renderProtocols(" in ui, "界面上没有按名单画协议档位牌"
        assert "protocol: 'openai'," not in ui, "协议还是写死的 'openai' —— 后端认的其它协议在界面上够不着。"

    @pytest.mark.parametrize("proto", ["openai", "anthropic"])
    def test_each_protocol_is_actually_accepted_end_to_end(self, client, proto):
        """不只是"名单里有"，而是**真的存得进去**。"""
        r = client.post(
            "/api/v1/providers/user",
            json={"id": f"gw-{proto}", "base_url": "https://x.example.com/v1", "protocol": proto},
        )
        assert r.status_code == 200, f"协议 {proto} 在名单里，却存不进去"
        assert r.json()["protocol"] == proto


class TestEditingDoesNotLeakTheKeyBackIntoTheDom:
    """「编辑」把一条端点填回表单时，密钥**不回填**。

    把它重新摊到 DOM 上没有任何好处 —— 想看的人本来就看得到，而不想泄露的场合
    （录屏、截图、远程桌面）它会跟着一起走。留空表示不改，后端保留原来那份。

    这条与设置页里那 26 个密钥输入框是同一条规矩，写成门是因为「编辑」这个新入口
    很容易顺手把值填回去。
    """

    PANEL_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"

    def test_fill_form_never_assigns_a_key_value(self):
        ui = (self.PANEL_SRC / "ui/user_providers.ts").read_text(encoding="utf-8")
        assert "function fillForm(" in ui, "没有「编辑」这条路 —— 改一条端点只能整份重打"
        body = ui.split("function fillForm(", 1)[1].split("\n  }", 1)[0]
        assert "fKey.value = ''" in body, "fillForm 里没有把密钥框清空 —— 它可能被回填了"
        assert "row.has_key ?" in body, "没有把「存过没有」表达出来，用户会以为自己没存过"

    def test_omitting_the_key_on_update_keeps_the_stored_one(self, client):
        """端到端：改标签不必重填 Key。"""
        from core.user_providers import api_key_for

        client.post(
            "/api/v1/providers/user",
            json={"id": "gw", "base_url": "https://x.example.com/v1", "api_key": "sk-keep-me"},
        )
        client.post(
            "/api/v1/providers/user", json={"id": "gw", "label": "改了个名", "base_url": "https://x.example.com/v1"}
        )
        assert api_key_for("gw") == "sk-keep-me", "只改了标签，密钥却丢了 —— 那等于逼人每次都重填"
