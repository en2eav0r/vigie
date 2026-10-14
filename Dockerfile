FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY data/replays ./data/replays

# Runs as an unprivileged user; the only writable place is the state volume.
RUN useradd --create-home --uid 10001 vigie && mkdir -p /app/state && chown vigie /app/state
USER vigie
ENV VIGIE_DB=/app/state/vigie.db

EXPOSE 8740
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8740/api/health', timeout=4).status == 200 else 1)"
# No access log: request lines would record the links people check (privacy, N06).
CMD ["uvicorn", "server.api:app", "--host", "0.0.0.0", "--port", "8740", "--no-access-log", "--proxy-headers"]
