FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx paho-mqtt

COPY main.py .

EXPOSE 8041

CMD ["python", "main.py"]
