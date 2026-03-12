# Node_57_QuantumCloud

## 简介

量子云端节点，通过 Qiskit/IBM Quantum 执行量子线路，支持 Bell 态和 Grover 算法

## 端口

默认端口：**8057**（可通过 `PORT` 环境变量覆盖）

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
  IBM_QUANTUM_TOKEN=  # IBM Quantum API Token
  PORT=8057
```

## 主要 API

- `GET /health`
- `POST /run_circuit`
- `POST /bell_state`
- `POST /grover`
- `GET /backends`
- `POST /mcp/call`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8057/health
```
