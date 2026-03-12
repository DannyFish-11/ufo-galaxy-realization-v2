# Node_48_Serial

## 简介

串口通信节点，使用 pyserial 实现串口设备的连接、数据发送和接收

## 端口

默认端口：**8048**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, pyserial>=3.5, pyserial-asyncio>=0.6
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8048
```

## 主要 API

- `GET /health - 健康检查（pyserial 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `GET /ports - 列出可用串口（返回设备名、描述和硬件ID）`
- `POST /connect - 连接串口（body: {port, baudrate, bytesize, parity, stopbits}）`
- `POST /disconnect - 断开串口（query: conn_id）`
- `POST /send - 发送数据（body: {conn_id, data, encoding=text|hex}）`
- `POST /read - 读取数据（body: {conn_id, max_bytes, timeout}）`
- `GET /connections - 列出活跃连接`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8048/health
```
