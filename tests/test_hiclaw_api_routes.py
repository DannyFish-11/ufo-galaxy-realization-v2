"""
HiClaw 新增 API 路由测试
========================

覆盖 core/api_routes.py 中新增的四类端点：
- /api/v1/vault/   — 集中凭证管理
- /api/v1/cost/    — 成本可观测性
- /api/v1/channels/ — 渠道插件
- /api/v1/federation/ — 多实例联邦
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ============================================================================
# Fixture: 共享 TestClient
# ============================================================================

@pytest.fixture(scope="module")
def client():
    from core.api_routes import create_api_routes
    app = FastAPI()
    router = create_api_routes()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


# ============================================================================
# 1. Vault 凭证管理
# ============================================================================

class TestVaultRoutes:

    def test_set_credential(self, client):
        """POST /api/v1/vault/credentials — 写入凭证"""
        r = client.post(
            "/api/v1/vault/credentials",
            json={"key_name": "openai", "value": "sk-test-key"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["key_name"] == "openai"

    def test_set_credential_missing_fields(self, client):
        """POST /api/v1/vault/credentials — 缺少必填字段返回 400"""
        r = client.post("/api/v1/vault/credentials", json={"key_name": "openai"})
        assert r.status_code == 400

        r = client.post("/api/v1/vault/credentials", json={"value": "sk-xxx"})
        assert r.status_code == 400

    def test_list_credentials(self, client):
        """GET /api/v1/vault/credentials — 列出凭证键名"""
        r = client.get("/api/v1/vault/credentials")
        assert r.status_code == 200
        data = r.json()
        assert "keys" in data
        assert isinstance(data["keys"], list)
        # openai 应已在上一个测试中写入
        assert "openai" in data["keys"]

    def test_issue_token(self, client):
        """POST /api/v1/vault/tokens — 颁发 token"""
        r = client.post(
            "/api/v1/vault/tokens",
            json={"device_id": "device-001", "ttl": 300, "scopes": ["openai"]},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "token" in data
        assert data["ttl"] == 300

    def test_issue_token_missing_device_id(self, client):
        """POST /api/v1/vault/tokens — 缺少 device_id 返回 400"""
        r = client.post("/api/v1/vault/tokens", json={"ttl": 300})
        assert r.status_code == 400

    def test_fetch_by_token(self, client):
        """POST /api/v1/vault/fetch — 用 token 拉取凭证"""
        # 先颁发 token
        r = client.post(
            "/api/v1/vault/tokens",
            json={"device_id": "device-fetch", "ttl": 300, "scopes": ["openai"]},
        )
        token = r.json()["token"]

        # 用 token 拉取
        r = client.post(
            "/api/v1/vault/fetch",
            json={"token": token, "key_name": "openai"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["key_name"] == "openai"
        assert "value" in data

    def test_fetch_by_invalid_token(self, client):
        """POST /api/v1/vault/fetch — 无效 token 返回 403"""
        r = client.post(
            "/api/v1/vault/fetch",
            json={"token": "invalid-token", "key_name": "openai"},
        )
        assert r.status_code == 403

    def test_fetch_missing_fields(self, client):
        """POST /api/v1/vault/fetch — 缺少必填字段返回 400"""
        r = client.post("/api/v1/vault/fetch", json={"token": "tok"})
        assert r.status_code == 400

    def test_audit_log(self, client):
        """GET /api/v1/vault/audit — 审计日志"""
        r = client.get("/api/v1/vault/audit?limit=50")
        assert r.status_code == 200
        data = r.json()
        assert "records" in data
        assert isinstance(data["records"], list)
        # 至少有前面测试产生的记录
        assert len(data["records"]) > 0
        # 每条记录应包含必要字段
        rec = data["records"][0]
        assert "action" in rec
        assert "timestamp" in rec

    def test_delete_credential(self, client):
        """DELETE /api/v1/vault/credentials/{key_name} — 删除凭证"""
        # 先写入一个专用凭证
        client.post(
            "/api/v1/vault/credentials",
            json={"key_name": "to_delete", "value": "temp-val"},
        )

        r = client.delete("/api/v1/vault/credentials/to_delete")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["key_name"] == "to_delete"

        # 不存在时返回 404
        r = client.delete("/api/v1/vault/credentials/nonexistent_key_xyz")
        assert r.status_code == 404


# ============================================================================
# 2. 成本可观测性
# ============================================================================

class TestCostRoutes:

    def test_get_records_empty(self, client):
        """GET /api/v1/cost/records — 无记录时返回空列表"""
        r = client.get("/api/v1/cost/records?limit=50")
        assert r.status_code == 200
        data = r.json()
        assert "records" in data
        assert isinstance(data["records"], list)

    def test_get_summary_empty(self, client):
        """GET /api/v1/cost/summary — 无记录时返回零值汇总"""
        r = client.get("/api/v1/cost/summary")
        assert r.status_code == 200
        data = r.json()
        assert "total_calls" in data
        assert "total_cost_usd" in data
        assert "by_provider" in data

    def test_get_records_after_record(self, client):
        """GET /api/v1/cost/records — 手动记录后应返回数据"""
        from core.cost_tracker import get_cost_tracker
        tracker = get_cost_tracker()
        tracker.record(
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
        )

        r = client.get("/api/v1/cost/records?limit=10")
        assert r.status_code == 200
        records = r.json()["records"]
        assert len(records) >= 1
        assert records[-1]["provider"] == "openai"

    def test_get_summary_after_record(self, client):
        """GET /api/v1/cost/summary — 记录后汇总应不为零"""
        r = client.get("/api/v1/cost/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["total_calls"] >= 1
        assert "openai" in data["by_provider"]


# ============================================================================
# 3. 渠道插件
# ============================================================================

class TestChannelRoutes:

    def test_list_plugins_empty(self, client):
        """GET /api/v1/channels — 返回已加载插件列表"""
        r = client.get("/api/v1/channels")
        assert r.status_code == 200
        data = r.json()
        assert "plugins" in data
        assert isinstance(data["plugins"], list)

    def test_load_builtin_plugin(self, client):
        """POST /api/v1/channels/load — 加载内置 console 插件"""
        r = client.post("/api/v1/channels/load", json={"plugin_id": "console"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["plugin_id"] == "console"
        assert data["name"] == "console"

    def test_load_unknown_plugin_returns_400(self, client):
        """POST /api/v1/channels/load — 未知插件返回 400"""
        r = client.post("/api/v1/channels/load", json={"plugin_id": "nonexistent_xyz"})
        assert r.status_code == 400

    def test_load_plugin_missing_id(self, client):
        """POST /api/v1/channels/load — 缺少 plugin_id 返回 400"""
        r = client.post("/api/v1/channels/load", json={})
        assert r.status_code == 400

    def test_list_plugins_after_load(self, client):
        """GET /api/v1/channels — 加载后能列出插件"""
        r = client.get("/api/v1/channels")
        assert r.status_code == 200
        plugins = r.json()["plugins"]
        ids = [p["plugin_id"] for p in plugins]
        assert "console" in ids

    def test_send_message(self, client):
        """POST /api/v1/channels/{plugin_id}/send — 发送消息"""
        r = client.post(
            "/api/v1/channels/console/send",
            json={"message": "Hello from test!", "target": "test-user"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True

    def test_send_message_missing_message(self, client):
        """POST /api/v1/channels/{plugin_id}/send — 缺少 message 返回 400"""
        r = client.post("/api/v1/channels/console/send", json={})
        assert r.status_code == 400

    def test_health_check(self, client):
        """GET /api/v1/channels/health — 健康检查"""
        r = client.get("/api/v1/channels/health")
        assert r.status_code == 200
        data = r.json()
        assert "health" in data
        assert "console" in data["health"]
        assert data["health"]["console"]["healthy"] is True


# ============================================================================
# 4. Galaxy 联邦
# ============================================================================

class TestFederationRoutes:

    def test_federation_info(self, client):
        """GET /api/v1/federation/info — 本实例信息"""
        r = client.get("/api/v1/federation/info")
        assert r.status_code == 200
        data = r.json()
        assert "instance_id" in data
        assert "url" in data
        assert "enabled" in data
        assert "peers_count" in data

    def test_list_peers_empty(self, client):
        """GET /api/v1/federation/peers — 初始状态无 peer"""
        r = client.get("/api/v1/federation/peers")
        assert r.status_code == 200
        data = r.json()
        assert "peers" in data
        assert isinstance(data["peers"], list)

    def test_register_peer(self, client):
        """POST /api/v1/federation/peers — 注册 peer"""
        r = client.post(
            "/api/v1/federation/peers",
            json={
                "url": "http://127.0.0.1:8001",
                "instance_id": "galaxy-B",
                "name": "Node B",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["peer"]["instance_id"] == "galaxy-B"
        assert data["peer"]["url"] == "http://127.0.0.1:8001"

    def test_register_peer_missing_url(self, client):
        """POST /api/v1/federation/peers — 缺少 url 返回 400"""
        r = client.post("/api/v1/federation/peers", json={"instance_id": "galaxy-C"})
        assert r.status_code == 400

    def test_list_peers_after_register(self, client):
        """GET /api/v1/federation/peers — 注册后能列出 peer"""
        r = client.get("/api/v1/federation/peers")
        assert r.status_code == 200
        peers = r.json()["peers"]
        ids = [p["instance_id"] for p in peers]
        assert "galaxy-B" in ids

    def test_receive_heartbeat(self, client):
        """POST /api/v1/federation/heartbeat — 接收心跳"""
        r = client.post(
            "/api/v1/federation/heartbeat",
            json={"instance_id": "galaxy-B", "url": "http://127.0.0.1:8001"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "instance_id" in data

    def test_receive_task(self, client):
        """POST /api/v1/federation/task — 接收并 echo 任务"""
        task = {"command": "ping", "params": {"data": "hello"}}
        r = client.post(
            "/api/v1/federation/task",
            json={"from_instance": "galaxy-A", "task": task},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["from_instance"] == "galaxy-A"
        assert data["task_received"] == task

    def test_forward_task_missing_target(self, client):
        """POST /api/v1/federation/forward — 缺少 target 返回 400"""
        r = client.post(
            "/api/v1/federation/forward",
            json={"task": {"command": "ping"}},
        )
        assert r.status_code == 400

    def test_federation_health(self, client):
        """GET /api/v1/federation/health — 联邦健康摘要"""
        r = client.get("/api/v1/federation/health")
        assert r.status_code == 200
        data = r.json()
        assert "instance_id" in data
        assert "peers_count" in data
        assert "alive" in data
        assert "degraded" in data
        assert "offline" in data
        assert "enabled" in data

    def test_peer_ping_not_found(self, client):
        """GET /api/v1/federation/peers/{instance_id}/ping — 未知 peer 返回 404"""
        r = client.get("/api/v1/federation/peers/nonexistent-peer-xyz/ping")
        assert r.status_code == 404

    def test_peer_ping_known_peer(self, client):
        """GET /api/v1/federation/peers/{instance_id}/ping — 已知 peer 返回状态"""
        r = client.get("/api/v1/federation/peers/galaxy-B/ping")
        assert r.status_code == 200
        data = r.json()
        assert data["instance_id"] == "galaxy-B"
        assert "status" in data
        assert "last_heartbeat_age_s" in data
        assert "alive" in data

    def test_heartbeat_throttle(self, client):
        """POST /api/v1/federation/heartbeat — 短时间内二次心跳被 throttle"""
        payload = {"instance_id": "galaxy-throttle-test", "url": "http://127.0.0.1:9999"}
        r1 = client.post("/api/v1/federation/heartbeat", json=payload)
        assert r1.status_code == 200
        # Second immediate heartbeat should be throttled (min_interval default 5s)
        r2 = client.post("/api/v1/federation/heartbeat", json=payload)
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["status"] == "throttled"
        assert "retry_after" in data2


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
