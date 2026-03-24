# Node_73_Learning

在线学习与模型管理服务节点，支持模型注册、训练任务提交与推理执行。

## 端口
8073

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /models` - 列出已注册模型
- `POST /model/register` - 注册新模型
- `GET /model/{name}` - 获取模型详情
- `POST /train` - 提交训练任务
