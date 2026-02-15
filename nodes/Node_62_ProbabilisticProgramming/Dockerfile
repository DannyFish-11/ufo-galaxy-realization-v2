FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pymc

COPY main.py .

EXPOSE 8062

CMD ["python", "main.py"]
