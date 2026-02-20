FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx edge-tts

COPY main.py .

EXPOSE 8017

CMD ["python", "main.py"]
