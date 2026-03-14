"""
Galaxy 健康监控系统
========================

实时监控所有节点的健康状态，自动重启失败的节点

功能：
1. 实时监控所有节点
2. 自动重启失败的节点
3. 发送告警通知
4. 生成健康报告
5. Web 仪表板

作者：Galaxy Team
日期：2026-01-23
"""

import asyncio
import httpx
import json
from datetime import datetime
from typing import Dict, List
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from nodes.common.cors_config import get_cors_origins

# 导入系统管理器
from system_manager import SystemManager, NODES, NodeConfig

app = FastAPI(title="Galaxy Health Monitor", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# =============================================================================
# 健康监控器
# =============================================================================

class HealthMonitor:
    """健康监控器"""
    
    def __init__(self, manager: SystemManager, check_interval: int = 30):
        self.manager = manager
        self.check_interval = check_interval
        self.health_history: Dict[str, List[Dict]] = {}
        self.alert_count: Dict[str, int] = {}
        
        # ===== 集成：初始化能力和连接管理器 =====
        try:
            from core.capability_manager import get_capability_manager
            from core.connection_manager import get_connection_manager
            
            self.capability_manager = get_capability_manager()
            self.connection_manager = get_connection_manager()
        except Exception as e:
            print(f"⚠️  能力/连接管理器初始化失败: {e}")
            self.capability_manager = None
            self.connection_manager = None
        
    async def check_node(self, config: NodeConfig) -> Dict:
        """检查单个节点"""
        is_healthy = await self.manager.check_node_health(config, timeout=5)
        
        status = {
            "node_id": config.id,
            "name": config.name,
            "port": config.port,
            "group": config.group,
            "healthy": is_healthy,
            "timestamp": datetime.now().isoformat()
        }
        
        # 记录历史
        if config.id not in self.health_history:
            self.health_history[config.id] = []
        
        self.health_history[config.id].append(status)
        
        # 只保留最近 100 条记录
        if len(self.health_history[config.id]) > 100:
            self.health_history[config.id] = self.health_history[config.id][-100:]
        
        return status
    
    async def check_all(self) -> List[Dict]:
        """检查所有节点"""
        all_configs = []
        for group in NODES.values():
            all_configs.extend(group)
        
        tasks = [self.check_node(config) for config in all_configs]
        results = await asyncio.gather(*tasks)
        
        return results
    
    async def monitor_loop(self):
        """监控循环"""
        print(f"🔍 健康监控已启动（间隔 {self.check_interval} 秒）")
        
        while True:
            try:
                results = await self.check_all()
                
                # 统计
                healthy_count = sum(1 for r in results if r["healthy"])
                total_count = len(results)
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"健康: {healthy_count}/{total_count}")
                
                # 检查是否需要告警
                for result in results:
                    if not result["healthy"]:
                        await self.handle_unhealthy_node(result)
                
            except Exception as e:
                print(f"❌ 监控错误: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    async def handle_unhealthy_node(self, status: Dict):
        """处理不健康的节点"""
        node_id = status["node_id"]
        
        # 增加告警计数
        if node_id not in self.alert_count:
            self.alert_count[node_id] = 0
        
        self.alert_count[node_id] += 1
        
        print(f"⚠️  节点 {status['name']} 不健康（告警次数: {self.alert_count[node_id]}）")
        
        # 如果连续 3 次不健康，尝试重启
        if self.alert_count[node_id] >= 3:
            print(f"🔄 尝试重启节点 {status['name']}...")
            try:
                restart_result = await self.manager.restart_node(node_id)
                if restart_result:
                    print(f"✅ 节点 {status['name']} 重启成功")
                else:
                    print(f"❌ 节点 {status['name']} 重启失败")
            except Exception as e:
                print(f"❌ 节点 {status['name']} 重启异常: {e}")
            self.alert_count[node_id] = 0
    
    def get_summary(self) -> Dict:
        """获取摘要"""
        summary = {
            "total_nodes": 0,
            "healthy_nodes": 0,
            "unhealthy_nodes": 0,
            "groups": {}
        }
        
        for group_name, configs in NODES.items():
            group_summary = {
                "total": len(configs),
                "healthy": 0,
                "unhealthy": 0
            }
            
            for config in configs:
                if config.id in self.health_history and self.health_history[config.id]:
                    latest = self.health_history[config.id][-1]
                    if latest["healthy"]:
                        group_summary["healthy"] += 1
                    else:
                        group_summary["unhealthy"] += 1
            
            summary["groups"][group_name] = group_summary
            summary["total_nodes"] += group_summary["total"]
            summary["healthy_nodes"] += group_summary["healthy"]
            summary["unhealthy_nodes"] += group_summary["unhealthy"]
        
        # ===== 集成：添加能力和连接状态 =====
        if self.capability_manager:
            try:
                cap_stats = self.capability_manager.get_stats()
                summary["capabilities"] = cap_stats
            except Exception as e:
                summary["capabilities"] = {"error": str(e)}
        
        if self.connection_manager:
            try:
                conn_stats = self.connection_manager.get_stats()
                summary["connections"] = conn_stats
            except Exception as e:
                summary["connections"] = {"error": str(e)}
        
        return summary

# =============================================================================
# 全局实例
# =============================================================================

manager = SystemManager()
monitor = HealthMonitor(manager)

# =============================================================================
# API 端点
# =============================================================================

@app.get("/")
async def root():
    """首页 — JSON status endpoint; UI via main SONARA dashboard at :8080"""
    summary = monitor.get_summary()
    return {
        "service": "Galaxy Health Monitor",
        "dashboard": "http://localhost:8080",
        "summary": summary,
    }

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    results = await monitor.check_all()
    summary = monitor.get_summary()
    
    response = {
        "summary": summary,
        "nodes": results
    }

    # Surface federation health summary if available
    try:
        from core.galaxy_federation import get_federation, _federation_enabled
        fed = get_federation()
        peers = fed.list_peers()
        response["federation"] = {
            "instance_id": fed.instance_id,
            "enabled": _federation_enabled(),
            "peers_count": len(peers),
            "alive": sum(1 for p in peers if p["status"] == "healthy"),
            "degraded": sum(1 for p in peers if p["status"] == "degraded"),
            "offline": sum(1 for p in peers if p["status"] == "offline"),
        }
    except Exception:
        pass

    return response

@app.get("/api/history/{node_id}")
async def get_history(node_id: str):
    """获取节点历史"""
    if node_id not in monitor.health_history:
        return {"error": "Node not found"}
    
    return {
        "node_id": node_id,
        "history": monitor.health_history[node_id]
    }

# =============================================================================
# 启动服务
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """启动时开始监控循环"""
    asyncio.create_task(monitor.monitor_loop())

if __name__ == "__main__":
    import uvicorn

    # 启动 Web 服务（监控循环通过 startup 事件自动启动）
    try:
        from core.port_config import get_service_port
        _hm_port = get_service_port("health_monitor")
    except Exception:
        _hm_port = 9100
    uvicorn.run(app, host="0.0.0.0", port=_hm_port)
