FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx redis pyjwt
COPY main.py .
EXPOSE 8001
CMD ["python", "main.py"]
