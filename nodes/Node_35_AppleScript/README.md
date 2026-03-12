# Node_35_AppleScript

## 简介

macOS AppleScript 自动化节点，通过 osascript 执行 AppleScript 脚本实现 macOS 系统自动化

## 端口

默认端口：**8035**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3

系统依赖：macOS 系统（`osascript`）
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8035
```

## 主要 API

- `GET /health - 健康检查（非 macOS 环境返回 degraded）`
- `GET /status - 节点状态`
- `POST /execute - 执行 AppleScript 字符串（body: {script, timeout}）`
- `POST /execute_file - 执行 AppleScript 文件（body: {path, timeout}）`
- `GET /apps - 列出运行中的 macOS 应用`
- `POST /notify - 显示 macOS 通知（body: {title, message, subtitle}）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8035/health
```
