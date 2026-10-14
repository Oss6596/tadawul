# Web app image for Cloudflare Containers (linux/amd64).
# Official python image via AWS's public mirror of Docker Hub (avoids Docker Hub rate limits).
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app
COPY requirements-web.txt .
# The optional "ca_bundle" build secret is only for build machines behind a TLS-inspecting
# proxy; it is mounted for this step only and never stored in the image.
RUN --mount=type=secret,id=ca_bundle \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install -r requirements-web.txt

COPY tadawul_ichimoku ./tadawul_ichimoku
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8080
# One worker so the in-memory cache is shared; threads handle concurrent requests.
# Long timeout because a watchlist scan fetches symbols one after another.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 180 'tadawul_ichimoku.web.app:create_app()'"]
