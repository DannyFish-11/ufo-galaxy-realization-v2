# Node_17_EdgeTTS

文字转语音节点，使用 Microsoft Edge TTS 服务。

## 端口
8017

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /synthesize` - 文字转语音
- `GET /voices` - 获取可用声音列表
