FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx aiosmtplib

COPY main.py .

EXPOSE 8016

CMD ["python", "main.py"]
