FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pytesseract

COPY main.py .

EXPOSE 8015

CMD ["python", "main.py"]
