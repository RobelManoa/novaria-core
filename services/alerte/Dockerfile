# --- Image du service alerte : construction multi-étapes, utilisateur non-root ---
FROM python:3.15-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

FROM base AS deps
COPY requirements.txt .
RUN pip install --require-hashes --only-binary :all: --prefix=/install -r requirements.txt

FROM base AS runtime
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}
COPY --from=deps /install /usr/local
COPY app ./app
RUN useradd --system --uid 10001 appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
