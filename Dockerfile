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
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn reconx.api:app --app-dir src --host 0.0.0.0 --port \"${PORT:-8000}\""]
