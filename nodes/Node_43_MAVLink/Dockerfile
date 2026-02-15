FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pymavlink

COPY main.py .

EXPOSE 8043

CMD ["python", "main.py"]
