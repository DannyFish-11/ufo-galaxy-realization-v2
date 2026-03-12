# Node_02_Tasker

任务调度引擎，提供任务创建、执行、取消和状态查询功能。

## 端口
8002

## 环境变量
- `STATE_MACHINE_URL`: 状态机节点地址（默认 http://localhost:8000）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /tasks` - 创建任务
- `GET /tasks` - 列出任务
- `GET /tasks/{task_id}` - 获取任务详情
- `DELETE /tasks/{task_id}` - 取消任务
