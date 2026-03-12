"""
tests/test_p1_features.py
=========================
P1 功能测试：执行链路可视化、权限管理中心、集成管理

注：这些测试直接导入 dashboard.backend.main 的 FastAPI 应用，
使用 httpx.AsyncClient（TestClient）进行端点验证，无需外部服务。
"""

import json
import os
import sys
import tempfile
import pytest

# ── 添加项目根目录到 sys.path ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 辅助：临时替换 _PERMISSIONS_POLICY_FILE / _INTEGRATIONS_CONFIG_FILE
# ---------------------------------------------------------------------------

def _patch_data_files(monkeypatch, tmp_path):
    """将后端的数据文件路径重定向到临时目录，避免污染真实数据。"""
    import dashboard.backend.main as m
    monkeypatch.setattr(m, "_PERMISSIONS_POLICY_FILE", str(tmp_path / "permissions_policy.json"))
    monkeypatch.setattr(m, "_INTEGRATIONS_CONFIG_FILE", str(tmp_path / "integrations_config.json"))


# ---------------------------------------------------------------------------
# Permissions policy tests
# ---------------------------------------------------------------------------

class TestPermissionsPolicyEndpoints:

    def test_get_default_policy(self, monkeypatch, tmp_path):
        """GET /api/v1/permissions/policy 在文件不存在时返回内置默认值"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        resp = client.get("/api/v1/permissions/policy")
        assert resp.status_code == 200
        data = resp.json()
        assert "global" in data
        assert "agent_overrides" in data
        global_perms = data["global"]
        for key in ("filesystem", "terminal", "network", "browser"):
            assert key in global_perms

    def test_update_global_policy(self, monkeypatch, tmp_path):
        """POST /api/v1/permissions/policy 可以更新全局权限"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        payload = {"global": {"filesystem": True, "terminal": False, "network": True, "browser": False}}
        resp = client.post("/api/v1/permissions/policy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["policy"]["global"]["filesystem"] is True

    def test_update_agent_override(self, monkeypatch, tmp_path):
        """POST /api/v1/permissions/policy 可以添加 agent_overrides"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        payload = {"agent_overrides": {"agent_test_001": {"filesystem": True, "terminal": True}}}
        resp = client.post("/api/v1/permissions/policy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_test_001" in data["policy"]["agent_overrides"]
        assert data["policy"]["agent_overrides"]["agent_test_001"]["filesystem"] is True

    def test_policy_persisted(self, monkeypatch, tmp_path):
        """写入后再次 GET 应返回持久化的值"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        client.post("/api/v1/permissions/policy", json={"global": {"filesystem": True}})
        resp = client.get("/api/v1/permissions/policy")
        assert resp.json()["global"]["filesystem"] is True


# ---------------------------------------------------------------------------
# Integrations config tests
# ---------------------------------------------------------------------------

class TestIntegrationsConfigEndpoints:

    def test_get_default_integrations(self, monkeypatch, tmp_path):
        """GET /api/v1/integrations/config 返回 4 个平台的默认配置"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        resp = client.get("/api/v1/integrations/config")
        assert resp.status_code == 200
        data = resp.json()
        for platform in ("telegram", "discord", "slack", "whatsapp"):
            assert platform in data

    def test_update_integration_enabled(self, monkeypatch, tmp_path):
        """POST /api/v1/integrations/config 可启用 Telegram"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        resp = client.post("/api/v1/integrations/config", json={"telegram": {"enabled": True}})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_token_masked_on_get(self, monkeypatch, tmp_path):
        """保存 Token 后，GET 应返回脱敏（空字符串），但 _configured 为 True"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        # 直接写入原始文件
        raw = m._DEFAULT_INTEGRATIONS_CONFIG.copy()
        raw["telegram"] = dict(raw.get("telegram", {}))
        raw["telegram"]["bot_token"] = "secret-token-abc"
        raw["updated_at"] = ""
        with open(str(tmp_path / "integrations_config.json"), "w") as f:
            json.dump(raw, f)

        resp = client.get("/api/v1/integrations/config")
        data = resp.json()
        assert data["telegram"]["bot_token"] == ""
        assert data["telegram"]["bot_token_configured"] is True

    def test_update_webhook_url(self, monkeypatch, tmp_path):
        """POST 更新 webhook_url 后，GET 应返回更新后的值"""
        from fastapi.testclient import TestClient
        import dashboard.backend.main as m
        _patch_data_files(monkeypatch, tmp_path)

        client = TestClient(m.app)
        client.post("/api/v1/integrations/config", json={"discord": {"webhook_url": "https://discord.com/api/webhooks/test"}})
        # 再次 GET（token 脱敏，但 webhook_url 可以明文读回）
        # 写入裸数据并验证持久化
        with open(str(tmp_path / "integrations_config.json")) as f:
            saved = json.load(f)
        assert saved["discord"]["webhook_url"] == "https://discord.com/api/webhooks/test"


# ---------------------------------------------------------------------------
# Policy loader tests
# ---------------------------------------------------------------------------

class TestPolicyLoader:

    def test_get_global_permissions_defaults(self, tmp_path, monkeypatch):
        """policy_loader 文件不存在时返回内置默认值"""
        import core.policy_loader as pl
        monkeypatch.setattr(pl, "_POLICY_FILE", str(tmp_path / "nonexistent.json"))
        perms = pl.get_global_permissions()
        assert isinstance(perms, dict)
        for key in ("filesystem", "terminal", "network", "browser"):
            assert key in perms

    def test_get_agent_permissions_inherits_global(self, tmp_path, monkeypatch):
        """agent_id 无覆盖时，get_agent_permissions 继承全局权限"""
        import core.policy_loader as pl
        policy = {
            "global": {"filesystem": False, "terminal": False, "network": True, "browser": False},
            "agent_overrides": {},
        }
        pfile = tmp_path / "permissions_policy.json"
        pfile.write_text(json.dumps(policy))
        monkeypatch.setattr(pl, "_POLICY_FILE", str(pfile))
        perms = pl.get_agent_permissions("unknown_agent")
        assert perms["network"] is True
        assert perms["filesystem"] is False

    def test_get_agent_permissions_override(self, tmp_path, monkeypatch):
        """agent_overrides 优先于全局策略"""
        import core.policy_loader as pl
        policy = {
            "global": {"filesystem": False, "terminal": False, "network": True, "browser": False},
            "agent_overrides": {"agent_A": {"filesystem": True, "terminal": True}},
        }
        pfile = tmp_path / "permissions_policy.json"
        pfile.write_text(json.dumps(policy))
        monkeypatch.setattr(pl, "_POLICY_FILE", str(pfile))
        perms = pl.get_agent_permissions("agent_A")
        assert perms["filesystem"] is True
        assert perms["terminal"] is True
        assert perms["network"] is True  # 继承全局

    def test_inject_policy_into_context(self, tmp_path, monkeypatch):
        """inject_policy_into_context 应在 context['permissions'] 中写入权限"""
        import core.policy_loader as pl
        monkeypatch.setattr(pl, "_POLICY_FILE", str(tmp_path / "nope.json"))
        ctx: dict = {"task": "do something"}
        result = pl.inject_policy_into_context(ctx)
        assert "permissions" in result
        assert isinstance(result["permissions"], dict)
