# Node_39_SSH

## 简介

SSH 远程连接节点，使用 asyncssh 实现 SSH 命令执行和文件传输

## 端口

默认端口：**8039**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, asyncssh>=2.14.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8039
```

## 主要 API

- `GET /health`
- `POST /connect`
- `POST /disconnect`
- `POST /execute`
- `POST /upload`
- `POST /download`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8039/health
```
