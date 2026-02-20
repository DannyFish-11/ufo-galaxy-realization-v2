FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx deepl

COPY main.py .

EXPOSE 8018

CMD ["python", "main.py"]
