FROM python:3.12-slim-bookworm AS base
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 CONNECTOR_DATA_DIR=/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir /data && chown 10001:10001 /data
COPY meeting_gateway ./meeting_gateway
USER 10001:10001
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3).close()"]
CMD ["uvicorn", "meeting_gateway.api:app", "--host", "0.0.0.0", "--port", "8010"]

FROM python:3.12-slim-bookworm AS pjsip-build
ARG PJSIP_VERSION=2.16
RUN apt-get update && apt-get install -y --no-install-recommends build-essential swig libssl-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl --fail --location --retry 3 https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz -o pj.tar.gz \
    && tar xzf pj.tar.gz --strip-components=1
RUN ./configure CFLAGS="-fPIC" CXXFLAGS="-fPIC" --disable-video --disable-sound \
    && make dep && make -j2
RUN pip install --no-cache-dir setuptools wheel \
    && cd pjsip-apps/src/swig/python && make \
    && python setup.py bdist_wheel --dist-dir /wheels

FROM base AS assistant
USER root
COPY --from=pjsip-build /wheels /wheels
COPY --from=pjsip-build /build/COPYING /usr/share/doc/pjsip/COPYING
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-m", "meeting_gateway.worker_health"]
CMD ["python", "-m", "meeting_gateway.automation"]

FROM base AS api
