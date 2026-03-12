# Node_49_OctoPrint

## 简介

OctoPrint 3D打印机控制节点，通过 OctoPrint API 管理和控制 3D 打印机

## 端口

默认端口：**8049**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, httpx>=0.26.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  OCTOPRINT_URL=http://localhost:5000
  OCTOPRINT_API_KEY=  # OctoPrint API 密钥（必填）
  PORT=8049
```

## 主要 API

- `GET /health`
- `GET /status`
- `POST /execute - 执行打印命令（connect/disconnect/print/cancel/pause/resume/home/temperature）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8049/health
```
