# Node_30_Reserved

## 简介

通用插件框架节点，支持动态加载、执行和管理Python插件模块

## 端口

默认端口：**8030**（可通过 `PORT` 环境变量覆盖）

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
  PORT=8030
```

## 主要 API

- `GET /health - 健康检查`
- `GET /status - 详细状态`
- `GET /plugins - 列出已加载插件`
- `POST /plugins/load - 加载插件（body: {path, name}）`
- `POST /plugins/execute - 执行插件动作（body: {name, action, params}）`
- `POST /plugins/unload - 卸载插件（body: {name}）`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8030/health
```
