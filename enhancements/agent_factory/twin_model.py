"""
孪生模型管理器 (Twin Model Manager)
===================================

数字孪生能力：
- 创建 Agent 的数字孪生
- 状态同步
- 行为模拟
- 预测分析
- 解耦和耦合

版本: v2.3.22
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import copy

logger = logging.getLogger(__name__)


class TwinState(Enum):
    """孪生状态"""
    CREATED = "created"
    SYNCING = "syncing"
    SYNCED = "synced"
    DIVERGED = "diverged"
    DETACHED = "detached"
    ERROR = "error"


class CouplingMode(Enum):
    """耦合模式"""
    TIGHT = "tight"           # 紧耦合: 实时同步
    LOOSE = "loose"           # 松耦合: 定期同步
    DECOUPLED = "decoupled"   # 解耦: 独立运行
    SHADOW = "shadow"         # 影子模式: 只读同步


@dataclass
class TwinModel:
    """孪生模型"""
    twin_id: str
    source_id: str                    # 源 Agent ID
    name: str
    state: TwinState = TwinState.CREATED
    coupling_mode: CouplingMode = CouplingMode.LOOSE
    
    # 状态快照
    snapshot: Dict[str, Any] = field(default_factory=dict)
    
    # 行为历史
    behavior_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # 预测模型
    prediction_model: Dict[str, Any] = field(default_factory=dict)
    
    # 同步配置
    sync_interval: float = 5.0        # 同步间隔（秒）
    last_sync: Optional[datetime] = None
    sync_count: int = 0
    
    # 偏差检测
    divergence_threshold: float = 0.1
    current_divergence: float = 0.0
    
    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    """同步结果"""
    twin_id: str
    success: bool
    changes: Dict[str, Any]
    divergence: float
    timestamp: datetime = field(default_factory=datetime.now)
    error: str = ""


class TwinModelManager:
    """孪生模型管理器"""
    
    def __init__(self):
        self.twins: Dict[str, TwinModel] = {}
        self.source_to_twins: Dict[str, List[str]] = {}  # source_id -> [twin_ids]
        self._sync_tasks: Dict[str, asyncio.Task] = {}
        self._state_callbacks: Dict[str, List[Callable]] = {}
    
    async def create_twin(
        self,
        source_id: str,
        name: str,
        coupling_mode: CouplingMode = CouplingMode.LOOSE,
        initial_snapshot: Optional[Dict[str, Any]] = None
    ) -> TwinModel:
        """创建孪生模型"""
        twin_id = f"twin_{datetime.now().strftime('%Y%m%d%H%M%S')}_{source_id[:8]}"
        
        twin = TwinModel(
            twin_id=twin_id,
            source_id=source_id,
            name=name,
            coupling_mode=coupling_mode,
            snapshot=initial_snapshot or {}
        )
        
        self.twins[twin_id] = twin
        
        # 建立映射
        if source_id not in self.source_to_twins:
            self.source_to_twins[source_id] = []
        self.source_to_twins[source_id].append(twin_id)
        
        # 启动同步任务
        if coupling_mode != CouplingMode.DECOUPLED:
            self._sync_tasks[twin_id] = asyncio.create_task(
                self._sync_loop(twin_id)
            )
        
        logger.info(f"Created twin model: {twin_id} for source: {source_id}")
        return twin
    
    async def delete_twin(self, twin_id: str):
        """删除孪生模型"""
        if twin_id in self.twins:
            twin = self.twins[twin_id]
            
            # 停止同步任务
            if twin_id in self._sync_tasks:
                self._sync_tasks[twin_id].cancel()
                del self._sync_tasks[twin_id]
            
            # 移除映射
            if twin.source_id in self.source_to_twins:
                self.source_to_twins[twin.source_id] = [
                    tid for tid in self.source_to_twins[twin.source_id]
                    if tid != twin_id
                ]
            
            del self.twins[twin_id]
            logger.info(f"Deleted twin model: {twin_id}")
    
    async def update_snapshot(
        self,
        twin_id: str,
        snapshot: Dict[str, Any]
    ) -> SyncResult:
        """更新快照"""
        if twin_id not in self.twins:
            return SyncResult(
                twin_id=twin_id,
                success=False,
                changes={},
                divergence=0.0,
                error="Twin not found"
            )
        
        twin = self.twins[twin_id]
        old_snapshot = copy.deepcopy(twin.snapshot)
        
        # 计算偏差
        divergence = self._calculate_divergence(old_snapshot, snapshot)
        twin.current_divergence = divergence
        
        # 检测状态变化
        changes = self._detect_changes(old_snapshot, snapshot)
        
        # 更新快照
        twin.snapshot = snapshot
        twin.updated_at = datetime.now()
        twin.sync_count += 1
        twin.last_sync = datetime.now()
        
        # 更新状态
        if divergence > twin.divergence_threshold:
            twin.state = TwinState.DIVERGED
        else:
            twin.state = TwinState.SYNCED
        
        # 记录行为历史
        twin.behavior_history.append({
            "timestamp": datetime.now().isoformat(),
            "changes": changes,
            "divergence": divergence
        })
        
        # 限制历史长度
        if len(twin.behavior_history) > 100:
            twin.behavior_history = twin.behavior_history[-100:]
        
        # 触发回调
        await self._trigger_callbacks(twin_id, "sync", changes)
        
        return SyncResult(
            twin_id=twin_id,
            success=True,
            changes=changes,
            divergence=divergence
        )
    
    def _calculate_divergence(
        self,
        old: Dict[str, Any],
        new: Dict[str, Any]
    ) -> float:
        """计算偏差"""
        if not old or not new:
            return 1.0
        
        # 简单的偏差计算：比较键值对
        all_keys = set(old.keys()) | set(new.keys())
        if not all_keys:
            return 0.0
        
        differences = 0
        for key in all_keys:
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                differences += 1
        
        return differences / len(all_keys)
    
    def _detect_changes(
        self,
        old: Dict[str, Any],
        new: Dict[str, Any]
    ) -> Dict[str, Any]:
        """检测变化"""
        changes = {
            "added": {},
            "removed": {},
            "modified": {}
        }
        
        old_keys = set(old.keys())
        new_keys = set(new.keys())
        
        # 新增的键
        for key in new_keys - old_keys:
            changes["added"][key] = new[key]
        
        # 移除的键
        for key in old_keys - new_keys:
            changes["removed"][key] = old[key]
        
        # 修改的键
        for key in old_keys & new_keys:
            if old[key] != new[key]:
                changes["modified"][key] = {
                    "old": old[key],
                    "new": new[key]
                }
        
        return changes
    
    async def _sync_loop(self, twin_id: str):
        """同步循环"""
        while True:
            try:
                twin = self.twins.get(twin_id)
                if not twin:
                    break
                
                if twin.coupling_mode == CouplingMode.DECOUPLED:
                    break
                
                # 根据耦合模式决定同步间隔
                interval = twin.sync_interval
                if twin.coupling_mode == CouplingMode.TIGHT:
                    interval = 0.1  # 100ms
                elif twin.coupling_mode == CouplingMode.LOOSE:
                    interval = twin.sync_interval
                elif twin.coupling_mode == CouplingMode.SHADOW:
                    interval = twin.sync_interval * 2
                
                await asyncio.sleep(interval)
                
                # 触发同步回调
                await self._trigger_callbacks(twin_id, "sync_tick", {})
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error for {twin_id}: {e}")
                await asyncio.sleep(5)
    
    async def _trigger_callbacks(
        self,
        twin_id: str,
        event: str,
        data: Dict[str, Any]
    ):
        """触发回调"""
        callbacks = self._state_callbacks.get(twin_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event, data)
                else:
                    callback(event, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def register_callback(
        self,
        twin_id: str,
        callback: Callable
    ):
        """注册回调"""
        if twin_id not in self._state_callbacks:
            self._state_callbacks[twin_id] = []
        self._state_callbacks[twin_id].append(callback)
    
    def set_coupling_mode(
        self,
        twin_id: str,
        mode: CouplingMode
    ):
        """设置耦合模式"""
        if twin_id in self.twins:
            twin = self.twins[twin_id]
            old_mode = twin.coupling_mode
            twin.coupling_mode = mode
            
            # 处理模式切换
            if mode == CouplingMode.DECOUPLED:
                # 解耦：停止同步
                if twin_id in self._sync_tasks:
                    self._sync_tasks[twin_id].cancel()
                    del self._sync_tasks[twin_id]
                twin.state = TwinState.DETACHED
            elif old_mode == CouplingMode.DECOUPLED:
                # 重新耦合：启动同步
                self._sync_tasks[twin_id] = asyncio.create_task(
                    self._sync_loop(twin_id)
                )
                twin.state = TwinState.SYNCING
            
            logger.info(f"Twin {twin_id} coupling mode changed: {old_mode.value} -> {mode.value}")
    
    def decouple(self, twin_id: str):
        """解耦"""
        self.set_coupling_mode(twin_id, CouplingMode.DECOUPLED)
    
    def couple(self, twin_id: str, mode: CouplingMode = CouplingMode.LOOSE):
        """耦合"""
        self.set_coupling_mode(twin_id, mode)
    
    def get_twin(self, twin_id: str) -> Optional[TwinModel]:
        """获取孪生模型"""
        return self.twins.get(twin_id)
    
    def get_twins_for_source(self, source_id: str) -> List[TwinModel]:
        """获取源的所有孪生模型"""
        twin_ids = self.source_to_twins.get(source_id, [])
        return [self.twins[tid] for tid in twin_ids if tid in self.twins]
    
    def list_twins(self) -> List[Dict]:
        """列出所有孪生模型"""
        return [
            {
                "twin_id": t.twin_id,
                "source_id": t.source_id,
                "name": t.name,
                "state": t.state.value,
                "coupling_mode": t.coupling_mode.value,
                "sync_count": t.sync_count,
                "current_divergence": t.current_divergence,
                "last_sync": t.last_sync.isoformat() if t.last_sync else None
            }
            for t in self.twins.values()
        ]
    
    async def predict_behavior(
        self,
        twin_id: str,
        horizon: int = 5
    ) -> List[Dict[str, Any]]:
        """预测行为"""
        if twin_id not in self.twins:
            return []
        
        twin = self.twins[twin_id]
        history = twin.behavior_history
        
        if len(history) < 3:
            return []
        
        # 简单的预测：基于历史趋势
        predictions = []
        recent_changes = [h.get("changes", {}) for h in history[-5:]]
        
        # 统计最近的变化模式
        modified_keys = {}
        for changes in recent_changes:
            for key, val in changes.get("modified", {}).items():
                if key not in modified_keys:
                    modified_keys[key] = []
                modified_keys[key].append(val.get("new"))
        
        # 预测未来变化
        for i in range(horizon):
            prediction = {
                "step": i + 1,
                "predicted_changes": {},
                "confidence": max(0.5, 1.0 - i * 0.1)
            }
            
            for key, values in modified_keys.items():
                if len(values) >= 2:
                    # 简单趋势预测
                    trend = "increasing" if values[-1] > values[-2] else "decreasing"
                    prediction["predicted_changes"][key] = {
                        "trend": trend,
                        "last_value": values[-1]
                    }
            
            predictions.append(prediction)
        
        return predictions
    
    async def simulate(
        self,
        twin_id: str,
        scenario: Dict[str, Any]
    ) -> Dict[str, Any]:
        """模拟场景"""
        if twin_id not in self.twins:
            return {"error": "Twin not found"}
        
        twin = self.twins[twin_id]
        
        # 创建模拟快照
        simulated_snapshot = copy.deepcopy(twin.snapshot)
        
        # 应用场景变化
        for key, value in scenario.items():
            simulated_snapshot[key] = value
        
        # 计算模拟后的偏差
        divergence = self._calculate_divergence(twin.snapshot, simulated_snapshot)
        
        return {
            "original_snapshot": twin.snapshot,
            "simulated_snapshot": simulated_snapshot,
            "divergence": divergence,
            "scenario": scenario
        }


# 全局实例
twin_manager = TwinModelManager()
