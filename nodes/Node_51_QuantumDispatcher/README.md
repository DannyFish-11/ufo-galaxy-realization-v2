# Node_51_QuantumDispatcher

## 简介

量子任务分派节点，将量子计算任务分派到最优后端（本地 Qiskit 或云端量子计算机）

## 端口

默认端口：**8051**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, httpx>=0.26.0, qiskit>=0.45.0, qiskit-aer>=0.13.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  IBM_QUANTUM_TOKEN=  # IBM Quantum API Token（可选，本地模拟无需）
  PORT=8051
```

## 主要 API

- `GET /health`
- `POST /dispatch`
- `POST /analyze`
- `GET /algorithms`
- `GET /stats`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8051/health
```
