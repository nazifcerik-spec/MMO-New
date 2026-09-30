# syntax=docker/dockerfile:1
# Multi-stage, non-root backend image.
# Optional corporate/egress-proxy CA: `docker build --secret id=extra_ca,src=/path/ca.pem ...`
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

FROM base AS deps
ARG HTTPS_PROXY
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false sh -c '\
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir "uv>=0.8,<0.9" && uv sync --frozen --no-dev --no-install-project'

FROM base AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=deps /app/.venv /app/.venv
COPY --chown=app:app . .
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
