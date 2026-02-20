FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

COPY main.py .

ENV NODE_ID=51
ENV NODE_NAME=QuantumDispatcher
ENV LOG_LEVEL=INFO

EXPOSE 8051

CMD ["python", "main.py"]
