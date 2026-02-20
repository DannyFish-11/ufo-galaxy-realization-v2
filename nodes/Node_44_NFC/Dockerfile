FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx nfcpy

COPY main.py .

EXPOSE 8044

CMD ["python", "main.py"]
