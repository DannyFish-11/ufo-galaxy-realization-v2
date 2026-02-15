"""
Node 71 - MultiDeviceCoordination (多设备协调节点)
提供多设备协同控制、任务分配和状态同步能力
v2.1 - 集成容错层、模块化 API 路由
"""
import os
import sys
import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 确保模块路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    MultiDeviceCoordinatorEngine, CoordinatorConfig, CoordinatorState,
    DiscoveryConfig, SyncConfig, SchedulerConfig,
    CircuitBreakerConfig, RetryConfig, FailoverConfig
)
from api.routes import create_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("Node71")

# ==================== 配置 ====================

NODE_PORT = int(os.environ.get("NODE71_PORT", "8071"))
NODE_HOST = os.environ.get("NODE71_HOST", "0.0.0.0")
NODE_ID = os.environ.get("NODE71_ID", "")
NODE_NAME = os.environ.get("NODE71_NAME", "MultiDeviceCoordinator")

# 发现协议配置
DISCOVERY_MDNS = os.environ.get("NODE71_MDNS_ENABLED", "true").lower() == "true"
DISCOVERY_UPNP = os.environ.get("NODE71_UPNP_ENABLED", "true").lower() == "true"
DISCOVERY_BROADCAST = os.environ.get("NODE71_BROADCAST_ENABLED", "true").lower() == "true"
BROADCAST_PORT = int(os.environ.get("NODE71_BROADCAST_PORT", "37021"))

# 容错配置
CB_FAILURE_THRESHOLD = int(os.environ.get("NODE71_CB_FAILURE_THRESHOLD", "5"))
CB_TIMEOUT = float(os.environ.get("NODE71_CB_TIMEOUT", "30.0"))
RETRY_MAX = int(os.environ.get("NODE71_RETRY_MAX", "3"))
RETRY_BASE_DELAY = float(os.environ.get("NODE71_RETRY_BASE_DELAY", "1.0"))


def build_config() -> CoordinatorConfig:
    """构建协调器配置"""
    return CoordinatorConfig(
        node_id=NODE_ID,
        node_name=NODE_NAME,
        discovery_config=DiscoveryConfig(
            mdns_enabled=DISCOVERY_MDNS,
            upnp_enabled=DISCOVERY_UPNP,
            broadcast_enabled=DISCOVERY_BROADCAST,
            broadcast_port=BROADCAST_PORT
        ),
        sync_config=SyncConfig(),
        scheduler_config=SchedulerConfig(),
        circuit_breaker_config=CircuitBreakerConfig(
            failure_threshold=CB_FAILURE_THRESHOLD,
            timeout=CB_TIMEOUT
        ),
        retry_config=RetryConfig(
            max_retries=RETRY_MAX,
            base_delay=RETRY_BASE_DELAY
        ),
        failover_config=FailoverConfig()
    )


# ==================== 引擎实例 ====================

engine = MultiDeviceCoordinatorEngine(build_config())


# ==================== 应用生命周期 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting Node 71 - MultiDeviceCoordination Engine...")

    # 启动引擎
    success = await engine.start()
    if success:
        logger.info(f"Engine started successfully (node_id={engine.config.node_id})")
    else:
        logger.error("Failed to start engine")

    yield

    # 停止引擎
    logger.info("Shutting down engine...")
    await engine.stop()
    logger.info("Engine stopped")


# ==================== FastAPI 应用 ====================

app = FastAPI(
    title="Node 71 - MultiDeviceCoordination",
    description="多设备协调引擎 - 提供设备发现、状态同步、任务调度和容错恢复能力",
    version="2.1.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 注册模块化路由
api_router = create_router(engine)
app.include_router(api_router)


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting Node 71 on {NODE_HOST}:{NODE_PORT}")

    uvicorn.run(
        "main:app",
        host=NODE_HOST,
        port=NODE_PORT,
        reload=False,
        log_level="info",
        access_log=True
    )
