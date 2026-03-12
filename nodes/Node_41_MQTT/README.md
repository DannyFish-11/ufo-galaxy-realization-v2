# Node_41_MQTT

## 简介

MQTT 消息队列节点，使用 paho-mqtt 实现 MQTT 发布/订阅消息通信

## 端口

默认端口：**8041**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, paho-mqtt>=1.6.1
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  MQTT_BROKER=localhost
  MQTT_PORT=1883
  MQTT_USERNAME=
  MQTT_PASSWORD=
  PORT=8041
```

## 主要 API

- `GET /health`
- `POST /connect`
- `POST /disconnect`
- `POST /publish`
- `POST /subscribe`
- `POST /unsubscribe`
- `GET /messages`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8041/health
```
