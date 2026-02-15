FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx opencv-python

COPY main.py .

EXPOSE 8046

CMD ["python", "main.py"]
