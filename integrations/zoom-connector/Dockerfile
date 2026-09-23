FROM python:3.12-slim-bookworm AS base
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ZOOM_DATA_DIR=/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown 10001:10001 /data
COPY zoom_connector ./zoom_connector
USER 10001:10001

FROM base AS api
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8021/health', timeout=3).close()"]
CMD ["uvicorn", "zoom_connector.api:app", "--host", "0.0.0.0", "--port", "8021", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

FROM base AS worker
CMD ["python", "-m", "zoom_connector.worker"]

FROM python:3.12-bookworm AS rtms-worker
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ZOOM_DATA_DIR=/data
COPY requirements.txt requirements-rtms.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-rtms.txt && python -c "import rtms; print('Zoom RTMS SDK import OK')" \
    && mkdir /data && chown 10001:10001 /data
COPY zoom_connector ./zoom_connector
USER 10001:10001
HEALTHCHECK NONE
CMD ["python", "-m", "zoom_connector.rtms_worker"]
