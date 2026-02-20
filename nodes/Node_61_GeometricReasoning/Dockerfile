FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx shapely

COPY main.py .

EXPOSE 8061

CMD ["python", "main.py"]
