# ─────────────────────────────────────────────────────────────────────────
# ConvergenceKanban — production Docker image
# Single-stage: Python 3.12 slim + dependencies + app.
# Run with: docker run -p 8666:8666 -v $(pwd)/data:/app/data --env-file .env convergencekanban
# ─────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps — none required for SQLite + urllib; just basic certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer)
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# Copy app
COPY . /app/

# Default port; overridable via PORT env or compose
ENV PORT=8666 \
    KANBAN_DATA_DIR=/app/data

# Create the data dir (will be mounted as a volume in production)
RUN mkdir -p /app/data

EXPOSE 8666

# Healthcheck — kanban responds on /api/health (if defined) or just /
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/').read()" || exit 1

# Use tini for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "app.py"]
