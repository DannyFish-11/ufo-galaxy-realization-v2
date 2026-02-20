FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn[standard]==0.27.0 \
    httpx==0.26.0 \
    pydantic==2.5.3

COPY main.py .

EXPOSE 8049
CMD ["python", "main.py"]
