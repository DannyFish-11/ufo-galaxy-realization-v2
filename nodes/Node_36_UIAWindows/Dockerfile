FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pywinauto

COPY main.py .

EXPOSE 8036

CMD ["python", "main.py"]
