# syntax=docker/dockerfile:1
# CASSANDRA — single-service deploy (Hugging Face Space): FastAPI serves /api + the static
# Next.js workstation export on one port (7860). SSE works because it's same-origin.

# ---- stage 1: build the static Next.js export ----
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
ENV NEXT_PUBLIC_BACKEND_URL=""
RUN npm run build         # next.config output:"export" -> /web/out

# ---- stage 2: python runtime ----
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-space.txt ./
RUN pip install --no-cache-dir -r requirements-space.txt

COPY cassandra/ ./cassandra/
COPY seed/ ./seed/
COPY data/models/ ./data/models/
COPY --from=web /web/out ./frontend/out

ENV CASSANDRA_SEC_UA="CASSANDRA-space contact@example.com" \
    CASSANDRA_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "cassandra.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
