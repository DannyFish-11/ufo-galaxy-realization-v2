# Node_127_BambuLab

拓竹 3D 打印机控制服务节点，提供打印任务管理、设备控制与 G-code 下发功能。

## 端口
8127

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /print` - 提交打印任务
- `POST /control` - 设备控制命令
- `POST /gcode` - 下发 G-code 指令
- `POST /mcp/call` - MCP 工具调用
