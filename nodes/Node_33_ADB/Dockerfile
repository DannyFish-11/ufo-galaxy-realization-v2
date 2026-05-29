FROM python:3.11-slim-bookworm

# Security: non-root user
RUN groupadd -r galaxy && useradd -r -g galaxy -s /bin/false galaxy

WORKDIR /app

# Install common dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy node code
COPY . /app/

# Switch to non-root
USER galaxy

# Expose service port
EXPOSE 8033

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8033/health')" || exit 1

CMD ["python", "main.py"]
