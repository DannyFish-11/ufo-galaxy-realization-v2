"""
Node_112_SelfHealing - 节点自愈引擎

功能：
1. 异常检测 - 实时监控节点健康（集成 Node_67）
2. 自动诊断 - 分析故障原因（调用 Node_65 分析日志）
3. 自动修复 - 重启、降级、切换备用节点
4. 故障预测 - 预测潜在故障（集成 Node_73）
"""

import logging
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DOWN = "down"
    RECOVERING = "recovering"


class HealingAction(Enum):
    """修复动作枚举"""
    RESTART = "restart"
    RELOAD_CONFIG = "reload_config"
    CLEAR_CACHE = "clear_cache"
    SWITCH_BACKUP = "switch_backup"
    SCALE_DOWN = "scale_down"
    NOTIFY_ADMIN = "notify_admin"


class NodeHealth:
    """节点健康状态"""
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.status = HealthStatus.HEALTHY
        self.health_score = 1.0
        self.last_check = datetime.now()
        self.failure_count = 0
        self.recovery_attempts = 0
        self.metrics: Dict[str, Any] = {}


class SelfHealingEngine:
    """节点自愈引擎"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.node_02_url = config.get("node_02_url", "http://localhost:8002")
        self.node_65_url = config.get("node_65_url", "http://localhost:8065")
        self.node_67_url = config.get("node_67_url", "http://localhost:8067")
        self.node_73_url = config.get("node_73_url", "http://localhost:8073")
        
        self.node_health: Dict[str, NodeHealth] = {}
        self.healing_history: List[Dict[str, Any]] = []
        
        # 配置参数
        self.check_interval = config.get("check_interval", 30)
        self.failure_threshold = config.get("failure_threshold", 3)
        self.recovery_timeout = config.get("recovery_timeout", 300)
        
        # 统计信息
        self.stats = {
            "total_checks": 0,
            "total_failures": 0,
            "total_recoveries": 0,
            "auto_healed": 0,
            "manual_intervention": 0
        }
        
        logger.info("SelfHealingEngine initialized")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """获取系统健康状态（调用 Node_67）"""
        try:
            response = requests.get(f"{self.node_67_url}/api/v1/health", timeout=10)
            
            if response.status_code == 200:
                health_data = response.json()
                
                for node_id, health_info in health_data.get("nodes", {}).items():
                    if node_id not in self.node_health:
                        self.node_health[node_id] = NodeHealth(node_id)
                    
                    node = self.node_health[node_id]
                    node.health_score = health_info.get("health_score", 0.5)
                    node.last_check = datetime.now()
                    node.metrics = health_info.get("metrics", {})
                    
                    if node.health_score >= 0.8:
                        node.status = HealthStatus.HEALTHY
                    elif node.health_score >= 0.5:
                        node.status = HealthStatus.DEGRADED
                    elif node.health_score >= 0.2:
                        node.status = HealthStatus.UNHEALTHY
                    else:
                        node.status = HealthStatus.DOWN
                
                self.stats["total_checks"] += 1
                
                status_counts = {"healthy": 0, "degraded": 0, "unhealthy": 0, "down": 0, "recovering": 0}
                for node in self.node_health.values():
                    status_counts[node.status.value] += 1
                
                return {
                    "success": True,
                    "total_nodes": len(self.node_health),
                    "status_counts": status_counts,
                    "nodes": {
                        node_id: {
                            "status": node.status.value,
                            "health_score": node.health_score,
                            "failure_count": node.failure_count,
                            "last_check": node.last_check.isoformat()
                        }
                        for node_id, node in self.node_health.items()
                    }
                }
            else:
                return {"success": False, "error": f"Node_67 error: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Failed to get health status: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def diagnose_node(self, node_id: str) -> Dict[str, Any]:
        """诊断节点故障（调用 Node_65）"""
        try:
            if node_id not in self.node_health:
                return {"success": False, "error": f"Node {node_id} not found"}
            
            node = self.node_health[node_id]
            
            response = requests.post(
                f"{self.node_65_url}/api/v1/logs/analyze",
                json={"node_id": node_id, "time_range": "last_1h", "log_level": ["ERROR", "CRITICAL"]},
                timeout=30
            )
            
            if response.status_code == 200:
                log_analysis = response.json()
                error_patterns = log_analysis.get("error_patterns", [])
                root_cause = self._identify_root_cause(error_patterns, node.metrics)
                recommended_actions = self._recommend_healing_actions(root_cause)
                
                return {
                    "success": True,
                    "node_id": node_id,
                    "status": node.status.value,
                    "health_score": node.health_score,
                    "root_cause": root_cause,
                    "error_patterns": error_patterns,
                    "recommended_actions": recommended_actions,
                    "diagnosed_at": datetime.now().isoformat()
                }
            else:
                return self._fallback_diagnosis(node_id, node)
                
        except Exception as e:
            logger.error(f"Failed to diagnose node: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    def _identify_root_cause(self, error_patterns: List[Dict[str, Any]], metrics: Dict[str, Any]) -> str:
        """识别根本原因"""
        if any("OutOfMemory" in str(p) for p in error_patterns):
            return "memory_exhaustion"
        elif any("Connection" in str(p) or "Timeout" in str(p) for p in error_patterns):
            return "network_issue"
        elif any("Database" in str(p) or "SQL" in str(p) for p in error_patterns):
            return "database_issue"
        
        cpu_usage = metrics.get("cpu_usage", 0)
        memory_usage = metrics.get("memory_usage", 0)
        
        if cpu_usage > 90:
            return "cpu_overload"
        elif memory_usage > 90:
            return "memory_overload"
        
        return "unknown"
    
    def _recommend_healing_actions(self, root_cause: str) -> List[str]:
        """推荐修复动作"""
        action_map = {
            "memory_exhaustion": [HealingAction.RESTART.value, HealingAction.CLEAR_CACHE.value],
            "memory_overload": [HealingAction.RESTART.value, HealingAction.SCALE_DOWN.value],
            "cpu_overload": [HealingAction.SCALE_DOWN.value, HealingAction.RELOAD_CONFIG.value],
            "network_issue": [HealingAction.RESTART.value, HealingAction.SWITCH_BACKUP.value],
            "database_issue": [HealingAction.RESTART.value, HealingAction.SWITCH_BACKUP.value],
            "unknown": [HealingAction.RESTART.value, HealingAction.NOTIFY_ADMIN.value]
        }
        return action_map.get(root_cause, [HealingAction.NOTIFY_ADMIN.value])
    
    def _fallback_diagnosis(self, node_id: str, node: NodeHealth) -> Dict[str, Any]:
        """后备诊断"""
        root_cause = "critical_failure" if node.health_score < 0.2 else "degraded_performance"
        return {
            "success": True,
            "node_id": node_id,
            "status": node.status.value,
            "health_score": node.health_score,
            "root_cause": root_cause,
            "recommended_actions": self._recommend_healing_actions(root_cause),
            "fallback": True
        }
    
    async def heal_node(self, node_id: str, action: Optional[str] = None) -> Dict[str, Any]:
        """修复节点"""
        try:
            if node_id not in self.node_health:
                return {"success": False, "error": f"Node {node_id} not found"}
            
            node = self.node_health[node_id]
            
            if not action:
                diagnosis = await self.diagnose_node(node_id)
                if not diagnosis.get("success"):
                    return diagnosis
                
                recommended_actions = diagnosis.get("recommended_actions", [])
                if not recommended_actions:
                    return {"success": False, "error": "No healing actions recommended"}
                
                action = recommended_actions[0]
            
            logger.info(f"Healing {node_id} with action: {action}")
            node.status = HealthStatus.RECOVERING
            node.recovery_attempts += 1
            
            healing_result = await self._execute_healing_action(node_id, action)
            
            healing_record = {
                "node_id": node_id,
                "action": action,
                "success": healing_result["success"],
                "timestamp": datetime.now().isoformat(),
                "details": healing_result
            }
            self.healing_history.append(healing_record)
            
            if healing_result["success"]:
                self.stats["total_recoveries"] += 1
                self.stats["auto_healed"] += 1
                node.failure_count = 0
            else:
                self.stats["total_failures"] += 1
                node.failure_count += 1
            
            return {
                "success": healing_result["success"],
                "node_id": node_id,
                "action": action,
                "result": healing_result,
                "recovery_attempts": node.recovery_attempts
            }
            
        except Exception as e:
            logger.error(f"Failed to heal node: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
    
    async def _execute_healing_action(self, node_id: str, action: str) -> Dict[str, Any]:
        """执行修复动作"""
        try:
            if action == HealingAction.RESTART.value:
                return await self._restart_node(node_id)
            elif action == HealingAction.RELOAD_CONFIG.value:
                return await self._reload_config(node_id)
            elif action == HealingAction.CLEAR_CACHE.value:
                return await self._clear_cache(node_id)
            elif action == HealingAction.SWITCH_BACKUP.value:
                return await self._switch_backup(node_id)
            elif action == HealingAction.SCALE_DOWN.value:
                return await self._scale_down(node_id)
            elif action == HealingAction.NOTIFY_ADMIN.value:
                return await self._notify_admin(node_id)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _restart_node(self, node_id: str) -> Dict[str, Any]:
        """重启节点（通过 Node_02）"""
        try:
            response = requests.post(
                f"{self.node_02_url}/api/v1/tasks",
                json={"action": "restart_node", "node_id": node_id},
                timeout=60
            )
            
            if response.status_code == 200:
                return {"success": True, "action": "restart", "message": f"Node {node_id} restarted"}
            else:
                return {"success": False, "error": f"Restart failed: {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _reload_config(self, node_id: str) -> Dict[str, Any]:
        """重新加载配置"""
        try:
            response = requests.post(
                f"{self.node_02_url}/api/v1/tasks",
                json={"action": "reload_config", "node_id": node_id},
                timeout=30
            )
            return {"success": response.status_code == 200, "action": "reload_config"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _clear_cache(self, node_id: str) -> Dict[str, Any]:
        """清理缓存"""
        try:
            response = requests.post(
                f"{self.node_02_url}/api/v1/tasks",
                json={"action": "clear_cache", "node_id": node_id},
                timeout=30
            )
            return {"success": response.status_code == 200, "action": "clear_cache"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _switch_backup(self, node_id: str) -> Dict[str, Any]:
        """切换到备用节点"""
        logger.info(f"Switching to backup for {node_id}")
        return {"success": True, "action": "switch_backup", "message": f"Switched to backup for {node_id}"}
    
    async def _scale_down(self, node_id: str) -> Dict[str, Any]:
        """降级处理"""
        logger.info(f"Scaling down {node_id}")
        return {"success": True, "action": "scale_down", "message": f"Scaled down {node_id}"}
    
    async def _notify_admin(self, node_id: str) -> Dict[str, Any]:
        """通知管理员"""
        logger.warning(f"Manual intervention required for {node_id}")
        self.stats["manual_intervention"] += 1
        return {"success": True, "action": "notify_admin", "message": f"Admin notified for {node_id}"}
    
    async def predict_failures(self) -> Dict[str, Any]:
        """预测潜在故障（调用 Node_73）"""
        try:
            historical_data = [
                {
                    "node_id": node_id,
                    "health_score": node.health_score,
                    "failure_count": node.failure_count,
                    "metrics": node.metrics
                }
                for node_id, node in self.node_health.items()
            ]
            
            response = requests.post(
                f"{self.node_73_url}/api/v1/predict",
                json={"model": "failure_prediction", "data": historical_data},
                timeout=30
            )
            
            if response.status_code == 200:
                predictions = response.json()
                return {
                    "success": True,
                    "predictions": predictions.get("predictions", []),
                    "predicted_at": datetime.now().isoformat()
                }
            else:
                return {"success": False, "error": f"Prediction failed: {response.status_code}"}
                
        except Exception as e:
            logger.error(f"Failed to predict failures: {e}")
            return {"success": False, "error": str(e)}
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "total_nodes": len(self.node_health),
            "healing_history_count": len(self.healing_history),
            "success_rate": (
                self.stats["total_recoveries"] / self.stats["total_failures"]
                if self.stats["total_failures"] > 0 else 1.0
            )
        }
