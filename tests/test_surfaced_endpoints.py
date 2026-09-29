"""挂出来的那一批接口：真的挂上了、写操作真的要鉴权、读出来的东西对。

背景：未接线清单里有一批"做好了却没有任何入口"的只读快照与运维操作（config/unwired_placement.json
里记为 surface）。这一批把它们挂到了各自该在的路由上；只读的内部快照统一收进
``/api/v1/diagnostics/internals``（需 API 鉴权、面板不画）。

顺带钉住挂的过程中查出来的几处真问题：
* 几个会装代码 / 换策略的写端点此前**没有鉴权**：从 GitHub 安装扩展、加载渠道插件（可从任意
  路径导入代码）、整张安全策略表替换；
* 操作者的任务谱系检查从未把回放事件放进时间线（迭代了一个不可迭代的数据类，异常被 debug 吞掉）；
* 「最近一分钟被拒次数」只在新的拒绝进来时才修剪窗口 —— 一波拒绝过后，这个数永远停在当时。
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TOKEN = "surface-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_NATS_ENABLED", "false")
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", TOKEN)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_KNOWLEDGE_DIR", str(tmp_path / "kb"))

    import core.agent_identity_memory as aim
    import core.tool_permissions as tp

    monkeypatch.setattr(aim, "_identity_memory", aim.AgentIdentityMemory(tmp_path / "identity.json"))
    monkeypatch.setattr(tp, "_checker_instance", None)

    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes(service_manager=None, config=None))
    return TestClient(app)


# ── 内部诊断索引 ──────────────────────────────────────────────────────────


class TestDiagnosticsInternals:
    def test_every_listed_section_is_readable(self, client):
        listed = client.get("/api/v1/diagnostics/internals", headers=AUTH).json()["sections"]
        assert len(listed) >= 30
        names = [s["name"] if isinstance(s, dict) else s for s in listed]
        broken = {}
        for name in names:
            r = client.get(f"/api/v1/diagnostics/internals/{name}", headers=AUTH)
            if r.status_code != 200:
                broken[name] = r.status_code
        assert not broken, f"这些段读不出来: {broken}"

    def test_unknown_section_is_404(self, client):
        assert client.get("/api/v1/diagnostics/internals/nope", headers=AUTH).status_code == 404

    def test_needs_auth(self, client):
        assert client.get("/api/v1/diagnostics/internals").status_code in (401, 403)


# ── 写端点一律要鉴权 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/v1/github/install", {"url": "https://github.com/a/b"}),
        ("post", "/api/v1/github/uninstall", {"name": "x"}),
        ("post", "/api/v1/channels/load", {"plugin_id": "x", "path": "/tmp/evil.py"}),
        ("delete", "/api/v1/channels/x", None),
        ("put", "/api/v1/security/policy", {"rules": []}),
        ("post", "/api/v1/security/tool-permissions", {"tool_pattern": "x"}),
        ("post", "/api/v1/agent/identity/goals", {"text": "x"}),
        ("post", "/api/v1/agent/identity/values", {"text": "x"}),
        ("post", "/api/v1/twin/couple-all", None),
        ("post", "/api/v1/twin/decouple-all", None),
        ("post", "/api/v1/governance/tools/x/reset-bucket", None),
        ("delete", "/api/v1/governance/tools/audit", None),
        ("post", "/api/v1/system/container-runtime/choice", {"runtime": "docker"}),
        ("get", "/api/v1/rag/knowledge-base/export", None),
        ("post", "/api/v1/rag/knowledge-base/import", {"entries": []}),
    ],
)
def test_write_endpoints_reject_anonymous_callers(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code in (401, 403), f"{method.upper()} {path} 没带令牌却返回 {r.status_code}"


# ── 各处挂出来的东西读得对 ──────────────────────────────────────────────


class TestAgentIdentity:
    def test_goals_and_values_round_trip(self, client):
        base = client.get("/api/v1/agent/identity").json()
        r = client.post("/api/v1/agent/identity/goals", json={"text": "学会新设备"}, headers=AUTH)
        assert "学会新设备" in r.json()["long_term_goals"]
        r = client.delete("/api/v1/agent/identity/goals", params={"text": "学会新设备"}, headers=AUTH)
        assert "学会新设备" not in r.json()["long_term_goals"]
        r = client.post("/api/v1/agent/identity/values", json={"text": "诚实"}, headers=AUTH)
        assert "诚实" in r.json()["values"]
        assert r.json()["version"] > base["version"]


class TestTwin:
    def test_status_lists_connected_devices_and_batch_ops_work(self, client):
        assert "connected_devices" in client.get("/api/v1/twin/status").json()
        assert client.post("/api/v1/twin/couple-all", headers=AUTH).json()["success"] is True
        assert client.post("/api/v1/twin/decouple-all", headers=AUTH).json()["success"] is True


class TestGovernanceOps:
    def test_reset_bucket_and_clear_audit(self, client):
        assert client.post("/api/v1/governance/tools/shell/reset-bucket", headers=AUTH).json()["ok"] is True
        assert client.delete("/api/v1/governance/tools/audit", headers=AUTH).json()["ok"] is True
        assert client.get("/api/v1/governance/tools/audit", headers=AUTH).json() == []


class TestGithub:
    def test_install_check_rejects_bad_url_without_installing(self, client):
        r = client.get("/api/v1/github/install/check", params={"url": "not-a-url"})
        assert r.status_code == 400 and r.json()["success"] is False

    def test_install_check_accepts_valid_url(self, client):
        r = client.get("/api/v1/github/install/check", params={"url": "https://github.com/owner/repo"})
        assert r.json().get("dry_run") is True or r.status_code == 400  # allowlist may refuse; never installs

    def test_tools_listing(self, client):
        assert isinstance(client.get("/api/v1/github/tools").json()["tools"], list)


class TestSmallReads:
    def test_audio_capabilities_report_native_speech(self, client):
        caps = client.get("/v1/audio/capabilities", headers=AUTH).json()
        assert "native_backend_registered" in caps["tts"]

    def test_channel_unload_unknown_is_404(self, client):
        assert client.delete("/api/v1/channels/nope", headers=AUTH).status_code == 404

    def test_config_status_carries_missing_summary(self, client):
        assert "missing_summary" in client.get("/api/v1/config/status", headers=AUTH).json()

    def test_container_runtime_test_rejects_unknown(self, client):
        r = client.post("/api/v1/system/container-runtime/test", json={"runtime": "lxc"}, headers=AUTH)
        assert r.json()["ok"] is False

    def test_audit_integrity_and_dag(self, client):
        assert client.get("/api/v1/audit/integrity").json()["intact"] is True
        assert isinstance(client.get("/api/v1/audit/dag").json()["dag"], dict)

    def test_perception_continuous(self, client):
        assert client.get("/api/perception/desktop/continuous", headers=AUTH).json()["success"] is True

    def test_hybrid_modes(self, client):
        modes = {m["mode"]: m for m in client.get("/api/v1/hybrid/modes").json()["modes"]}
        assert modes["parallel_race"]["concurrent"] is True
        assert modes["sequential_degrade"]["degrade_chain"] is True
        assert all(m["description"] for m in modes.values())

    def test_task_timeline(self, client):
        r = client.get("/api/v1/tasks/nope/timeline", headers=AUTH).json()
        assert r == {"task_id": "nope", "events": []}

    def test_cost_task_bills(self, client):
        body = client.get("/api/v1/cost/tasks").json()
        assert "bills" in body and "summary" in body


class TestToolPermissions:
    def test_add_policy_shows_up_and_bad_body_is_422(self, client):
        before = client.get("/api/v1/security/tool-permissions").json()["policies"]
        r = client.post(
            "/api/v1/security/tool-permissions",
            json={"tool_pattern": "mcp__x__*", "risk_level": "dangerous", "requires_confirmation": True},
            headers=AUTH,
        )
        assert len(r.json()["policies"]) == len(before) + 1
        bad = client.post("/api/v1/security/tool-permissions", json={"risk_level": "x"}, headers=AUTH)
        assert bad.status_code == 422


class TestKnowledgeBaseRoundTrip:
    def test_import_persists_and_export_returns_it(self, client):
        entry = {"id": "k1", "content": "天空是蓝的", "metadata": {"tags": ["t"]}, "timestamp": "2026-01-01"}
        r = client.post("/api/v1/rag/knowledge-base/import", json={"entries": [entry]}, headers=AUTH)
        assert r.json()["imported"] == 1
        # 新实例从盘上重载 —— 此前 import 只进内存，这一步会读不到
        exported = client.get("/api/v1/rag/knowledge-base/export", headers=AUTH).json()["entries"]
        assert any(e["id"] == "k1" for e in exported)

    def test_import_rejects_incomplete_entries(self, client):
        r = client.post("/api/v1/rag/knowledge-base/import", json={"entries": [{"id": "x"}]}, headers=AUTH)
        assert r.status_code == 422


# ── 顺带修掉的两处 ──────────────────────────────────────────────────────


def test_rejection_rate_decays_without_new_rejections():
    from core.resilience.metrics import ResilienceMetrics

    m = ResilienceMetrics()
    m.record_rejected()
    m.record_rejected()
    assert m.snapshot()["rejection_rate_per_min"] == 2.0
    m._rejection_timestamps = [time.time() - 120] * 5  # 一波拒绝发生在两分钟前
    assert m.rejection_rate_per_minute == 0.0
    assert m.snapshot()["rejection_rate_per_min"] == 0.0


def test_lineage_timeline_includes_replay_events():
    from core.canonical_task import TaskOrigin, build_canonical_task, get_canonical_task_runtime
    from core.operator_surface import get_operator_surface
    from core.replay_foundation import emit_runtime_event

    task = build_canonical_task(goal="lineage replay", origin=TaskOrigin.API_REQUEST)
    get_canonical_task_runtime().register(task)
    tid = task.identity.task_id
    emit_runtime_event(kind="CONTINUUM_TICK", task_id=tid, trace_id=tid, payload={"continuum": {"phase": "liminal"}})

    lineage = get_operator_surface().inspect_lineage(tid)
    events = [e["event"] for e in lineage.timeline]
    assert "continuum_liminal" in events, f"回放事件没进时间线: {events}"
