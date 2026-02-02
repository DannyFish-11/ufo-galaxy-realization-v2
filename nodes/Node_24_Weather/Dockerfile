FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx requests

COPY main.py .

EXPOSE 8024

CMD ["python", "main.py"]
