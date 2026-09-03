FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY apps ./apps
COPY data ./data
COPY fixtures ./fixtures
COPY policies ./policies
COPY reports ./reports
COPY schemas ./schemas
RUN python -m pip install --no-cache-dir "pip==26.2.1" && \
    python -m pip install --no-cache-dir .
RUN addgroup --system reconx && \
    adduser --system --ingroup reconx --home /nonexistent --no-create-home reconx

USER reconx

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn reconx.api:app --app-dir src --host 0.0.0.0 --port \"${PORT:-8000}\""]
