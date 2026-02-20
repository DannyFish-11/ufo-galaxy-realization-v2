FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx PyGithub

COPY main.py .

EXPOSE 8011

CMD ["python", "main.py"]
