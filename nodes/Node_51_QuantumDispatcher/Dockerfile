FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

COPY main.py .

ENV NODE_ID=51
ENV NODE_NAME=QuantumDispatcher
ENV LOG_LEVEL=INFO

EXPOSE 8051

RUN addgroup --system --gid 1000 galaxy && adduser --system --uid 1000 --ingroup galaxy --no-create-home galaxy
RUN chown -R galaxy:galaxy /app
USER galaxy

CMD ["python", "main.py"]
