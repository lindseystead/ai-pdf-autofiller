FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && adduser --disabled-password --gecos "" appuser

COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser pyproject.toml README.md ./

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["python", "-m", "uvicorn", "pdf_autofiller.api_service:app", "--host", "0.0.0.0", "--port", "8000"]
