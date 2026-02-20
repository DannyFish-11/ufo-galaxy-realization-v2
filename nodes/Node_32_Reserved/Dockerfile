FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY main.py .
EXPOSE 8032
CMD ["python", "main.py"]
