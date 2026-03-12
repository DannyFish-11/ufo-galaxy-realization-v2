# Node_34_Scrcpy

## 简介

Android 屏幕镜像与控制节点，通过 scrcpy/adb 实现屏幕截图、录屏和输入控制

## 端口

默认端口：**8034**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3

系统依赖：`adb`、`scrcpy`（可选）需安装在 PATH 中
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  ADB_PATH=adb
  SCRCPY_PATH=scrcpy
  PORT=8034
```

## 主要 API

- `GET /health`
- `GET /devices`
- `POST /tap`
- `POST /swipe`
- `POST /input`
- `POST /key`
- `GET /screenshot`
- `POST /install`
- `GET /packages`
- `GET /device_info`
- `POST /mcp/call`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8034/health
```
