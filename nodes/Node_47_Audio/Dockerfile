FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx sounddevice

COPY main.py .

EXPOSE 8047

CMD ["python", "main.py"]
