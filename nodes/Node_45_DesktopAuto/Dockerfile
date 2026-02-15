FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx pyautogui

COPY main.py .

EXPOSE 8045

CMD ["python", "main.py"]
