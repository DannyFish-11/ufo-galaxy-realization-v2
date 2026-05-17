"""
galaxy_gateway/android/handlers/mesh_lifecycle.py
==================================================
PR-13：Android Mesh 生命周期上行消息处理器

处理 Android GalaxyConnectionService.kt 在 ``parallel_subtask`` 路径中发出的
三类 mesh 生命周期消息：

* ``mesh_join``   — 设备请求加入 mesh 协作会话
* ``mesh_result`` — 设备上报 mesh 协作结果
* ``mesh_leave``  — 设备离开 mesh 协作会话

每个处理器均会：

1. 将事件落盘至 :mod:`core.mesh.android_mesh_lifecycle_store`（可追踪的运行时存储）。
2. 尝试将生命周期信号传递给 :class:`~core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator`
   （对应 create → activate → terminate 转换）。
3. 向 Android 设备返回结构化 ACK，携带 session_id、lifecycle_state 等字段。

兼容性
------
* wire value 与 Android 当前 AipModels.kt MsgType 保持对齐（``mesh_join`` /
  ``mesh_result`` / ``mesh_leave``），不要求 Android 侧重写协议。
* 所有外部依赖均以 ``try/except ImportError`` 保护，确保当依赖不可用时
  处理器仍能正常返回有效 ACK。

哨兵
----
:data:`MESH_LIFECYCLE_HANDLER_IS_CANONICAL_PR13`
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# PR-13 哨兵 — 权威性标识
MESH_LIFECYCLE_HANDLER_IS_CANONICAL_PR13: str = (
    "MESH_LIFECYCLE_HANDLER::CANONICAL_STATEFUL_PR13"
)

# ---------------------------------------------------------------------------
# 模块级导入（以 try/except 保护，确保在依赖不可用时模块仍可导入）
# 模块级导入的好处：测试可以通过 patch() 在模块层注入 mock。
# ---------------------------------------------------------------------------

try:
    from core.mesh.android_mesh_lifecycle_store import (
        record_mesh_join,
        record_mesh_result,
        record_mesh_leave,
        get_android_mesh_lifecycle_store,
    )
except ImportError:  # pragma: no cover
    record_mesh_join = None  # type: ignore[assignment]
    record_mesh_result = None  # type: ignore[assignment]
    record_mesh_leave = None  # type: ignore[assignment]
    get_android_mesh_lifecycle_store = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _get_lifecycle_coordinator() -> Optional[Any]:
    """返回 MeshSessionLifecycleCoordinator 单例，不可用时返回 ``None``。"""
    try:
        from core.mesh.mesh_session_lifecycle import get_lifecycle_coordinator
        return get_lifecycle_coordinator()
    except ImportError:
        logger.debug("MeshSessionLifecycleCoordinator 不可用（ImportError）")
        return None
    except Exception as exc:
        logger.debug("获取 MeshSessionLifecycleCoordinator 失败：%s", exc)
        return None


def _extract_session_id(message: Dict[str, Any]) -> Optional[str]:
    """从消息的多个候选字段中提取 session_id。

    优先级（高→低）：
    1. payload.session_id
    2. payload.mesh_session_id
    3. 顶层 message.session_id
    4. 顶层 message.mesh_session_id
    """
    payload = message.get("payload") or {}
    return (
        payload.get("session_id")
        or payload.get("mesh_session_id")
        or message.get("session_id")
        or message.get("mesh_session_id")
    )


# ---------------------------------------------------------------------------
# 处理器
# ---------------------------------------------------------------------------


async def handle_mesh_join(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """处理来自 Android 设备的 ``mesh_join`` 消息。

    步骤：

    1. 将事件落盘至 :mod:`core.mesh.android_mesh_lifecycle_store`。
    2. 将生命周期信号传递给 :class:`~core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator`
       （create_session / activate_session）。
    3. 返回携带 ``session_id`` 和 ``lifecycle_state=joining`` 的结构化 ACK。

    Parameters
    ----------
    bridge:
        :class:`~galaxy_gateway.android_bridge.AndroidBridge` 实例。
    websocket:
        WebSocket 连接句柄（保留，暂不使用）。
    message:
        规范化后的 AIP v3 消息字典。

    Returns
    -------
    dict
        发回 Android 设备的 ACK 响应。
    """
    device_id: str = message.get("device_id", "unknown")
    message_id: str = message.get("message_id") or str(uuid.uuid4())
    payload: Dict[str, Any] = message.get("payload") or {}
    raw_session_id: Optional[str] = _extract_session_id(message)

    logger.info(
        "MESH_JOIN 收到：device_id=%s raw_session_id=%s",
        device_id,
        raw_session_id,
    )

    # 1. 落盘至 android_mesh_lifecycle_store
    stored_session_id: Optional[str] = raw_session_id
    store_status = "stored"
    try:
        _record_fn = record_mesh_join
        if _record_fn is None:
            raise ImportError("record_mesh_join not available")
        event = _record_fn(
            device_id,
            session_id=raw_session_id,
            payload=payload,
            correlation_id=message_id,
        )
        if event:
            stored_session_id = event.session_id
    except Exception as store_exc:
        logger.warning(
            "MESH_JOIN store error（non-fatal）：device_id=%s error=%s",
            device_id,
            store_exc,
        )
        store_status = "store_error"

    session_id = stored_session_id or raw_session_id or f"amesh_{device_id}_{int(time.time() * 1000)}"

    # 2. 向 MeshSessionLifecycleCoordinator 传递信号
    lifecycle_record = None
    coordinator_available = False
    try:
        coordinator = _get_lifecycle_coordinator()
        if coordinator is not None:
            coordinator_available = True
            # 用轻量 dict 作为 session 对象（coordinator 可接受 dict）
            session_obj = {
                "session_id": session_id,
                "coordinator_id": f"android_mesh_{session_id}",
                "overall_status": "pending",
                "source_device_id": device_id,
                "mesh_join_payload": payload,
            }
            record = coordinator.create_session(
                session_obj,
                metadata={"origin": "android_mesh_join", "device_id": device_id},
            )
            if record:
                lifecycle_record = record.to_dict()
                # 立即 activate（join 等同于已开始参与）
                coordinator.activate_session(session_id)
    except Exception as coord_exc:
        logger.debug(
            "MESH_JOIN lifecycle coordinator error（non-fatal）：device_id=%s error=%s",
            device_id,
            coord_exc,
        )

    return {
        "version": "3.0",
        "type": "mesh_join_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "session_id": session_id,
        "lifecycle_state": "joining",
        "store_status": store_status,
        "coordinator_available": coordinator_available,
        "lifecycle_record": lifecycle_record,
        "correlation_id": message_id,
    }


async def handle_mesh_result(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """处理来自 Android 设备的 ``mesh_result`` 消息。

    步骤：

    1. 将事件（含结果 payload）落盘至 :mod:`core.mesh.android_mesh_lifecycle_store`。
    2. 向 :class:`~core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator`
       发送激活信号（session 进入或保持 active 状态）。
    3. 返回携带 ``session_id``、``result_count``、``lifecycle_state=active`` 的结构化 ACK。

    Parameters
    ----------
    bridge, websocket, message:
        同 :func:`handle_mesh_join`。

    Returns
    -------
    dict
    """
    device_id: str = message.get("device_id", "unknown")
    message_id: str = message.get("message_id") or str(uuid.uuid4())
    payload: Dict[str, Any] = message.get("payload") or {}
    raw_session_id: Optional[str] = _extract_session_id(message)

    logger.info(
        "MESH_RESULT 收到：device_id=%s raw_session_id=%s",
        device_id,
        raw_session_id,
    )

    # 1. 落盘至 android_mesh_lifecycle_store
    stored_session_id = raw_session_id
    result_count = 0
    store_status = "stored"
    try:
        _result_fn = record_mesh_result
        _store_fn = get_android_mesh_lifecycle_store
        if _result_fn is None:
            raise ImportError("record_mesh_result not available")
        event = _result_fn(
            device_id,
            session_id=raw_session_id,
            payload=payload,
            correlation_id=message_id,
        )
        if event:
            stored_session_id = event.session_id
        # 查询结果数量（供 ACK 使用）
        if _store_fn is not None:
            store = _store_fn()
            session_rec = store.get_session(stored_session_id or "")
            if session_rec:
                result_count = len(session_rec.result_events)
    except Exception as store_exc:
        logger.warning(
            "MESH_RESULT store error（non-fatal）：device_id=%s error=%s",
            device_id,
            store_exc,
        )
        store_status = "store_error"

    session_id = stored_session_id or raw_session_id or f"amesh_{device_id}_{int(time.time() * 1000)}"

    # 2. 向 MeshSessionLifecycleCoordinator 传递激活信号
    coordinator_available = False
    try:
        coordinator = _get_lifecycle_coordinator()
        if coordinator is not None:
            coordinator_available = True
            coordinator.activate_session(session_id)
    except Exception as coord_exc:
        logger.debug(
            "MESH_RESULT lifecycle coordinator error（non-fatal）：device_id=%s error=%s",
            device_id,
            coord_exc,
        )

    return {
        "version": "3.0",
        "type": "mesh_result_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "session_id": session_id,
        "lifecycle_state": "active",
        "result_count": result_count,
        "store_status": store_status,
        "coordinator_available": coordinator_available,
        "correlation_id": message_id,
    }


async def handle_mesh_leave(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """处理来自 Android 设备的 ``mesh_leave`` 消息。

    步骤：

    1. 将 leave 事件落盘至 :mod:`core.mesh.android_mesh_lifecycle_store`。
    2. 向 :class:`~core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator`
       发送 terminate 信号（session 进入 completed/cancelled 状态）。
    3. 返回携带 ``session_id``、``lifecycle_state=left`` 的结构化 ACK。

    Parameters
    ----------
    bridge, websocket, message:
        同 :func:`handle_mesh_join`。

    Returns
    -------
    dict
    """
    device_id: str = message.get("device_id", "unknown")
    message_id: str = message.get("message_id") or str(uuid.uuid4())
    payload: Dict[str, Any] = message.get("payload") or {}
    raw_session_id: Optional[str] = _extract_session_id(message)

    logger.info(
        "MESH_LEAVE 收到：device_id=%s raw_session_id=%s",
        device_id,
        raw_session_id,
    )

    # 1. 落盘至 android_mesh_lifecycle_store
    stored_session_id = raw_session_id
    store_status = "stored"
    try:
        _leave_fn = record_mesh_leave
        if _leave_fn is None:
            raise ImportError("record_mesh_leave not available")
        event = _leave_fn(
            device_id,
            session_id=raw_session_id,
            payload=payload,
            correlation_id=message_id,
        )
        if event:
            stored_session_id = event.session_id
    except Exception as store_exc:
        logger.warning(
            "MESH_LEAVE store error（non-fatal）：device_id=%s error=%s",
            device_id,
            store_exc,
        )
        store_status = "store_error"

    session_id = stored_session_id or raw_session_id or f"amesh_{device_id}_{int(time.time() * 1000)}"

    # 2. 向 MeshSessionLifecycleCoordinator 传递终止信号
    coordinator_available = False
    try:
        coordinator = _get_lifecycle_coordinator()
        if coordinator is not None:
            coordinator_available = True
            leave_reason = str(payload.get("reason") or "mesh_leave")
            coordinator.terminate_session(
                session_id,
                outcome="completed",
                reason=leave_reason,
            )
    except Exception as coord_exc:
        logger.debug(
            "MESH_LEAVE lifecycle coordinator error（non-fatal）：device_id=%s error=%s",
            device_id,
            coord_exc,
        )

    return {
        "version": "3.0",
        "type": "mesh_leave_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "session_id": session_id,
        "lifecycle_state": "left",
        "store_status": store_status,
        "coordinator_available": coordinator_available,
        "correlation_id": message_id,
    }
