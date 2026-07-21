FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XIAOYI_HOST=0.0.0.0 \
    XIAOYI_PORT=8010

WORKDIR /app

RUN groupadd --system xiaoyi && useradd --system --gid xiaoyi --home-dir /app xiaoyi

COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY --chown=xiaoyi:xiaoyi . .
RUN python scripts/build_index.py \
    && mkdir -p data/rl_runs data/kb_pending runtime \
    && chown -R xiaoyi:xiaoyi data runtime

USER xiaoyi
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health/ready', timeout=3).read()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "1", "--no-server-header"]
