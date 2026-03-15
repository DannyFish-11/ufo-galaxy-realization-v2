"""
Device Router - 设备路由和任务分发模块

负责将用户命令路由到正确的设备执行，支持多设备协同任务。

数据流说明
----------
此模块是 ``galaxy_gateway/main.py`` 和 ``websocket_handler.py`` 使用的路由层。
设备注册状态由 :class:`DeviceRouter` 维护（运行时 WebSocket 连接表），
仅在连接活跃期间有效。

内部消息处理使用 AIP v3 标准字段；向设备发送的命令也使用 AIP v3 格式。
接入层（``websocket_handler.py``）负责通过 compat 层将所有 incoming 消息
规范化为 v3 格式后再传入此模块。

标准端点（参见 galaxy_gateway/app.py）
--------------------------------------
- WebSocket : ``/ws/device/{device_id}`` (primary), ``/ws/android`` (initial)
- REST      : ``/api/v1/devices/*``

Author: Manus AI
Version: 2.0
Date: 2026-03-07
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Cross-device feature-flag (Round 4) — checked before any cross-device path.
from galaxy_gateway.cross_device_switch import (  # noqa: E402
    is_cross_device_enabled,
    make_disabled_response,
)

# 延迟导入以避免循环依赖
cross_device_coordinator = None

def get_cross_device_coordinator():
    global cross_device_coordinator
    if cross_device_coordinator is None:
        from galaxy_gateway.cross_device_coordinator import cross_device_coordinator as cdc
        cross_device_coordinator = cdc
    return cross_device_coordinator


from core.device_types import DeviceType, resolve_device_type  # noqa: E402

# Module-level import so the function can be patched in tests
from galaxy_gateway.capability_registry import get_gateway_capability_registry  # noqa: E402


def map_device_type_to_platform(aip_device_type: str) -> str:
    """将 AIP v3 DeviceType 字符串映射为路由层平台大类（公共接口）。

    Example::

        >>> map_device_type_to_platform("android_phone")
        'android'
        >>> map_device_type_to_platform("windows_desktop")
        'windows'
    """
    return resolve_device_type(aip_device_type).value


class TaskType:
    """任务类型"""
    UI_AUTOMATION = "ui_automation"
    APP_CONTROL = "app_control"
    SYSTEM_CONTROL = "system_control"
    QUERY = "query"
    COMPOUND = "compound"
    CROSS_DEVICE = "cross_device"


class Device:
    """设备信息 — gateway 运行时包装层。

    内部使用 core.schemas.device.DeviceModel 存储设备数据，
    额外维护 WebSocket 连接引用（不可序列化，不放入 Pydantic 模型）。
    ``metadata`` 存储设备注册时上报的任意扩展字段（如自主执行能力标志）。
    """

    def __init__(
        self,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ):
        from core.schemas.device import DeviceModel, DeviceCapabilityModel
        from core.device_types import DeviceStatus

        cap_models = [DeviceCapabilityModel(name=c) for c in capabilities]
        self._model = DeviceModel(
            device_id=device_id,
            device_type=device_type,
            name=device_id,
            status=DeviceStatus.ONLINE,
            capabilities=cap_models,
        )
        self.websocket = None
        # Free-form metadata dict (e.g. goal_execution_enabled, device_role)
        self.metadata: Dict[str, Any] = metadata or {}

    @property
    def device_id(self) -> str:
        return self._model.device_id

    @property
    def device_type(self) -> str:
        return self._model.device_type.value

    @property
    def capabilities(self) -> List[str]:
        return self._model.capability_names()

    @property
    def status(self) -> str:
        return self._model.status.value

    @status.setter
    def status(self, value: str) -> None:
        from core.device_types import DeviceStatus
        try:
            self._model.status = DeviceStatus(value.lower())
        except ValueError:
            self._model.status = DeviceStatus.UNKNOWN

    @property
    def last_seen(self) -> datetime:
        return datetime.fromtimestamp(self._model.last_seen)

    @last_seen.setter
    def last_seen(self, value: datetime) -> None:
        self._model.last_seen = value.timestamp()

    def to_dict(self) -> Dict[str, Any]:
        d = self._model.to_api_dict()
        d["last_seen"] = datetime.fromtimestamp(self._model.last_seen).isoformat()
        return d


class DeviceRouter:
    """设备路由器"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.task_queue: Dict[str, Dict] = {}
        self.task_results: Dict[str, Dict] = {}
        self._task_events: Dict[str, asyncio.Event] = {}
        # Idempotency: seen task-result IDs.
        self._seen_task_result_ids: set = set()
    
    def register_device(self, device_id: str, device_type: str,
                       capabilities: List[str], websocket=None,
                       metadata: Optional[Dict[str, Any]] = None) -> bool:
        """注册设备"""
        try:
            device = Device(device_id, device_type, capabilities, metadata=metadata)
            device.websocket = websocket
            self.devices[device_id] = device

            # 同步设备能力到 CapabilityRegistry
            try:
                from core.routes.devices import _sync_device_to_capability_registry
                device_info = {
                    "device_id": device_id,
                    "device_type": device_type,
                    "device_name": device_id,
                    "capabilities": capabilities,
                }
                _sync_device_to_capability_registry(device_info)
            except Exception as _sync_err:
                logger.warning(f"设备能力同步到 CapabilityRegistry 失败（不影响注册）: {_sync_err}")

            logger.info(f"✅ 设备注册成功: {device_id} ({device_type})")
            return True
            
        except Exception as e:
            logger.error(f"❌ 设备注册失败: {e}")
            return False
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备，同时清理 GatewayCapabilityRegistry 中的能力记录。"""
        try:
            if device_id in self.devices:
                del self.devices[device_id]

                # Purge capabilities from GatewayCapabilityRegistry
                try:
                    purged = get_gateway_capability_registry().purge(device_id)
                    logger.debug(
                        "unregister_device: purged %d capabilities for device %s",
                        purged,
                        device_id,
                    )
                except Exception as _purge_err:
                    logger.warning(
                        "unregister_device: capability registry purge failed: %s", _purge_err
                    )

                logger.info(f"✅ 设备注销成功: {device_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"❌ 设备注销失败: {e}")
            return False
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_devices_by_type(self, device_type: str) -> List[Device]:
        """根据类型获取设备列表"""
        return [d for d in self.devices.values() if d.device_type == device_type]
    
    def get_devices_by_capability(self, capability: str) -> List[Device]:
        """根据能力获取设备列表"""
        return [d for d in self.devices.values() if capability in d.capabilities]
    
    async def route_task(self, command: str, context: Dict = None) -> Dict:
        """
        路由任务到合适的设备
        
        Args:
            command: 用户命令
            context: 上下文信息
        
        Returns:
            任务执行结果
        """
        try:
            logger.info(f"🎯 开始路由任务: {command}")
            
            # 1. 分析命令，确定目标设备和任务类型
            analysis = await self._analyze_command(command, context)
            
            # 2. 判断是否需要跨设备协同
            if analysis.get("requires_cross_device", False):
                # --- Round 4: hard constraint — check cross-device switch ---
                if not is_cross_device_enabled():
                    trace_id = (context or {}).get("trace_id")
                    return make_disabled_response(trace_id=trace_id)

                # --- Round 5: Agent Bridge handoff ---
                # Try delegating to the agent runtime before falling back to the
                # local cross-device coordinator.
                try:
                    from galaxy_gateway.agent_bridge import (
                        AgentBridge,
                        HandoffContract,
                        get_agent_bridge,
                    )

                    ctx = context or {}
                    bridge = get_agent_bridge()
                    # Only attempt handoff when the bridge is configured and enabled.
                    if bridge._config.enabled:
                        trace_id = ctx.get("trace_id") or str(uuid.uuid4())
                        contract = HandoffContract(
                            trace_id=trace_id,
                            task={
                                "command": command,
                                "analysis": analysis,
                                "context": ctx,
                            },
                            capability=analysis.get("task_type", ""),
                            exec_mode=analysis.get("exec_mode", "both"),
                            route_mode=ctx.get("route_mode", "direct"),
                            session=ctx.get("session", {}),
                            callback_channel=ctx.get("callback_channel", "ws"),
                        )

                        async def _local_coordinator_fallback(task: dict) -> dict:
                            coordinator = get_cross_device_coordinator()
                            return await coordinator.execute_cross_device_task(
                                task.get("command", command),
                                task.get("context", ctx),
                            )

                        return await bridge.handoff(
                            contract=contract,
                            local_fallback=_local_coordinator_fallback,
                        )
                except Exception as _bridge_err:
                    logger.warning(
                        "agent_bridge_import_error trace_id=%s error=%s; using coordinator",
                        (context or {}).get("trace_id", ""),
                        _bridge_err,
                    )

                # Use cross-device coordinator (fallback when bridge import failed)
                coordinator = get_cross_device_coordinator()
                return await coordinator.execute_cross_device_task(command, context)
            
            # 3. 选择合适的设备
            target_devices = self._select_devices(analysis)
            
            if not target_devices:
                return {
                    "success": False,
                    "error": "没有可用的设备执行此任务"
                }
            
            # 3. 创建任务
            task = self._create_task(command, analysis, target_devices)
            
            # 4. 分发任务
            if len(target_devices) == 1:
                # 单设备任务
                result = await self.dispatch_task(task, target_devices[0])
            else:
                # 多设备协同任务
                result = await self._dispatch_cross_device_task(task, target_devices)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 任务路由失败: {e}")
            return {
                "success": False,
                "error": f"任务路由失败: {str(e)}"
            }
    
    async def _analyze_command(self, command: str, context: Dict = None) -> Dict:
        """
        分析命令，确定目标设备和任务类型
        
        这里使用简单的关键词匹配
        实际应该调用 NLU 引擎进行深度分析
        """
        analysis = {
            "command": command,
            "target_device_type": DeviceType.UNKNOWN,
            "task_type": TaskType.UI_AUTOMATION,
            "actions": [],
            "requires_cross_device": False
        }
        
        command_lower = command.lower()
        
        # 判断目标设备
        if any(keyword in command_lower for keyword in ["手机", "android", "移动端", "app"]):
            analysis["target_device_type"] = DeviceType.ANDROID
        elif any(keyword in command_lower for keyword in ["电脑", "pc", "windows", "桌面"]):
            analysis["target_device_type"] = DeviceType.WINDOWS
        elif any(keyword in command_lower for keyword in ["平板", "ipad", "tablet"]):
            analysis["target_device_type"] = DeviceType.IOS
        
        # 判断任务类型
        if any(keyword in command_lower for keyword in ["打开", "启动", "运行"]):
            analysis["task_type"] = TaskType.APP_CONTROL
            analysis["actions"].append("open")
        elif any(keyword in command_lower for keyword in ["点击", "按", "选择"]):
            analysis["task_type"] = TaskType.UI_AUTOMATION
            analysis["actions"].append("click")
        elif any(keyword in command_lower for keyword in ["输入", "填写", "写入"]):
            analysis["task_type"] = TaskType.UI_AUTOMATION
            analysis["actions"].append("input")
        elif any(keyword in command_lower for keyword in ["查询", "查看", "显示"]):
            analysis["task_type"] = TaskType.QUERY
            analysis["actions"].append("query")
        elif any(keyword in command_lower for keyword in ["音量", "亮度", "wifi", "蓝牙"]):
            analysis["task_type"] = TaskType.SYSTEM_CONTROL
        
        # 判断是否需要跨设备协同
        if any(keyword in command_lower for keyword in ["复制到", "发送到", "传输到", "同步"]):
            analysis["requires_cross_device"] = True
        
        return analysis
    
    def _select_devices(self, analysis: Dict) -> List[Device]:
        """选择合适的设备（优先选择自主执行能力的设备），并尊重 exec_mode。

        exec_mode 路由语义（Round 3）
        ------------------------------
        ``analysis["exec_mode"]`` 可由调用方（如编排器、NLU）设置：

        - ``"local"``  — 只选择注册了对应动作且 exec_mode=local/both 的设备。
        - ``"remote"`` — 只选择注册了对应动作且 exec_mode=remote/both 的设备。
        - ``"both"``   — 不按 exec_mode 额外过滤（默认行为）。
        - 缺失         — 等同于 "both"（向后兼容）。

        若 GatewayCapabilityRegistry 不可用或设备尚未上报 capability_report，
        则退回到原有逻辑，保证向后兼容。
        """
        target_device_type = analysis["target_device_type"]

        if target_device_type == DeviceType.UNKNOWN:
            # 如果未指定设备，默认选择 Windows
            target_device_type = DeviceType.WINDOWS

        # 获取该类型的所有设备
        devices = self.get_devices_by_type(target_device_type)

        # ── exec_mode-aware filtering via GatewayCapabilityRegistry ─────────
        desired_exec_mode_str: Optional[str] = analysis.get("exec_mode")
        _actions = analysis.get("actions") or []
        desired_action: Optional[str] = _actions[0] if _actions else None

        if desired_exec_mode_str or desired_action:
            try:
                from galaxy_gateway.capability_registry import ExecMode
                gw_reg = get_gateway_capability_registry()
                desired_exec_mode = ExecMode.from_str(desired_exec_mode_str)

                filtered: List[Device] = []
                unregistered: List[Device] = []
                for device in devices:
                    schemas = gw_reg.query(
                        action=desired_action,
                        exec_mode=desired_exec_mode if desired_exec_mode != ExecMode.BOTH else None,
                        device_id=device.device_id,
                    )
                    if schemas:
                        filtered.append(device)
                    else:
                        # Device has no schema record — could be legacy client
                        all_caps = gw_reg.get_by_device(device.device_id)
                        if not all_caps:
                            # Legacy device: no capability_report yet → keep it
                            unregistered.append(device)
                        # else: device has caps but none match → exclude

                if filtered:
                    devices = filtered
                    logger.debug(
                        "_select_devices: exec_mode=%s action=%s → %d matching device(s)",
                        desired_exec_mode_str,
                        desired_action,
                        len(filtered),
                    )
                elif unregistered:
                    # Fall back to legacy devices that haven't reported capabilities yet
                    devices = unregistered
                    logger.debug(
                        "_select_devices: no schema matches; falling back to %d legacy device(s)",
                        len(unregistered),
                    )
                else:
                    logger.debug(
                        "_select_devices: no devices match exec_mode=%s action=%s; using all",
                        desired_exec_mode_str,
                        desired_action,
                    )
                    # devices already holds the full list — no further filtering

            except Exception as _reg_err:
                logger.warning(
                    "_select_devices: capability registry unavailable, skipping exec_mode filter: %s",
                    _reg_err,
                )

        # 使用自主优先过滤器（有 fallback 保证）
        try:
            from galaxy_gateway.autonomous_filter import filter_autonomous_devices
            require_cross = analysis.get("requires_cross_device", False)
            task_role = analysis.get("task_role")
            preferred = filter_autonomous_devices(
                devices,
                get_metadata=lambda d: d.metadata,
                get_status=lambda d: d.status,
                require_cross_device=require_cross,
                task_role=task_role,
            )
        except Exception as _filter_err:
            logger.warning("autonomous_filter unavailable, using online-only fallback: %s", _filter_err)
            preferred = [d for d in devices if d.status == "online"]

        if not preferred:
            logger.warning(f"⚠️ 没有在线的 {target_device_type} 设备")
            return []

        # 简单策略：返回第一个设备
        # 实际可以根据设备负载、能力等进行智能选择
        return [preferred[0]]
    
    def _create_task(self, command: str, analysis: Dict, target_devices: List[Device]) -> Dict:
        """创建任务"""
        task_id = str(uuid.uuid4())
        
        task = {
            "task_id": task_id,
            "command": command,
            "analysis": analysis,
            "target_devices": [d.device_id for d in target_devices],
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "payload": self._build_task_payload(analysis)
        }
        
        self.task_queue[task_id] = task
        return task
    
    def _build_task_payload(self, analysis: Dict) -> Dict:
        """构建任务 Payload"""
        payload = {
            "task_type": analysis["task_type"],
            "action": analysis["actions"][0] if analysis["actions"] else "",
            "target": "",
            "params": {}
        }
        
        # 根据任务类型构建具体参数
        # 这里是简化版本，实际应该更复杂
        
        return payload
    
    async def dispatch_task(self, task: Dict, device: Device) -> Dict:
        """分发单设备任务（公共 API，供跨模块调用）"""
        try:
            logger.info(f"📤 分发任务到设备: {device.device_id}")

            # 优先通过统一命令路由器分发（已绑定 DeviceCommunication executor）
            try:
                from core.command_router import get_command_router, CommandRequest, CommandMode
                cmd_router = get_command_router()
                if cmd_router._executor is not None:
                    cmd_req = CommandRequest(
                        source="device_router",
                        targets=[device.device_id],
                        command=task["payload"].get("action", task["payload"].get("task_type", "")),
                        params=task["payload"].get("params", task["payload"]),
                        mode=CommandMode.SYNC,
                        timeout=30.0,
                    )
                    cmd_result = await cmd_router.dispatch(cmd_req)
                    target_result = cmd_result.targets.get(device.device_id)
                    if target_result:
                        return {
                            "success": target_result.status.value == "success",
                            "result": target_result.result,
                            "error": target_result.error,
                        }
            except Exception as route_err:
                logger.debug(f"CommandRouter 分发失败，回退 WebSocket: {route_err}")

            # 回退：直接通过 WebSocket 发送 AIP v3.0 消息
            if device.websocket:
                message = {
                    "version": "3.0",
                    "message_id": str(uuid.uuid4()),
                    "type": "command",
                    "device_id": device.device_id,
                    "task_id": task["task_id"],
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": task["payload"],
                }
                await device.websocket.send(json.dumps(message))
                
                # 等待结果，使用 asyncio.Event 避免阻塞轮询
                task_id = task["task_id"]
                event = asyncio.Event()
                self._task_events[task_id] = event

                try:
                    await asyncio.wait_for(event.wait(), timeout=30.0)
                    if task_id in self.task_results:
                        result = self.task_results.pop(task_id)
                        return result
                except asyncio.TimeoutError:
                    pass
                finally:
                    self._task_events.pop(task_id, None)
                
                return {
                    "success": False,
                    "error": "任务执行超时"
                }
            else:
                return {"success": False, "error": "设备未连接"}

        except Exception as e:
            logger.error(f"❌ 任务分发失败: {e}")
            return {"success": False, "error": f"任务分发失败: {str(e)}"}
    
    async def _dispatch_cross_device_task(self, task: Dict, devices: List[Device]) -> Dict:
        """分发跨设备协同任务 (gated by cross-device switch — Round 4)."""
        # --- Round 4: hard constraint — single dispatcher guard ---
        if not is_cross_device_enabled():
            trace_id = task.get("trace_id")
            return make_disabled_response(trace_id=trace_id)
        try:
            logger.info(f"🔄 分发跨设备任务到 {len(devices)} 个设备")
            
            # 将任务分解为多个子任务
            subtasks = self._decompose_task(task, devices)
            
            # 并行执行所有子任务
            results = await asyncio.gather(
                *[self.dispatch_task(subtask, device) 
                  for subtask, device in zip(subtasks, devices)],
                return_exceptions=True
            )
            
            # 汇总结果
            success = all(r.get("success", False) for r in results if isinstance(r, dict))
            
            return {
                "success": success,
                "subtask_results": results,
                "message": "跨设备任务执行完成" if success else "部分子任务执行失败"
            }
            
        except Exception as e:
            logger.error(f"❌ 跨设备任务分发失败: {e}")
            return {
                "success": False,
                "error": f"跨设备任务分发失败: {str(e)}"
            }
    
    def _decompose_task(self, task: Dict, devices: List[Device]) -> List[Dict]:
        """将跨设备任务分解为多个子任务"""
        # 简化版本：每个设备执行相同的任务
        # 实际应该根据任务类型智能分解
        return [task.copy() for _ in devices]
    
    async def handle_task_result(self, task_id: str, result: Dict):
        """处理任务执行结果（幂等：同一 task_id 的重复结果将被忽略）。"""
        try:
            # ── Idempotency: ignore duplicate task results ──
            if task_id in self._seen_task_result_ids:
                logger.info(
                    "Duplicate task result ignored by device_router",
                    extra={
                        "event": "task_result_duplicate_ignored",
                        "task_id": task_id,
                    },
                )
                return
            self._seen_task_result_ids.add(task_id)

            self.task_results[task_id] = result

            # Signal the waiting event if any
            event = self._task_events.get(task_id)
            if event:
                event.set()

            if task_id in self.task_queue:
                task = self.task_queue[task_id]
                task["status"] = "completed" if result.get("success") else "failed"
                task["result"] = result
                task["completed_at"] = datetime.now().isoformat()

            # ── 并行闭环：secondary coverage — 若 result 携带并行字段则记录 ──
            if result.get("group_id"):
                try:
                    from galaxy_gateway.orchestrator.parallel_tracker import record_parallel_fields
                    parallel_payload = {
                        **result,
                        # derive status from success field when not explicitly set
                        "status": result.get("status") or (
                            "success" if result.get("success") else "failed"
                        ),
                    }
                    await record_parallel_fields(parallel_payload)
                except Exception as _pt_err:
                    logger.warning("parallel_tracker[device_router]: record failed: %s", _pt_err)

            logger.info(f"✅ 任务结果已记录: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ 处理任务结果失败: {e}")
    
    @staticmethod
    def aggregate_results(results: List[Dict]) -> Dict:
        """Aggregate multi-device task results into a unified summary."""
        success_count = sum(1 for r in results if r.get("success"))
        failure_count = len(results) - success_count
        results_by_device = {}
        for r in results:
            device_id = r.get("device_id", "unknown")
            results_by_device[device_id] = r
        return {
            "total": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "overall_success": failure_count == 0 and len(results) > 0,
            "results_by_device": results_by_device,
        }

    def get_device_status(self) -> Dict:
        """获取所有设备状态"""
        return {
            "total_devices": len(self.devices),
            "online_devices": len([d for d in self.devices.values() if d.status == "online"]),
            "devices": [d.to_dict() for d in self.devices.values()]
        }


# 全局设备路由器实例
device_router = DeviceRouter()
