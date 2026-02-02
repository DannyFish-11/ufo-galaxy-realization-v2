FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pytz

COPY main.py .

EXPOSE 8023

CMD ["python", "main.py"]
