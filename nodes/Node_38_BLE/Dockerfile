FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx bleak

COPY main.py .

EXPOSE 8038

CMD ["python", "main.py"]
