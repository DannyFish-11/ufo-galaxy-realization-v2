# Node_33_ADB

## 简介

Android ADB 控制节点，通过 adb 命令实现 Android 设备的自动化控制

## 端口

默认端口：**8033**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3

系统依赖：`adb`（Android Debug Bridge）需要安装在 PATH 中
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  ADB_PATH=adb  # adb 可执行文件路径
  PORT=8033
```

## 主要 API

- `GET /health - 健康检查`
- `GET /status - 节点状态`
- `POST /execute - 执行 ADB 操作（tap/swipe/shell/screenshot/input/keyevent）`
- `GET /devices - 列出已连接设备`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8033/health
```
