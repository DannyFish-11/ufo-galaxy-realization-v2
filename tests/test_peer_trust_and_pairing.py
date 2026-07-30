"""对端信任 + 智能体名片配对的行为测试。

覆盖三件事,每件都要求"真的接上了",而不只是模块能 import:

1. :mod:`core.peer_trust` 的五级判定与自动放行模式;
2. :mod:`core.agent_card` 的签名防篡改、过期、短码一次性;
3. **接入证明** —— 端点真的挂进了 ``create_api_routes()``,
   且 ``evaluate_dispatch_readiness()`` 真的会因 blocked 而拒绝派发。

第 3 类是重点:本仓库反复出现"模块造好了但没有任何生产调用方"
(``core/capability_token.py`` 在本次改动前就是如此,全仓只有测试在用它)。
因此这里不满足于"函数能调通",而是从真实路由表和真实派发门去断言。
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_introspection import iter_flat_routes  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """每个用例一份独立的信任档案与配对码表,避免互相污染。"""
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_PEER_DEFAULT_TRUST", raising=False)
    import core.agent_card as ac
    import core.peer_trust as pt

    pt.reset_peer_trust_book()
    ac.reset_pairing_code_registry()
    yield
    pt.reset_peer_trust_book()
    ac.reset_pairing_code_registry()


# ── 1. 信任判定 ───────────────────────────────────────────────────────────
class TestTrustDecisions:
    def test_blocked_is_hard_denial_regardless_of_intent(self):
        from core.peer_trust import PermissionResult, TrustLevel, get_peer_trust_book

        book = get_peer_trust_book()
        # 即便给了通配自动放行,blocked 也必须拒绝 —— 拉黑优先于一切
        book.upsert("evil", trust=TrustLevel.BLOCKED, auto_accept=["*"])
        assert book.check("evil", "messaging.send") is PermissionResult.DENIED
        assert book.check("evil", "") is PermissionResult.DENIED

    def test_trusted_allows_without_patterns(self):
        from core.peer_trust import PermissionResult, TrustLevel, get_peer_trust_book

        book = get_peer_trust_book()
        book.upsert("main-pc", trust=TrustLevel.TRUSTED)
        assert book.check("main-pc", "anything.at.all") is PermissionResult.ALLOWED

    def test_friend_only_auto_accepts_matching_patterns(self):
        from core.peer_trust import PermissionResult, TrustLevel, get_peer_trust_book

        book = get_peer_trust_book()
        book.upsert("phone", trust=TrustLevel.FRIEND, auto_accept=["messaging.*", "scheduling.query"])
        assert book.check("phone", "messaging.send") is PermissionResult.ALLOWED
        assert book.check("phone", "scheduling.query") is PermissionResult.ALLOWED
        # 未命中的意图仍要人确认 —— 这正是"只问该问的"
        assert book.check("phone", "shell.exec") is PermissionResult.REQUIRE_APPROVAL
        assert book.check("phone", "scheduling.cancel") is PermissionResult.REQUIRE_APPROVAL

    def test_unpaired_peer_uses_conservative_default(self):
        from core.peer_trust import PermissionResult, TrustLevel, get_peer_trust_book

        book = get_peer_trust_book()
        assert book.trust_of("never-seen") is TrustLevel.ASK
        assert book.check("never-seen", "messaging.send") is PermissionResult.REQUIRE_APPROVAL

    def test_default_trust_is_configurable(self, monkeypatch):
        import core.peer_trust as pt

        monkeypatch.setenv("GALAXY_PEER_DEFAULT_TRUST", "blocked")
        pt.reset_peer_trust_book()
        assert pt.get_peer_trust_book().check("stranger", "x") is pt.PermissionResult.DENIED

    def test_trust_survives_reload_from_disk(self):
        import core.peer_trust as pt

        pt.get_peer_trust_book().upsert("persist-me", trust=pt.TrustLevel.TRUSTED, auto_accept=["a.*"])
        pt.reset_peer_trust_book()  # 丢弃单例,强制重新从盘上读
        rec = pt.get_peer_trust_book().get("persist-me")
        assert rec is not None and rec.trust == "trusted" and rec.auto_accept == ["a.*"]

    def test_str_enum_uses_value_not_repr(self):
        """(str, Enum) 上 str(member) 会得到 'TrustLevel.ASK',落盘必须用 .value。"""
        import json

        import core.peer_trust as pt

        pt.get_peer_trust_book().upsert("x", trust=pt.TrustLevel.FRIEND)
        raw = json.load(open(os.path.join(os.environ["GALAXY_DATA_DIR"], "peer_trust.json"), encoding="utf-8"))
        assert raw["peers"]["x"]["trust"] == "friend"


# ── 2. 名片 ───────────────────────────────────────────────────────────────
class TestAgentCard:
    def test_roundtrip_preserves_content(self):
        from core.agent_card import create_agent_card, from_link, to_link

        card = create_agent_card("dev-1", name="手机", capabilities=["messaging"], endpoints={"websocket": "ws://x/y"})
        v = from_link(to_link(card))
        assert v.valid
        assert v.card.device_id == "dev-1"
        assert v.card.capabilities == ["messaging"]
        assert v.card.endpoints == {"websocket": "ws://x/y"}

    def test_tampered_link_is_rejected_and_returns_no_card(self):
        """校验失败时绝不能返回半张名片 —— 否则伪造名片就进了信任链。"""
        from core.agent_card import create_agent_card, from_link, to_link

        link = to_link(create_agent_card("dev-1"))
        v = from_link(link[:-4] + "AAAA")
        assert v.valid is False
        assert v.card is None
        assert "签名" in v.reason

    def test_expired_card_is_rejected(self):
        from core.agent_card import create_agent_card, from_link, to_link

        card = create_agent_card("dev-1", ttl_s=10.0, now=1000.0)
        assert from_link(to_link(card), now=1005.0).valid is True
        assert from_link(to_link(card), now=2000.0).valid is False

    def test_non_pairing_link_rejected(self):
        from core.agent_card import from_link

        assert from_link("https://evil.example/pair?c=a&s=b").valid is False

    def test_pairing_code_is_single_use(self):
        from core.agent_card import create_agent_card, get_pairing_code_registry, to_link

        reg = get_pairing_code_registry()
        code, _ = reg.issue(to_link(create_agent_card("dev-1")))
        assert reg.resolve(code) is not None
        assert reg.resolve(code) is None

    def test_pairing_code_expires(self):
        from core.agent_card import create_agent_card, get_pairing_code_registry, to_link

        reg = get_pairing_code_registry()
        code, _ = reg.issue(to_link(create_agent_card("dev-1")), ttl_s=60.0, now=1000.0)
        assert reg.resolve(code, now=2000.0) is None


# ── 3. 接入证明 ───────────────────────────────────────────────────────────
class TestActuallyWiredIn:
    """不满足于"能调通",而是断言它进了真实路由表和真实派发门。"""

    def test_pairing_endpoints_are_mounted_in_create_api_routes(self):
        from core.api_routes import create_api_routes

        paths = {getattr(r, "path", "") for r in iter_flat_routes(create_api_routes())}
        for expected in (
            "/api/v1/pair/card",
            "/api/v1/pair/claim",
            "/api/v1/pair/peers",
            "/api/v1/pair/trust",
            "/api/v1/pair/check",
        ):
            assert expected in paths, f"{expected} 未挂进 create_api_routes —— 端点会 404"

    def test_blocked_peer_is_refused_by_the_dispatch_gate(self):
        """派发门是"唯一权威前置检查",拉黑必须在这里生效,而不只是存在档案里。"""
        from core.peer_trust import TrustLevel, get_peer_trust_book
        from core.unified_dispatch_readiness_gate import DispatchReadinessStatus, evaluate_dispatch_readiness

        get_peer_trust_book().upsert("evil", trust=TrustLevel.BLOCKED)
        r = evaluate_dispatch_readiness("evil")
        assert r.dispatch_ready is False
        assert r.status == DispatchReadinessStatus.BLOCKED_PEER_TRUST.value
        assert r.peer_trust == "blocked"

    def test_gate_reports_peer_trust_on_every_path(self):
        """peer_trust 不能只在被拦时才有值,否则这个字段对调用方没用。"""
        from core.peer_trust import TrustLevel, get_peer_trust_book
        from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness

        get_peer_trust_book().upsert("known", trust=TrustLevel.TRUSTED)
        assert evaluate_dispatch_readiness("known").peer_trust == "trusted"
        # 未登记设备走的是另一条 return 分支,同样要带出默认信任
        assert evaluate_dispatch_readiness("unknown-dev").peer_trust == "ask"
        assert "peer_trust" in evaluate_dispatch_readiness("known").to_dict()

    def test_gate_fails_open_when_trust_layer_unavailable(self, monkeypatch):
        """信任层是加固,不该成为新的单点故障:它坏了,派发不能整体停摆。"""
        import core.peer_trust as pt
        from core.unified_dispatch_readiness_gate import DispatchReadinessStatus, evaluate_dispatch_readiness

        def _boom():
            raise RuntimeError("信任层故障")

        monkeypatch.setattr(pt, "get_peer_trust_book", _boom)
        r = evaluate_dispatch_readiness("some-dev")
        assert r.status != DispatchReadinessStatus.BLOCKED_PEER_TRUST.value


class TestUpsertDoesNotSilentlyDowngradeTrust:
    """新建档案的初始信任必须取 _default_trust(),不能用 dataclass 默认值。

    两者是"未指定信任算几级"的两个不同真相源:未登记对端走 _default_trust()
    (默认 ask,可配),而 PeerRecord 的 dataclass 默认是 unknown —— 比 ask 低。
    于是调 POST /api/v1/pair/trust 只传 device_id(例如只想改备注)就会把该对端
    悄悄降级。若部署方把默认设成 friend,原本 allowed 的意图会变成 require_approval。
    """

    @pytest.mark.parametrize("default_trust", ["blocked", "unknown", "ask", "friend", "trusted"])
    def test_note_only_upsert_preserves_effective_trust(self, default_trust, tmp_path, monkeypatch):
        import core.peer_trust as pt

        # 每个参数一份独立存储 —— 否则上一轮落盘的记录会让本轮走"已存在"分支,
        # 根本测不到新建路径(第一版探针就是这么自欺的)。
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / default_trust))
        monkeypatch.setenv("GALAXY_PEER_DEFAULT_TRUST", default_trust)
        pt.reset_peer_trust_book()
        book = pt.get_peer_trust_book()

        before = book.trust_of("dev").value
        assert before == default_trust  # 前提:未登记对端按配置的默认值处理
        book.upsert("dev", note="只想加个备注")
        assert book.trust_of("dev").value == before, "只改备注不该动权限"

    def test_explicit_trust_still_wins(self, tmp_path, monkeypatch):
        import core.peer_trust as pt

        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("GALAXY_PEER_DEFAULT_TRUST", "friend")
        pt.reset_peer_trust_book()
        book = pt.get_peer_trust_book()
        book.upsert("dev", trust="blocked")
        assert book.trust_of("dev").value == "blocked"
        book.upsert("dev", note="事后改备注")
        assert book.trust_of("dev").value == "blocked", "备注更新不能把 blocked 冲掉"


class TestPairingCodeRegistryIsBounded:
    """短码表必须有上限。

    GET /api/v1/pair/card 每调用一次就签发一个 10 分钟有效的短码;只清过期、
    不限总数的话,任何反复拉名片的客户端都会让这张表持续膨胀(实测 5000 次
    签发即积压 5000 条)。与 IPBlockList、学习引擎模式表同类。
    """

    def test_active_codes_are_capped(self):
        from core.agent_card import PairingCodeRegistry, create_agent_card, to_link

        reg = PairingCodeRegistry(max_active=32)
        link = to_link(create_agent_card("d"))
        codes = [reg.issue(link)[0] for _ in range(500)]
        assert reg.active_count() <= 32
        assert reg.evicted > 0, "应当发生过淘汰"

    def test_newest_survives_and_oldest_is_evicted(self):
        from core.agent_card import PairingCodeRegistry, create_agent_card, to_link

        reg = PairingCodeRegistry(max_active=8)
        link = to_link(create_agent_card("d"))
        codes = [reg.issue(link)[0] for _ in range(64)]
        assert reg.resolve(codes[-1]) is not None, "最新签发的必须可兑换"
        assert reg.resolve(codes[0]) is None, "最旧的应已被挤掉"

    def test_cap_does_not_break_single_use_semantics(self):
        from core.agent_card import PairingCodeRegistry, create_agent_card, to_link

        reg = PairingCodeRegistry(max_active=8)
        code, _ = reg.issue(to_link(create_agent_card("d")))
        assert reg.resolve(code) is not None
        assert reg.resolve(code) is None


class TestHitlWaiver:
    """信任豁免人工确认 —— 这是分级信任的"便利性"落点:只问该问的。

    这些用例必须真的走到 readiness_gate 的第 9 步(确认门)。默认策略是
    ``observe_only``,会在第 7 步就 blocked,根本到不了第 9 步 —— 因此这里注入一个
    "允许执行但要求确认"的真实 ExecutionPolicy。用假对象会因 policy_band 缺 .value
    而落进 safe fallback,测试看起来通过实则什么都没验到。
    """

    @pytest.fixture
    def gate_with_confirming_policy(self, monkeypatch):
        import core.execution.readiness_gate as rg
        from core.execution_policy.execution_policy import ExecutionPolicy, PolicyBand

        policy = ExecutionPolicy(
            policy_band=PolicyBand.BOUNDED_EXECUTE,
            action_budget=10,
            requires_confirmation=True,
            reason="test: permit execution but demand confirmation",
        )
        monkeypatch.setattr(rg.ExecutionReadinessGate, "_resolve_policy", lambda self, sc, notes: policy, raising=True)
        return rg

    @staticmethod
    def _profile(target_ref, target_type, intent):
        from types import SimpleNamespace

        return SimpleNamespace(
            action_level="direct",
            target_ref=target_ref,
            target_type=target_type,
            runtime_session_id="s1",
            runtime_domain="local",
            intent_id=intent,
        )

    def test_trusted_device_skips_confirmation(self, gate_with_confirming_policy):
        from core.peer_trust import TrustLevel, get_peer_trust_book

        get_peer_trust_book().upsert("pc", trust=TrustLevel.TRUSTED)
        r = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("pc", "device", "messaging.send")
        )
        assert r.requires_confirmation is False
        assert r.status == "ready"

    def test_friend_skips_only_matching_intents(self, gate_with_confirming_policy):
        from core.peer_trust import TrustLevel, get_peer_trust_book

        get_peer_trust_book().upsert("phone", trust=TrustLevel.FRIEND, auto_accept=["messaging.*"])
        matched = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("phone", "device", "messaging.send")
        )
        unmatched = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("phone", "device", "shell.exec")
        )
        assert matched.requires_confirmation is False
        assert unmatched.requires_confirmation is True

    def test_unpaired_device_still_requires_confirmation(self, gate_with_confirming_policy):
        r = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("stranger", "device", "messaging.send")
        )
        assert r.requires_confirmation is True

    def test_non_device_target_is_never_treated_as_a_peer(self, gate_with_confirming_policy):
        """target_ref 也可能是 app 名/窗口标题;拿它去查对端信任是张冠李戴。"""
        from core.peer_trust import TrustLevel, get_peer_trust_book

        get_peer_trust_book().upsert("Notepad", trust=TrustLevel.TRUSTED)
        r = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("Notepad", "app", "messaging.send")
        )
        assert r.requires_confirmation is True

    def test_trust_layer_failure_fails_closed_here(self, gate_with_confirming_policy, monkeypatch):
        """与派发门相反:这里失败必须保持"要确认",放行等于绕过人工确认。"""
        import core.peer_trust as pt

        monkeypatch.setattr(pt, "check_peer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("信任层故障")))
        r = gate_with_confirming_policy.evaluate_readiness(
            intent_profile=self._profile("pc", "device", "messaging.send")
        )
        assert r.requires_confirmation is True


class TestPairingFlow:
    @pytest.fixture
    def client(self):
        from core.routes.pairing import create_router

        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app)

    def test_claim_by_code_registers_peer_and_issues_token(self, client):
        from core.capability_token import verify_token

        card = client.get("/api/v1/pair/card").json()
        r = client.post(
            "/api/v1/pair/claim",
            json={"code": card["code"], "trust": "friend", "auto_accept": ["messaging.*"]},
        ).json()
        assert r["success"] is True
        assert r["peer"]["trust"] == "friend"
        # capability_token 在本次改动前全仓无生产调用方 —— 这条锁定它已被接活
        assert r["token_issued"] is True
        assert verify_token(r["capability_token"], required_scope="device:tap").valid is True
        assert verify_token(r["capability_token"], required_scope="admin:wipe").valid is False

    def test_token_scopes_follow_trust_level(self, client):
        from core.capability_token import verify_token

        card = client.get("/api/v1/pair/card").json()
        r = client.post("/api/v1/pair/claim", json={"link": card["link"], "trust": "trusted"}).json()
        assert r["token_scopes"] == ["*"]
        assert verify_token(r["capability_token"], required_scope="admin:wipe").valid is True

    def test_claim_rejects_tampered_link(self, client):
        card = client.get("/api/v1/pair/card").json()
        r = client.post("/api/v1/pair/claim", json={"link": card["link"][:-4] + "AAAA"})
        assert r.status_code == 400
        assert r.json()["success"] is False

    def test_claim_requires_link_or_code(self, client):
        assert client.post("/api/v1/pair/claim", json={}).status_code == 400

    def test_unpaired_peer_lookup_reports_effective_trust_not_404(self, client):
        r = client.get("/api/v1/pair/peers/nobody").json()
        assert r["success"] is True and r["registered"] is False
        assert r["effective_trust"] == "ask"

    def test_check_endpoint_explains_decision(self, client):
        card = client.get("/api/v1/pair/card").json()
        did = client.post(
            "/api/v1/pair/claim",
            json={"code": card["code"], "trust": "friend", "auto_accept": ["messaging.*"]},
        ).json()["peer"]["device_id"]

        assert (
            client.post("/api/v1/pair/check", json={"device_id": did, "intent": "messaging.send"}).json()["result"]
            == "allowed"
        )
        assert (
            client.post("/api/v1/pair/check", json={"device_id": did, "intent": "shell.exec"}).json()["result"]
            == "require_approval"
        )

    def test_internal_errors_do_not_leak_exception_text(self, client, monkeypatch):
        """CodeQL: Information exposure through an exception。

        配对是信任链入口,内部异常文本(可能含文件路径、模块名、密钥文件位置)
        绝不能回给调用方;但要留下 error_code,让人能凭它去服务端日志定位。
        """
        import core.peer_trust as pt

        secret = "/very/secret/path/.galaxy_mesh_key"
        monkeypatch.setattr(pt, "get_peer_trust_book", lambda: (_ for _ in ()).throw(RuntimeError(f"{secret} 打不开")))
        r = client.get("/api/v1/pair/peers")
        assert r.status_code == 500
        assert secret not in r.text
        assert "RuntimeError" not in r.text
        assert r.json()["error_code"] == "pair_list_peers"

    def test_card_rejection_reason_carries_no_exception_text(self, client):
        """from_link 的 reason 会被原样回传,同样不能带异常文本。"""
        r = client.post("/api/v1/pair/claim", json={"link": "galaxy://pair?c=@@@bad@@@&s=@@@"})
        assert r.status_code == 400
        body = r.text
        assert "Traceback" not in body and "Error:" not in body
        # 仍要给出可行动的原因,而不是一句无信息的"失败"
        assert r.json()["error"]

    def test_trust_can_be_raised_and_revoked(self, client):
        card = client.get("/api/v1/pair/card").json()
        did = client.post("/api/v1/pair/claim", json={"code": card["code"]}).json()["peer"]["device_id"]

        client.post("/api/v1/pair/trust", json={"device_id": did, "trust": "blocked"})
        assert client.post("/api/v1/pair/check", json={"device_id": did}).json()["result"] == "denied"

        assert client.delete(f"/api/v1/pair/peers/{did}").json()["removed"] is True
        assert client.get(f"/api/v1/pair/peers/{did}").json()["registered"] is False
