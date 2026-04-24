"""
galaxy_gateway/android/message_builder.py — AIP v3 message construction.

Extracted from android_bridge.py as part of PR-3 modularization.
Provides the ``MessageBuilder`` class, aligned with AIPMessageV3.kt's MessageBuilder.
"""

import time
import uuid
from typing import Any, Dict, Optional

from galaxy_gateway.protocol.aip_v3 import MessageType


class MessageBuilder:
    """消息构建器 - 与 AIPMessageV3.kt 的 MessageBuilder 对齐"""

    PROTOCOL_VERSION = "3.0"

    @classmethod
    def _base_message(cls, msg_type: MessageType, device_id: str) -> Dict[str, Any]:
        return {
            "version": cls.PROTOCOL_VERSION,
            "type": msg_type.value,
            "message_id": str(uuid.uuid4()),
            "device_id": device_id,
            "timestamp": int(time.time() * 1000),
        }

    @classmethod
    def device_register_ack(cls, device_id: str, success: bool,
                            session_id: Optional[str] = None,
                            message: Optional[str] = None) -> Dict[str, Any]:
        """设备注册确认"""
        msg = cls._base_message(MessageType.DEVICE_REGISTER_ACK, device_id)
        msg["success"] = success
        if session_id:
            msg["session_id"] = session_id
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def heartbeat_ack(cls, device_id: str) -> Dict[str, Any]:
        """心跳确认"""
        return cls._base_message(MessageType.DEVICE_HEARTBEAT_ACK, device_id)

    @classmethod
    def task_assign(cls, device_id: str, task_id: str, task_type: str,
                    payload: Dict[str, Any], priority: int = 5,
                    timeout: int = 300,
                    trace_id: Optional[str] = None) -> Dict[str, Any]:
        """分配任务

        Parameters
        ----------
        trace_id:
            Optional distributed trace identifier.  When provided it is
            stamped as a top-level field on the AIP message for end-to-end
            observability.  It is also accessible inside the ``payload``
            dict when embedded there by the orchestrator dispatch path.
        """
        msg = cls._base_message(MessageType.TASK_ASSIGN, device_id)
        msg["task_id"] = task_id
        msg["task_type"] = task_type
        msg["payload"] = payload
        msg["priority"] = priority
        msg["timeout"] = timeout
        if trace_id:
            msg["trace_id"] = trace_id
        return msg

    @classmethod
    def task_cancel_ack(cls, device_id: str, task_id: Optional[str],
                        cancelled: bool, reason: Optional[str] = None,
                        correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """取消任务确认"""
        msg = cls._base_message(MessageType.TASK_CANCEL_ACK, device_id)
        msg["task_id"] = task_id
        msg["cancelled"] = cancelled
        if reason:
            msg["reason"] = reason
        if correlation_id:
            msg["correlation_id"] = correlation_id
        return msg

    @classmethod
    def task_status_response(cls, device_id: str, task_id: Optional[str],
                             status: str, progress: Optional[float] = None,
                             correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """任务状态查询响应"""
        msg = cls._base_message(MessageType.TASK_STATUS_RESPONSE, device_id)
        msg["task_id"] = task_id
        msg["status"] = status
        if progress is not None:
            msg["progress"] = progress
        if correlation_id:
            msg["correlation_id"] = correlation_id
        return msg

    @classmethod
    def goal_execution_result(cls, device_id: str, payload: Dict[str, Any],
                              correlation_id: Optional[str] = None,
                              trace_id: Optional[str] = None) -> Dict[str, Any]:
        """goal_execution / parallel_subtask 结果回传（Android → Gateway）"""
        msg = cls._base_message(MessageType.GOAL_EXECUTION_RESULT, device_id)
        msg["payload"] = payload
        if correlation_id:
            msg["correlation_id"] = correlation_id
        if trace_id:
            msg["trace_id"] = trace_id
        return msg

    @classmethod
    def task_progress(cls, device_id: str, task_id: str,
                      progress: float, step: int = 0,
                      message: str = "") -> Dict[str, Any]:
        """任务进度上报"""
        msg = cls._base_message(MessageType.TASK_PROGRESS, device_id)
        msg["task_id"] = task_id
        msg["progress"] = progress
        msg["step"] = step
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def gui_click(cls, device_id: str, x: int, y: int,
                  element_id: Optional[str] = None) -> Dict[str, Any]:
        """GUI 点击命令"""
        msg = cls._base_message(MessageType.GUI_CLICK, device_id)
        msg["x"] = x
        msg["y"] = y
        if element_id:
            msg["element_id"] = element_id
        return msg

    @classmethod
    def gui_swipe(cls, device_id: str, start_x: int, start_y: int,
                  end_x: int, end_y: int, duration_ms: int = 300) -> Dict[str, Any]:
        """GUI 滑动命令"""
        msg = cls._base_message(MessageType.GUI_SWIPE, device_id)
        msg["start_x"] = start_x
        msg["start_y"] = start_y
        msg["end_x"] = end_x
        msg["end_y"] = end_y
        msg["duration_ms"] = duration_ms
        return msg

    @classmethod
    def gui_input(cls, device_id: str, text: str,
                  element_id: Optional[str] = None,
                  clear_first: bool = False) -> Dict[str, Any]:
        """GUI 输入命令"""
        msg = cls._base_message(MessageType.GUI_INPUT, device_id)
        msg["text"] = text
        if element_id:
            msg["element_id"] = element_id
        msg["clear_first"] = clear_first
        return msg

    @classmethod
    def gui_screenshot(cls, device_id: str, quality: int = 80,
                       scale: float = 1.0) -> Dict[str, Any]:
        """GUI 截图命令"""
        msg = cls._base_message(MessageType.GUI_SCREENSHOT, device_id)
        msg["quality"] = quality
        msg["scale"] = scale
        return msg

    @classmethod
    def gui_element_query(cls, device_id: str,
                          text: Optional[str] = None,
                          class_name: Optional[str] = None,
                          view_id: Optional[str] = None,
                          content_description: Optional[str] = None) -> Dict[str, Any]:
        """GUI 元素查询"""
        msg = cls._base_message(MessageType.GUI_ELEMENT_QUERY, device_id)
        if text:
            msg["text"] = text
        if class_name:
            msg["class_name"] = class_name
        if view_id:
            msg["view_id"] = view_id
        if content_description:
            msg["content_description"] = content_description
        return msg

    @classmethod
    def command(cls, device_id: str, command_type: str,
                params: Dict[str, Any]) -> Dict[str, Any]:
        """通用命令"""
        msg = cls._base_message(MessageType.COMMAND, device_id)
        msg["command_type"] = command_type
        msg["params"] = params
        return msg

    @classmethod
    def error(cls, device_id: str, error_code: str,
              error_message: str, details: Optional[Dict] = None,
              correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """错误消息"""
        msg = cls._base_message(MessageType.ERROR, device_id)
        msg["error_code"] = error_code
        msg["error_message"] = error_message
        if details:
            msg["details"] = details
        if correlation_id:
            msg["correlation_id"] = correlation_id
        return msg

    @classmethod
    def capability_report_ack(cls, device_id: str, accepted: bool = True,
                              message: Optional[str] = None) -> Dict[str, Any]:
        """能力上报确认"""
        msg = cls._base_message(MessageType.CAPABILITY_REPORT_ACK, device_id)
        msg["accepted"] = accepted
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def diagnostics_payload_ack(cls, device_id: str, accepted: bool = True,
                                message: Optional[str] = None) -> Dict[str, Any]:
        """诊断数据确认"""
        msg = cls._base_message(MessageType.DIAGNOSTICS_PAYLOAD_ACK, device_id)
        msg["accepted"] = accepted
        if message:
            msg["message"] = message
        return msg

    @classmethod
    def vision_result(cls, device_id: str, task_id: str,
                      result: Dict[str, Any]) -> Dict[str, Any]:
        """视觉分析结果（以 task_assign 形式下发操作指令）"""
        return cls.task_assign(
            device_id=device_id,
            task_id=task_id,
            task_type="vision_action",
            payload=result,
        )

    @classmethod
    def handoff_envelope_v2(
        cls,
        device_id: str,
        envelope: Any,
        *,
        priority: int = 5,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Build an AIP v3 ``handoff_envelope_v2`` message for Android (canonical).

        This is the canonical downlink builder, aligned with
        ``AipModels.HANDOFF_ENVELOPE_V2("handoff_envelope_v2")`` on the Android
        side.  Use this method for all new handoff downlink sends.

        Parameters
        ----------
        device_id:
            Target Android device identifier.
        envelope:
            A :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` instance.
        priority:
            AIP message priority (1-10).  Defaults to 5.
        timeout:
            Expected execution timeout in seconds.  Defaults to 300.

        Returns
        -------
        dict
            AIP v3 ``handoff_envelope_v2`` message.
        """
        return envelope.to_android_task_assign_payload(
            device_id,
            task_type="handoff_v2",
            priority=priority,
            timeout=timeout,
        )

    @classmethod
    def handoff_dispatch(
        cls,
        device_id: str,
        envelope: Any,
        *,
        priority: int = 5,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Build an AIP v3 handoff message for Android.

        .. deprecated::
            Use :meth:`handoff_envelope_v2` instead.  This method is kept for
            backward compatibility and now delegates to
            :meth:`handoff_envelope_v2`, which emits the canonical
            ``handoff_envelope_v2`` wire type expected by Android.

        Parameters
        ----------
        device_id:
            Target Android device identifier.
        envelope:
            A :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` instance.
        priority:
            AIP message priority (1-10).  Defaults to 5.
        timeout:
            Expected execution timeout in seconds.  Defaults to 300.

        Returns
        -------
        dict
            AIP v3 ``handoff_envelope_v2`` message.
        """
        return cls.handoff_envelope_v2(
            device_id,
            envelope,
            priority=priority,
            timeout=timeout,
        )
