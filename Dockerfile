FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser backend/ backend/

ENV PYTHONPATH=/app/backend
EXPOSE 8000

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
