FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx networkx

COPY main.py .

EXPOSE 8053

CMD ["python", "main.py"]
