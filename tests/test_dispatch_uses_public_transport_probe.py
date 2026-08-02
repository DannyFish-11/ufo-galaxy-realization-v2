"""派发编排器不得伸手进 AndroidBridge 的私有传输缓存。

## 修的是什么(P3-3 第三处)

``core/runtime/source_dispatch_orchestrator.py`` 在决定"要不要走 Android bridge
派发"时,原先直接写:

    if device_id not in _bridge._devices:

**这个判断本身是对的** —— 派发前确认传输层可达,不可达就回退到 remote handoff
(见同文件的 ``ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY``
哨兵)。而且它读的确实是"传输层活性"而非设备真相,注释里也写明了。

错的是**跨层伸手拿别人的私有属性**:``_devices`` 属于 ``galaxy_gateway`` 里的
AndroidBridge,``core/runtime`` 是另一层。那个字段一旦改名或换结构,本模块会在
运行时才炸,而且炸在一个与它无关的地方 —— 没有任何静态检查会提前发现。

改为 bridge 提供的公开读口 ``has_transport_session(device_id)``,语义严格限定为
"现在有没有一条连着的 Android WebSocket 会话",与 ``cache_transport_handle``
配对。

## 不在本次范围内的

``galaxy_gateway/android/handlers/*`` 里还有多处 ``bridge._devices`` 直读。那是
**bridge 自己的子包读自己的缓存**,属包内封装的正常范围,与"跨层伸手"不是一回事,
不在这次收口范围里。这里把跨层那条边界钉死。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO_ROOT / "core" / "runtime" / "source_dispatch_orchestrator.py"


def test_bridge_exposes_a_public_transport_probe():
    """公开读口必须存在,且语义是布尔判定。"""
    from galaxy_gateway.android_bridge import AndroidBridge

    assert hasattr(AndroidBridge, "has_transport_session"), "AndroidBridge 缺少公开的传输层活性读口"

    bridge = AndroidBridge()
    assert bridge.has_transport_session("no-such-device-anywhere") is False


def test_probe_reflects_the_transport_cache():
    """读口必须真的反映缓存内容,而不是恒为 False。

    没有这条,一个 ``return False`` 的空实现也能让上面那条通过 —— 而那会让
    Android 派发**永远**走不通(全部回退到 remote handoff),是比原 bug 更糟的
    静默降级。
    """
    from galaxy_gateway.android_bridge import AndroidBridge, AndroidDevice

    bridge = AndroidBridge()
    device_id = "transport-probe-fixture"
    assert bridge.has_transport_session(device_id) is False

    bridge.cache_transport_handle(device_id, AndroidDevice(device_id=device_id))
    try:
        assert bridge.has_transport_session(device_id) is True, "缓存里明明有,读口却说没有"
    finally:
        bridge._devices.pop(device_id, None)


def test_orchestrator_does_not_reach_into_bridge_private_devices():
    """跨层边界:``core/runtime`` 不得出现 ``<bridge>._devices`` 的属性访问。

    用 AST 找属性访问,而不是 grep 字符串 —— 文件里的注释如实记录了旧写法
    (那是有意保留的病历),grep 会把注释也算进去。
    """
    tree = ast.parse(ORCHESTRATOR.read_text(encoding="utf-8"))

    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_devices":
            offenders.append(node.lineno)

    assert not offenders, (
        f"{ORCHESTRATOR.relative_to(REPO_ROOT)} 又直接访问 bridge 的私有 `_devices` 了"
        f"(行 {offenders})—— 请改用 AndroidBridge.has_transport_session()"
    )


def test_orchestrator_actually_calls_the_public_probe():
    """反面:不能为了让上面那条通过,把整个传输层判断**删掉**。

    删掉的后果是 Android 设备无论连没连都走 bridge 派发,失败才被发现 ——
    而 PR-E 的策略正是"派发前先确认可达,不可达就回退"。
    """
    src = ORCHESTRATOR.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))

    assert "has_transport_session(" in code, "编排器不再做传输层活性判断了 —— PR-E 的「派发前先确认可达」策略被删掉了"
