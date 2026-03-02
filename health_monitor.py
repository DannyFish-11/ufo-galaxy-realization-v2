"""
UFO³ Galaxy 健康监控系统
========================

实时监控所有节点的健康状态，自动重启失败的节点

功能：
1. 实时监控所有节点
2. 自动重启失败的节点
3. 发送告警通知
4. 生成健康报告
5. Web 仪表板

作者：Manus AI
日期：2026-01-23
"""

import asyncio
import httpx
import json
from datetime import datetime
from typing import Dict, List
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# 导入系统管理器
from system_manager import SystemManager, NODES, NodeConfig

app = FastAPI(title="UFO³ Galaxy Health Monitor", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """首页"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>UFO³ Galaxy Health Monitor</title>
        <style>
            body {
                font-family: 'Courier New', monospace;
                background: linear-gradient(135deg, #000000 0%, #1a1a1a 100%);
                color: #00ff00;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            h1 {
                color: #00bfff;
                text-align: center;
                text-shadow: 0 0 10px #00bfff;
            }
            .summary {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
                margin: 30px 0;
            }
            .card {
                background: rgba(0, 255, 0, 0.1);
                border: 1px solid #00ff00;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
            }
            .card h2 {
                margin: 0;
                font-size: 48px;
                color: #00ff00;
            }
            .card p {
                margin: 10px 0 0 0;
                color: #00bfff;
            }
            .nodes {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 15px;
            }
            .node {
                background: rgba(0, 191, 255, 0.1);
                border: 1px solid #00bfff;
                border-radius: 8px;
                padding: 15px;
            }
            .node.healthy {
                border-color: #00ff00;
            }
            .node.unhealthy {
                border-color: #ff4500;
            }
            .node h3 {
                margin: 0 0 10px 0;
                color: #00bfff;
            }
            .status {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            .status.healthy {
                background: #00ff00;
                color: #000;
            }
            .status.unhealthy {
                background: #ff4500;
                color: #fff;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛸 UFO³ Galaxy Health Monitor</h1>
            
            <div class="summary" id="summary">
                <div class="card">
                    <h2 id="total">-</h2>
                    <p>总节点数</p>
                </div>
                <div class="card">
                    <h2 id="healthy">-</h2>
                    <p>健康节点</p>
                </div>
                <div class="card">
                    <h2 id="unhealthy">-</h2>
                    <p>不健康节点</p>
                </div>
            </div>
            
            <div class="nodes" id="nodes"></div>
        </div>
        
        <script>
            async function updateStatus() {
                try {
                    const response = await fetch('/api/status');
                    const data = await response.json();
                    
                    // 更新摘要
                    document.getElementById('total').textContent = data.summary.total_nodes;
                    document.getElementById('healthy').textContent = data.summary.healthy_nodes;
                    document.getElementById('unhealthy').textContent = data.summary.unhealthy_nodes;
                    
                    // 更新节点列表
                    const nodesDiv = document.getElementById('nodes');
                    nodesDiv.innerHTML = '';
                    
                    data.nodes.forEach(node => {
                        const nodeDiv = document.createElement('div');
                        nodeDiv.className = `node ${node.healthy ? 'healthy' : 'unhealthy'}`;
                        nodeDiv.innerHTML = `
                            <h3>Node_${node.node_id} ${node.name}</h3>
                            <p>端口: ${node.port}</p>
                            <p>分组: ${node.group}</p>
                            <p>状态: <span class="status ${node.healthy ? 'healthy' : 'unhealthy'}">
                                ${node.healthy ? '✅ 健康' : '❌ 不健康'}
                            </span></p>
                        `;
                        nodesDiv.appendChild(nodeDiv);
                    });
                } catch (error) {
                    console.error('更新状态失败:', error);
                }
            }
            
            // 初始更新
            updateStatus();
            
            // 每 10 秒更新一次
            setInterval(updateStatus, 10000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    results = await monitor.check_all()
    summary = monitor.get_summary()
    
    return {
        "summary": summary,
        "nodes": results
    }

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
    uvicorn.run(app, host="0.0.0.0", port=9000)
