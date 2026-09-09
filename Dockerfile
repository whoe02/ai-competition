# ---- stage 1: build the web bundle -------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN npm ci

COPY packages/contracts packages/contracts
COPY apps/web apps/web
RUN npm --workspace apps/web run build

# ---- stage 2: the app image --------------------------------------------
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml ./
COPY apps/api/kira ./kira
RUN pip install --no-cache-dir ".[capture]"

COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/docker-entrypoint.sh ./docker-entrypoint.sh

# The bundle lands beside the package, where create_app() looks for it.
COPY --from=web /build/apps/web/dist ./kira/static

RUN adduser --system --home /home/kira kira && chown -R kira /app /home/kira
USER kira

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
