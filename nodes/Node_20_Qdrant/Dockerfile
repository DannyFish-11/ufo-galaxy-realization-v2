FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx qdrant-client

COPY main.py .

EXPOSE 8020

CMD ["python", "main.py"]
