# Два образа из одного файла (контекст сборки — корень репозитория):
#   api    — FastAPI + фронтенд, лёгкий
#   worker — конвейер: ffmpeg, faster-whisper, диаризация; модели встроены в образ
FROM python:3.12-slim AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data


FROM base AS api
# DejaVu — кириллица и казахские буквы (ә, ғ, қ, ң, ө, ұ, ү, һ, і) в PDF
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY backend/app ./app
COPY backend/tests ./tests
COPY frontend ./frontend
ENV FRONTEND_DIR=/srv/frontend
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS worker
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-local.txt .
RUN pip install --no-cache-dir -r requirements-local.txt
# Модели запекаются в образ: в закрытом контуре интернет на рантайме не нужен.
ARG WHISPER_MODEL=small
ENV MODELS_DIR=/models
COPY backend/download_models.py .
RUN python download_models.py --whisper "${WHISPER_MODEL}"
COPY backend/app ./app
ENV HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
CMD ["python", "-m", "app.worker"]
