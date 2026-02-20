FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx googlesearch-python

COPY main.py .

EXPOSE 8025

CMD ["python", "main.py"]
