# LedgerMind server (FastAPI). Built from the project root: docker build -f backend/Dockerfile .
# Settings come from the environment (backend/.env.production on the server); no secrets are copied in.

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app

# LibreOffice (no screen) works out the workbook's formulas before it is saved, as Excel does on a Windows computer
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc-nogui \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
RUN useradd --create-home app && mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000
# Two workers: a workbook build takes about a minute and should not hold up everyone else
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
