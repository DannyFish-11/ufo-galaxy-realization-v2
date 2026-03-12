# Node_58_ModelRouter

## 简介

模型路由节点，智能路由 AI 请求到最优 LLM（OpenAI/Claude/Gemini/本地模型）

## 端口

默认端口：**8058**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, httpx>=0.26.0, pydantic>=2.5.3, pydantic-settings==2.1.0, python-multipart>=0.0.6
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  OPENAI_API_KEY=
  ANTHROPIC_API_KEY=
  GOOGLE_API_KEY=
  PORT=8058
```

## 主要 API

- `GET /health`
- `POST /route`
- `POST /chat`
- `GET /analyze/{prompt}`
- `GET /stats`

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8058/health
```
