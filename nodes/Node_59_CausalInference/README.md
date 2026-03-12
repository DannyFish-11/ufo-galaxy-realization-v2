# Node_59_CausalInference

## 简介

因果推断节点，实现因果图构建、平均处理效应（ATE）估计、do-演算和反事实推理

## 端口

默认端口：**8059**（可通过 `PORT` 环境变量覆盖）

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
  PORT=8059
```

## 主要 API

- `GET /health`
- `POST /build_graph`
- `POST /ate`
- `POST /do_calculus`
- `POST /counterfactual`
- `POST /mcp/call`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8059/health
```
