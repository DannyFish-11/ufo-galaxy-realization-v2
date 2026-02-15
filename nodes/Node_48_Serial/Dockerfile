FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pyserial

COPY main.py .

EXPOSE 8048

CMD ["python", "main.py"]
