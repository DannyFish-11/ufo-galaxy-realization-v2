"""
Node_96_SmartTransportRouter - 智能传输路由节点

功能：
- 提供智能传输路由服务
- 根据任务类型自动选择最佳传输方式（WebRTC/Scrcpy/ADB/HTTP）
- 支持 Tailscale 和直连两种网络层
- 支持 MQTT/WebSocket/HTTP 三种控制信令

端口：8096
版本：1.0.0
"""

import sys
import os
from pathlib import Path

# 添加 galaxy_gateway 到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "galaxy_gateway"))

from smart_transport_router import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8096)
