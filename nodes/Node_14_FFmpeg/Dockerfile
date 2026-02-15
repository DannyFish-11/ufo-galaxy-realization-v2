FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx ffmpeg-python

COPY main.py .

EXPOSE 8014

CMD ["python", "main.py"]
