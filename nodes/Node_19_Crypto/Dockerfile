FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx cryptography

COPY main.py .

EXPOSE 8019

CMD ["python", "main.py"]
