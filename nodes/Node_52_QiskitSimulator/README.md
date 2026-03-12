# Node_52_QiskitSimulator

## 简介

Qiskit 量子线路模拟器节点，执行量子线路模拟，支持 Qiskit 真实模拟和内置模拟器

## 端口

默认端口：**8052**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, qiskit>=0.45.0, qiskit-aer>=0.13.0
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8052
```

## 主要 API

- `GET /health`
- `POST /simulate`
- `POST /interpret`
- `GET /backends`
- `GET /stats`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8052/health
```
