FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx psycopg2-binary

COPY main.py .

EXPOSE 8012

CMD ["python", "main.py"]
