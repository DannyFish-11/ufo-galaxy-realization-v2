# Node_53_GraphLogic

## 简介

图逻辑推理节点，使用 networkx 实现图算法（最短路径、连通分量、拓扑排序等）

## 端口

默认端口：**8053**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, networkx>=3.2.1
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8053
```

## 主要 API

- `GET /health`
- `POST /shortest_path`
- `POST /connected_components`
- `POST /topological_sort`
- `POST /cycle_detection`
- `POST /mst`
- `POST /logic/evaluate`
- `POST /centrality`
- `POST /community`
- `POST /clustering`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8053/health
```
