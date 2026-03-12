# Node_42_CANbus

## 简介

CAN 总线通信节点，使用 python-can 实现 CAN 总线报文的发送与接收

## 端口

默认端口：**8042**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, python-can>=4.3.1

系统依赖：socketcan 接口（Linux）或 Peak/Vector 驱动（Windows）
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8042
```

## 主要 API

- `GET /health - 健康检查（python-can 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `POST /connect - 连接 CAN 接口（body: {interface, channel, bitrate}）`
- `POST /disconnect - 断开连接`
- `POST /send - 发送 CAN 帧（body: {arbitration_id, data, is_extended_id}）`
- `GET /receive - 接收待处理帧（query: limit）`
- `GET /filters - 获取消息过滤器`
- `POST /filters - 设置消息过滤器`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8042/health
```
