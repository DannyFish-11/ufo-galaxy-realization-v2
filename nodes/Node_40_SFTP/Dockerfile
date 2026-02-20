FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx paramiko

COPY main.py .

EXPOSE 8040

CMD ["python", "main.py"]
