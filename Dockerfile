FROM python:3.11-slim

# Logs straight to stdout (Cloud Logging) and no .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy and install requirements first, so this layer is cached
# when only the code changes
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Cloud Run sets $PORT (8080 by default). One worker with several threads,
# since Cloud Run scales by adding instances. Timeout is handled by Cloud Run.
CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 --timeout 0 server:app
