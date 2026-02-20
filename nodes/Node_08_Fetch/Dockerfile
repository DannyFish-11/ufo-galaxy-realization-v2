FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx httpx

COPY main.py .

EXPOSE 8008

CMD ["python", "main.py"]
