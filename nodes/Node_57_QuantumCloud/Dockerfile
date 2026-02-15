FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx qiskit-ibm-runtime

COPY main.py .

EXPOSE 8057

CMD ["python", "main.py"]
