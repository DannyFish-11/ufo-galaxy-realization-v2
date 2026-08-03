"""tests/test_oauth_surface_and_id_token.py — 登录面必须真的挂着,ID Token 必须真的验。

这份测试钉两件事
----------------
**一、``/auth/oauth/*`` 此前任何进程都没有服务过。**
``register_oauth_routes()`` 定义在 ``nodes/Node_05_Auth/oauth_routes.py``,而全仓
(排除 ``.venv``)只有它自己那一行 —— 从来没被调用过;Node_05_Auth 自己的
``main.py`` 挂的是 ``/login`` / ``/refresh`` / ``/register`` 那一族,不含 ``/auth/``。

于是手表(``DeviceFlowManager``)的设备码登录、Android(``OAuthManager``)的
``logout`` / ``refresh``,全都打在不存在的端点上 —— 两个客户端的登录链路都是断的,
而没有任何测试会红。这里按客户端**实际调用的路径**逐条断言,而不是数路由条数。

**二、Google ID Token 的校验不能是摆设。**
ID Token 是一段任何人都能构造的 JSON。只要不验签,"用 Google 账号登录"就等于
"自称是谁就是谁" —— 攻击者拿自己伪造的 token 就能换到本系统的 JWT。

所以下面**不测"能签发 JWT"**(那种用例在校验被删光之后照样绿),而是逐项证明它会拒:
换个密钥签的、aud 不对的、iss 不对的、过期的。四条各拒一次,才说明四项校验都在。

不打网络
--------
校验用的公钥本该从 Google 的 JWKS 端点取。测试里把 ``_google_jwks_client`` 换成
一个返回本地生成密钥的桩 —— 既不依赖外网(CI 里 Google 未必可达),也让"用错误的
密钥签名"这种用例成为可能。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

CLIENT_ID = "test-android-client.apps.googleusercontent.com"


# ---------------------------------------------------------------------------
# 客户端实际会调的路径 —— 取自两个仓的生产代码,不是抄文档
# ---------------------------------------------------------------------------
#: WearOS ``DeviceFlowManager`` 打的
WEAROS_PATHS = ["/auth/oauth/device/start", "/auth/oauth/device/poll"]

#: Android ``OAuthManager`` 打的
ANDROID_PATHS = [
    "/auth/oauth/google",
    "/auth/oauth/github",
    "/auth/oauth/logout",
    "/auth/oauth/refresh",
]


@pytest.fixture(scope="module")
def authoritative_app():
    fastapi = pytest.importorskip("fastapi")
    from core.api_routes import create_api_routes

    app = fastapi.FastAPI()
    app.include_router(create_api_routes(service_manager=None, config=None))
    return app


class TestAuthSurfaceIsMounted:
    def test_every_path_the_watch_calls_exists(self, authoritative_app):
        paths = set(authoritative_app.openapi()["paths"])
        missing = [p for p in WEAROS_PATHS if p not in paths]
        assert not missing, (
            f"手表的设备码登录会 404:{missing}\n" "register_oauth_routes 没有被挂进权威层 —— 手表将无法登录。"
        )

    def test_every_path_android_calls_exists(self, authoritative_app):
        paths = set(authoritative_app.openapi()["paths"])
        missing = [p for p in ANDROID_PATHS if p not in paths]
        assert not missing, f"Android 的 OAuthManager 会 404:{missing}"

    def test_the_surface_actually_answers(self, authoritative_app):
        """存在不等于能答 —— 这是本仓一路在批的弱断言,不能自己再犯一次。"""
        from fastapi.testclient import TestClient

        client = TestClient(authoritative_app, raise_server_exceptions=False)
        dead = []
        for path in ("/auth/oauth/health", "/auth/oauth/providers"):
            resp = client.get(path)
            if resp.status_code == 404:
                dead.append(f"{path} -> 404")
        assert not dead, f"这些路由存在于 openapi 却答不了:{dead}"


# ---------------------------------------------------------------------------
# ID Token 校验
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def rsa_keys():
    """一对本地 RSA 密钥,外加一把**不同的**密钥用来伪造签名。"""
    good = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    evil = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return good, evil


@pytest.fixture
def patched_jwks(rsa_keys, monkeypatch):
    """把 JWKS 客户端换成返回本地公钥的桩 —— 不打网络。"""
    good, _evil = rsa_keys
    import nodes.Node_05_Auth.oauth_routes as mod

    class _Key:
        key = good.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, _token):
            return _Key()

    monkeypatch.setattr(mod, "_google_jwks_client", lambda: _Client())
    monkeypatch.setenv("GOOGLE_ANDROID_CLIENT_ID", CLIENT_ID)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    return mod


def _sign(key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "someone@example.com",
        "name": "Some One",
        "exp": now + timedelta(hours=1),
        "iat": now,
    }
    claims.update(overrides)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256")


class TestGoogleIdTokenVerification:
    def test_a_valid_token_is_accepted(self, patched_jwks, rsa_keys):
        """先证明"对的能过" —— 否则下面每条拒绝用例都可能是因为别的原因红。"""
        good, _ = rsa_keys
        user = patched_jwks._verify_google_id_token(_sign(good))
        assert user["email"] == "someone@example.com"
        assert user["id"] == "1234567890"
        assert user["provider"] == "google"

    def test_a_token_signed_by_someone_else_is_rejected(self, patched_jwks, rsa_keys):
        """**这一条是整份文件的核心。**

        用另一把私钥签的 token —— 内容可以写得和真的一模一样。不验签就会放行,
        而放行意味着任何人都能自称任何 Google 用户登录本系统。
        """
        _good, evil = rsa_keys
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            patched_jwks._verify_google_id_token(_sign(evil))
        assert exc.value.status_code == 401

    def test_a_token_for_another_app_is_rejected(self, patched_jwks, rsa_keys):
        """aud 不是本后端的客户端 ID —— 那是别家应用的 token,不能拿来登录这里。"""
        good, _ = rsa_keys
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            patched_jwks._verify_google_id_token(_sign(good, aud="someone-elses-app.apps.googleusercontent.com"))
        assert exc.value.status_code == 401

    def test_a_token_from_another_issuer_is_rejected(self, patched_jwks, rsa_keys):
        good, _ = rsa_keys
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            patched_jwks._verify_google_id_token(_sign(good, iss="https://evil.example.com"))
        assert exc.value.status_code == 401

    def test_an_expired_token_is_rejected(self, patched_jwks, rsa_keys):
        good, _ = rsa_keys
        from fastapi import HTTPException

        past = datetime.now(timezone.utc) - timedelta(hours=2)
        with pytest.raises(HTTPException) as exc:
            patched_jwks._verify_google_id_token(_sign(good, exp=past, iat=past - timedelta(hours=1)))
        assert exc.value.status_code == 401

    @pytest.mark.parametrize("issuer", ["accounts.google.com", "https://accounts.google.com"])
    def test_both_google_issuer_spellings_are_accepted(self, patched_jwks, rsa_keys, issuer):
        """Google 两种 iss 都会签发。只认一种会让一部分登录莫名失败。"""
        good, _ = rsa_keys
        assert patched_jwks._verify_google_id_token(_sign(good, iss=issuer))["provider"] == "google"

    def test_missing_client_id_config_says_so_instead_of_failing_obscurely(self, patched_jwks, monkeypatch):
        """没配客户端 ID 时要明说是配置问题。

        含糊地返回 401 会把人引去查 token,而问题其实在部署配置上 —— 那种错误
        最难查,因为每一条线索都指向错误的方向。
        """
        from fastapi import HTTPException

        monkeypatch.delenv("GOOGLE_ANDROID_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        with pytest.raises(HTTPException) as exc:
            patched_jwks._verify_google_id_token("whatever")
        assert exc.value.status_code == 503
        assert "GOOGLE_CLIENT_ID" in exc.value.detail

    def test_audience_list_accepts_either_configured_client_id(self, patched_jwks, rsa_keys, monkeypatch):
        """Android 原生的 client id 与 Web 的通常不是同一个,两个都要认。"""
        good, _ = rsa_keys
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-client.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_ANDROID_CLIENT_ID", CLIENT_ID)
        assert patched_jwks._verify_google_id_token(_sign(good, aud=CLIENT_ID))["id"] == "1234567890"
        assert (
            patched_jwks._verify_google_id_token(_sign(good, aud="web-client.apps.googleusercontent.com"))["id"]
            == "1234567890"
        )


class TestAlgorithmIsPinned:
    def test_source_pins_rs256(self):
        """不锁算法会给 alg=none / HS256 混淆攻击留口子。

        用读源码而不是构造攻击 token:PyJWT 新版本本身就拒 ``alg=none``,
        所以构造出来的用例会因为"库拦住了"而绿,证明不了**我们**锁了算法 ——
        哪天换个库或降级,洞就开了而用例还是绿的。
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "nodes" / "Node_05_Auth" / "oauth_routes.py").read_text(
            encoding="utf-8"
        )
        assert 'algorithms=["RS256"]' in src, "ID Token 校验没有锁定算法"


class TestLoggingDoesNotLeakIdentity:
    """登录日志不许出现可直接识别到人的字段。

    CodeQL 的 ``py/clear-text-logging-sensitive-data`` 在本轮点了一条
    ``logger.info(..., oauth_user["email"])``(high)。查下来同一类共四处,
    其中**存量那条更严重** —— ``logger.warning(f"...: {user_info}")`` 把整个
    用户信息字典(姓名、头像、id)打进了日志。所以四处一起改,而不是只修被点名的。

    日志会被采集、转发、长期留存。一条 ``logger.info`` 就把邮箱复制进了一条
    谁也说不清边界的管道 —— 与本仓 ``verify_provider_apis.py`` "绝不打印密钥值,
    连长度都不打" 是同一条规矩。
    """

    def _log_calls(self):
        import ast
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "nodes" / "Node_05_Auth" / "oauth_routes.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"info", "warning", "error", "debug", "exception"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"
            ):
                yield node, ast.unparse(node)

    def test_no_log_call_passes_an_identity_field(self):
        """用 AST 而不是正则:注释与 docstring 里提到 email 是允许的 ——
        那些恰恰是记录"为什么不打它"的地方,禁掉等于逼人删掉理由。"""
        leaks = []
        for node, text in self._log_calls():
            for bad in ("'email'", '"email"', ".email", "{user_info}", "{oauth_user}"):
                if bad in text:
                    leaks.append(f"line {node.lineno}: {text[:100]}")
                    break
        assert not leaks, "这些日志调用把可识别字段打了出去:\n  " + "\n  ".join(leaks)

    def test_the_guard_actually_sees_the_log_calls(self):
        """自证:如果 AST 遍历一条都没抓到,上面那条"没有泄漏"只是恒绿。"""
        assert len(list(self._log_calls())) >= 8, "只抓到很少的 logger 调用,遍历没生效"


class TestLogSubjectIsCorrelatableButNotReversible:
    def test_same_user_always_maps_to_the_same_string(self):
        """可对账 —— 否则排查"这个用户反复失败"时几条日志串不起来。"""
        from nodes.Node_05_Auth.oauth_routes import _log_subject

        user = {"id": "1234567890", "email": "a@example.com", "provider": "google"}
        assert _log_subject(user) == _log_subject(dict(user))

    def test_different_users_map_to_different_strings(self):
        from nodes.Node_05_Auth.oauth_routes import _log_subject

        a = _log_subject({"id": "1", "provider": "google"})
        b = _log_subject({"id": "2", "provider": "google"})
        assert a != b

    def test_the_email_does_not_appear_in_the_output(self):
        """不可还原 —— 这是这个函数存在的全部理由。"""
        from nodes.Node_05_Auth.oauth_routes import _log_subject

        out = _log_subject({"id": "1234567890", "email": "someone@example.com", "provider": "google"})
        assert "someone" not in out
        assert "example.com" not in out
        assert "1234567890" not in out
        assert out.startswith("google:")


class TestGitHubCodeExchange:
    def test_missing_code_is_rejected(self, authoritative_app):
        from fastapi.testclient import TestClient

        client = TestClient(authoritative_app, raise_server_exceptions=False)
        resp = client.post("/auth/oauth/github", json={"code": ""})
        assert resp.status_code == 400

    def test_client_supplied_redirect_uri_is_honoured(self):
        """必须用调用方给的 redirect_uri 构造 provider。

        GitHub 换取令牌时会校验它与授权时用的一致。客户端用的是自己的回调地址,
        而 ``get_oauth_provider()`` 拿到的是服务端默认值 —— 用后者换取必然
        redirect_uri_mismatch,而那个错误从客户端看只是"登录失败"。
        """
        from nodes.Node_05_Auth.oauth_providers import GitHubOAuthProvider

        provider = GitHubOAuthProvider(redirect_uri="galaxy://oauth/github")
        assert provider.redirect_uri == "galaxy://oauth/github"

    def test_source_builds_provider_with_the_supplied_redirect_uri(self):
        """钉住实现真的走了那条路 —— 上一条只证明了 provider 支持这个参数。"""
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "nodes" / "Node_05_Auth" / "oauth_routes.py").read_text(
            encoding="utf-8"
        )
        assert (
            "GitHubOAuthProvider(redirect_uri=body.redirect_uri" in src
        ), "github 那条没有用调用方给的 redirect_uri 构造 provider —— 换取会 mismatch"
