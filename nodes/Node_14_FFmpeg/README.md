# Node_14_FFmpeg

FFmpeg 多媒体处理节点，提供视频转码、音频处理、格式转换功能。

## 端口
8014

## 环境变量
- `FFMPEG_PATH`: FFmpeg 可执行文件路径（默认 ffmpeg）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /transcode` - 视频转码
- `POST /extract-audio` - 提取音频
- `POST /thumbnail` - 生成缩略图
- `GET /formats` - 支持的格式
