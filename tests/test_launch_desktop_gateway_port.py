from __future__ import annotations

import launch_desktop as ld


def test_gateway_health_url_uses_resolved_port(monkeypatch):
    monkeypatch.setattr(ld, "resolve_gateway_port", lambda: 9321)
    assert ld.get_gateway_health_url().endswith(":9321/health")


def test_start_gateway_backend_passes_resolved_port(monkeypatch, tmp_path):
    monkeypatch.setattr(ld, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(ld, "resolve_gateway_port", lambda: 9444)

    captured = {}

    class _Proc:
        def __init__(self):
            self.pid = 12345
            self.returncode = None

    def _fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return _Proc()

    monkeypatch.setattr(ld.subprocess, "Popen", _fake_popen)
    proc = ld.start_gateway_backend()
    assert proc.pid == 12345
    assert "--port" in captured["cmd"]
    assert "9444" in captured["cmd"]
    assert captured["env"]["PORT"] == "9444"
    assert captured["env"]["GALAXY_GATEWAY_PORT"] == "9444"
