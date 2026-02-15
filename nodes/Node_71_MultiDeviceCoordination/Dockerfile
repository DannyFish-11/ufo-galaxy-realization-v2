FROM python:3.11-slim

LABEL maintainer="UFO Galaxy Team"
LABEL description="Node 71 - Multi-Device Coordination Engine v2.1"
LABEL version="2.1.0"

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV NODE71_HOST=0.0.0.0
ENV NODE71_PORT=8071

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8071/health')" || exit 1

EXPOSE 8071

CMD ["python", "main.py"]
