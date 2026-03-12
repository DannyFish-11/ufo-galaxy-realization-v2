# Node_46_Camera

## 简介

摄像头节点，使用 OpenCV 实现摄像头设备枚举、拍照、录像和实时帧获取

## 端口

默认端口：**8046**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, opencv-python>=4.8.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8046
```

## 主要 API

- `GET /health - 健康检查（cv2 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `GET /devices - 枚举可用摄像头（最多扫描10个）`
- `POST /capture - 拍照（body: {device_id, width, height}，返回 base64 JPEG）`
- `POST /record/start - 开始录像（body: {device_id, output_path, fps}）`
- `POST /record/stop - 停止录像`
- `GET /stream/frame - 获取当前帧（query: device_id，返回 base64 JPEG）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8046/health
```
