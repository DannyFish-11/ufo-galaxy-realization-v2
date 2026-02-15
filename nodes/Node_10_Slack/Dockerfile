FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx slack_sdk

COPY main.py .

EXPOSE 8010

CMD ["python", "main.py"]
