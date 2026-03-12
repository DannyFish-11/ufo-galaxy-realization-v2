# Node_40_SFTP

## 简介

SFTP 文件传输节点，使用 asyncssh 实现安全文件传输协议（SFTP）操作

## 端口

默认端口：**8040**（可通过 `PORT` 环境变量覆盖）

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
  PORT=8040
```

## 主要 API

- `GET /health - 健康检查`
- `GET /status - 节点状态`
- `POST /connect - 建立 SFTP 连接（body: {host, port, username, password/private_key}）`
- `POST /disconnect - 断开连接（query: conn_id）`
- `POST /upload - 上传文件（body: {conn_id, local_path, remote_path}）`
- `POST /download - 下载文件`
- `GET /list - 列出远程目录（query: conn_id, remote_path）`
- `POST /mkdir - 创建远程目录`
- `DELETE /delete - 删除远程文件`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8040/health
```
