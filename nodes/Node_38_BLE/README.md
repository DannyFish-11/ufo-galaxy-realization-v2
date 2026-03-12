# Node_38_BLE

## 简介

蓝牙低功耗（BLE）节点，使用 bleak 库实现 BLE 设备扫描、连接和数据读写

## 端口

默认端口：**8038**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, bleak>=0.21.1
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8038
```

## 主要 API

- `GET /health - 健康检查`
- `GET /status - 节点状态`
- `POST /scan - 扫描 BLE 设备（body: {timeout}）`
- `POST /connect - 连接设备（body: {address}）`
- `POST /disconnect - 断开连接（body: {address}）`
- `GET /services/{address} - 列出设备服务`
- `POST /read - 读取特征值（body: {address, characteristic_uuid}）`
- `POST /write - 写入特征值（body: {address, characteristic_uuid, data}）`
- `POST /notify/subscribe - 订阅通知`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8038/health
```
