FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx aiosqlite

COPY main.py .

EXPOSE 8013

CMD ["python", "main.py"]
