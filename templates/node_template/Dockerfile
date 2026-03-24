# Dockerfile for Node_XXX_YourNodeName
#
# Replace <PORT> with the port declared in node_dependencies.json.
# Required by the node contract for active nodes.

FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy node source files.
COPY . .

# Expose the node's declared port.
EXPOSE <PORT>

# Healthcheck — the /health endpoint must respond within 10 s at startup.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:<PORT>/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "<PORT>"]
