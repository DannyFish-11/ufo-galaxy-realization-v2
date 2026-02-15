FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx python-can

COPY main.py .

EXPOSE 8042

CMD ["python", "main.py"]
