# Node_43_MAVLink

## 简介

MAVLink 无人机通信节点，使用 pymavlink 实现 MAVLink 协议的无人机控制

## 端口

默认端口：**8043**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, pymavlink>=2.4.37
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8043
```

## 主要 API

- `GET /health`
- `POST /connect`
- `POST /disconnect`
- `POST /arm`
- `POST /disarm`
- `POST /takeoff`
- `GET /telemetry/{connection_id}`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8043/health
```
