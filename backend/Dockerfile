FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libGL/glib are required by opencv; tesseract backs the OCR fallback path
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x scripts/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["sh", "scripts/entrypoint.sh"]

# Shell form so Railway's $PORT is expanded. Workers override the command.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
