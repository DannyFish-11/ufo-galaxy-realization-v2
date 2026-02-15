FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pyobjc

COPY main.py .

EXPOSE 8035

CMD ["python", "main.py"]
