# Node_44_NFC

## 简介

NFC 近场通信节点，使用 nfcpy 实现 NFC 标签的扫描、读取和写入

## 端口

默认端口：**8044**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, nfcpy>=1.0.4

系统依赖：libusb（USB NFC 读卡器）
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  NFC_DEVICE=  # NFC 设备路径，如 usb:072f:2200
  PORT=8044
```

## 主要 API

- `GET /health - 健康检查（nfcpy 不可用时返回 degraded）`
- `GET /status - 节点状态`
- `GET /devices - 列出可用 NFC 设备`
- `GET /scan - 扫描 NFC 标签（query: timeout）`
- `POST /read - 读取 NFC 标签数据（body: {device}）`
- `POST /write - 写入 NFC 标签数据（body: {data, device}）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8044/health
```
