FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq5 poppler-utils tesseract-ocr curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/ ./
RUN pip install --upgrade pip && pip install .

COPY config/ ./config/
RUN useradd --create-home --uid 10001 app && chown -R app:app /srv
USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
USER root
RUN pip install '.[dev]'
USER app
