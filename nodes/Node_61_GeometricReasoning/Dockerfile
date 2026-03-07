FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx shapely

COPY main.py .

EXPOSE 8061

RUN addgroup --system --gid 1000 galaxy && adduser --system --uid 1000 --ingroup galaxy --no-create-home galaxy
RUN chown -R galaxy:galaxy /app
USER galaxy

CMD ["python", "main.py"]
