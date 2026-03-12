# Node_31_Reserved

## 简介

通用插件框架节点（第二预留实例），支持独立部署的插件管理

## 端口

默认端口：**8031**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8031
```

## 主要 API

- `GET /health`
- `GET /status`
- `GET /plugins`
- `POST /plugins/load`
- `POST /plugins/execute`
- `POST /plugins/unload`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8031/health
```
