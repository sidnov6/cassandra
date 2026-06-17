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

# ---- stage 2: python runtime (HF-canonical non-root user) ----
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CASSANDRA_SEC_UA="CASSANDRA-space contact@example.com" \
    CASSANDRA_DATA_DIR=/home/user/app/data
WORKDIR /home/user/app

COPY --chown=user requirements-space.txt ./
RUN pip install --no-cache-dir --user -r requirements-space.txt

COPY --chown=user cassandra/ ./cassandra/
COPY --chown=user seed/ ./seed/
COPY --chown=user data/models/ ./data/models/
COPY --chown=user --from=web /web/out ./frontend/out

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "cassandra.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
