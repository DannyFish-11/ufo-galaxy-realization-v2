# Node_47_Audio

## 简介

音频节点，使用 sounddevice 实现音频设备枚举、录音和播放功能

## 端口

默认端口：**8047**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, sounddevice>=0.4.6, scipy>=1.11.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8047
```

## 主要 API

- `GET /health - 健康检查（sounddevice 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `GET /devices - 列出音频输入/输出设备`
- `POST /record/start - 开始录音（body: {device, samplerate, channels, duration}）`
- `POST /record/stop - 停止录音（返回 base64 编码 WAV 数据）`
- `POST /play - 播放音频（body: {data_base64  或 file_path}）`
- `POST /play/stop - 停止播放`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8047/health
```
