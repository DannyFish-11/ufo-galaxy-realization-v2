# Node_50_Transformer

## 简介

NLU/变换器节点，提供自然语言理解、命令分解、对话管理和命令提取功能

## 端口

默认端口：**8050**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn[standard]>=0.27.0, websockets>=12.0, requests>=2.31.0, python-multipart>=0.0.6
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8050
```

## 主要 API

- `GET /health`
- `GET /tools`
- `POST /understand`
- `POST /decompose`
- `POST /dialog`
- `POST /extract_command`
- `POST /mcp/call`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8050/health
```
