# Node_128_MediaGen

媒体生成服务节点，提供图片、音频、视频的异步生成任务提交与状态查询。

## 端口
8128

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /generate/{media_type}` - 创建媒体生成任务（media_type: image/audio/video）
- `GET /task/{task_id}` - 查询任务状态与结果
