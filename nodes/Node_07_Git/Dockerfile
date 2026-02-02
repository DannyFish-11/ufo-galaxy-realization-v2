FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.109.0 uvicorn[standard]==0.27.0
COPY main.py .
EXPOSE 8007
CMD ["python", "main.py"]
