# Node_81_Orchestrator

统一编排器服务节点，负责将高层任务分解为子任务并协调各节点执行工作流。

## 端口
8081

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /workflow` - 提交工作流
- `POST /decompose` - 任务分解
- `GET /workflow/{workflow_id}` - 查询工作流状态
