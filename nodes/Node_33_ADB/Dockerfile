FROM python:3.11-slim

WORKDIR /app

# Install ADB
RUN apt-get update && apt-get install -y \
    android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    pydantic==2.5.3

COPY main.py .

EXPOSE 8033
CMD ["python", "main.py"]
