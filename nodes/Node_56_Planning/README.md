# Node_56_Planning

## 简介

规划调度节点，实现拓扑排序、任务调度、最短路径和关键路径分析

## 端口

默认端口：**9002**（可通过 `PORT` 环境变量覆盖）

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
  PORT=9002
```

## 主要 API

- `GET /health`
- `POST /topological_sort`
- `POST /schedule`
- `POST /shortest_path`
- `POST /critical_path`
- `POST /mcp/call`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:9002/health
```
