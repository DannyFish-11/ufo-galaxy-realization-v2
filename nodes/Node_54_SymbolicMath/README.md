# Node_54_SymbolicMath

## 简介

符号数学节点，使用 sympy 进行符号计算、数学证明和方程求解

## 端口

默认端口：**8054**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, sympy>=1.12
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8054
```

## 主要 API

- `GET /health`
- `POST /verify`
- `POST /simplify`
- `POST /evaluate`
- `POST /check-equality`
- `POST /sympy/compute`
- `POST /sympy/solve`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8054/health
```
