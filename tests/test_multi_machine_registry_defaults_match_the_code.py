"""多机模式相关的数字 / 取值：登记表的默认值必须等于代码里读它的那一处的默认值。

「保存设置」把登记表里每个非空默认整体写进 ``.env``。登记成与代码不同的值，保存一次，
行为就悄悄变了（主脑缩放复评间隔 15 秒 → 300 秒、设备心跳 10 秒 → 5 秒……），没有任何人点过它。
读取点在哪个文件、默认写的什么，这里直接从源码里读，不再抄一份数字。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.routes.config_schema_registry import CONFIG_SCHEMA

REPO = Path(__file__).resolve().parent.parent

READ_SITES = {
    "GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S": "core/master_brain.py",
    "GALAXY_HEARTBEAT_INTERVAL": "core/nats_heartbeat.py",
    "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS": "core/android_device_state_store.py",
    "FEDERATION_HEARTBEAT_INTERVAL": "core/galaxy_federation.py",
    "GALAXY_SLO_HEARTBEAT_WINDOW": "core/slo_metrics.py",
    "GALAXY_TAILSCALE_CHECK_INTERVAL": "core/tailscale_manager.py",
    # 这一轮才登记的那批（core/routes/config_schema_multimachine.py）：默认同样抄自读取点
    "FEDERATION_MIN_HEARTBEAT_INTERVAL": "core/galaxy_federation.py",
    "FEDERATION_OFFLINE_THRESHOLD": "core/galaxy_federation.py",
    "GALAXY_WEBRTC_TASK_READY_TIMEOUT_S": "galaxy_gateway/webrtc_proxy.py",
    "GALAXY_HOLE_PUNCH_TIMEOUT_S": "galaxy_gateway/webrtc_proxy.py",
    "GALAXY_MESH_PORT": "galaxy_gateway/bootstrap/lifecycle.py",
    "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT": "galaxy_gateway/device_router.py",
}


def _code_default(key: str, rel: str) -> float:
    src = (REPO / rel).read_text(encoding="utf-8")
    m = re.search(rf"""["']{key}["']\s*,\s*["']([0-9.]+)["']""", src)
    assert m, f"{rel} 里找不到 {key} 的读取点(文件改了结构?这条测试要跟着改)"
    return float(m.group(1))


@pytest.mark.parametrize("key,rel", sorted(READ_SITES.items()))
def test_the_registry_default_is_the_default_the_code_runs_with(key, rel):
    assert float(CONFIG_SCHEMA[key]["default"]) == _code_default(key, rel), (
        f"{key}: 登记表写 {CONFIG_SCHEMA[key]['default']}，{rel} 里读它的默认是 {_code_default(key, rel):g} —— "
        "「保存设置」会把登记值写进 .env，悄悄改掉代码默认"
    )


def test_the_description_does_not_state_a_different_default():
    for key in READ_SITES:
        default = CONFIG_SCHEMA[key]["default"]
        desc = CONFIG_SCHEMA[key]["description"]
        for m in re.finditer(r"默认\s*([0-9.]+)", desc):
            assert m.group(1) == default, f"{key} 的说明写「默认 {m.group(1)}」，登记默认是 {default}"


def test_the_headscale_user_default_was_never_wrong():
    """清点时它曾被记成「登记 galaxy / 代码 空」:代码写的是 ``getenv(..., "").strip() or "galaxy"``,有效默认就是 galaxy。"""
    src = (REPO / "core/headscale_join.py").read_text(encoding="utf-8")
    assert re.search(r'GALAXY_HEADSCALE_USER["\'],\s*["\']["\']\)\.strip\(\)\s*or\s*["\']galaxy["\']', src)
    assert CONFIG_SCHEMA["GALAXY_HEADSCALE_USER"]["default"] == "galaxy"
