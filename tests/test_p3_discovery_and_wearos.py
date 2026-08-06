"""P3 回归:wearos 设备类型解析 + /api/v1/config 发现信息。

锁死:手表实发的 "wearos" 不再掉进 CUSTOM(归 ANDROID,与 android_wear 一致);
config 端点吐出 mDNS/Tailscale/配对路径,让客户端【从服务端拿】而非硬编码。
"""

from core.device_types import DeviceType, resolve_device_type


def test_wearos_resolves_to_android_not_custom():
    assert resolve_device_type("wearos") == DeviceType.ANDROID
    assert resolve_device_type("wear_os") == DeviceType.ANDROID
    assert resolve_device_type("wear") == DeviceType.ANDROID
    # 与规范 AIP 值一致
    assert resolve_device_type("android_wear") == DeviceType.ANDROID


def test_alias_does_not_break_known_types():
    assert resolve_device_type("android_phone") == DeviceType.ANDROID
    assert resolve_device_type("windows") == DeviceType.WINDOWS
    assert resolve_device_type("linux_server") == DeviceType.LINUX
    assert resolve_device_type("totally-unknown-xyz") == DeviceType.CUSTOM


def test_client_config_exposes_discovery():
    from galaxy_gateway.api.config import build_client_config

    cfg = build_client_config()
    disc = cfg["discovery"]
    assert disc["mdns_service"] == "_galaxy._tcp"
    assert "mdns_enabled" in disc
    assert disc["tailscale"]["network_layer"] == "tailscale"
    # 配对流程路径可被客户端直接使用(去硬编码)。
    # 这里顺带钉住"发现广告的路径必须真的挂着" —— 广告一条 404 出去,
    # 设备侧收到的是"配对功能坏了",而桌面这边一切正常,没人会去查发现接口。
    from core.routes.pairing import create_router

    mounted = {r.path for r in create_router().routes}
    for key in ("claim_path", "card_path", "paths_path"):
        assert disc["pairing"][key] in mounted, f"discovery 广告了未挂载的路径:{key}"
    assert disc["pairing"]["claim_path"] == "/api/v1/pair/claim"
