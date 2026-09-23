# Zoom Connector для Jinalys AI

Отдельный backend получает готовые Zoom Cloud Recordings, читает расписание пользователей и
принимает Realtime Media Streams (RTMS) с живым аудио, транскриптом и именами участников.
Готовые записи и завершённый RTMS WAV отправляются в общий [приёмник Jinalys AI](../../backend/INGEST.md).

## Что реализовано

- Проверка подписи и защита от повторной доставки webhook.
- `recording.completed`: выбор одного предпочтительного аудиофайла, фоновое скачивание и доставка.
- Server-to-Server OAuth с часовым access token и автоматическим обновлением.
- Календарь организованных встреч и приглашений для настроенных пользователей.
- `meeting.rtms_started`: официальный Zoom RTMS SDK, смешанный PCM 16 kHz WAV, live-транскрипт,
  имена участников, смена активного говорящего и события входа/выхода.
- Необязательный запрос запуска RTMS после `meeting.started`; для основной эксплуатации лучше
  включить RTMS auto-start в Zoom.
- SQLite-очереди, идемпотентность, восстановление worker после перезапуска и Docker Compose.

Cloud Recording и RTMS — независимые режимы. Если включить оба, Jinalys AI может получить две записи
одной встречи: облачную и созданную из RTMS. Поле `source` отличает `zoom-cloud` от `zoom-rtms`.

## Запуск

```sh
cd integrations/zoom-connector
python scripts/init_config.py
# Заполните .env параметрами Zoom и Jinalys AI.
docker compose up -d --build connector worker
```

Опубликуйте `/webhooks/zoom` через корпоративный HTTPS reverse proxy и укажите этот URL в Zoom
Marketplace. API администратора остаётся на `127.0.0.1:8021`; Swagger — `/docs`.

После настройки RTMS:

```sh
docker compose --profile rtms up -d --build
docker compose logs --tail 100 connector worker rtms-worker
```

RTMS SDK поддерживает Linux x86_64 и macOS arm64. В Compose используется Linux x86_64.
Windows запускает RTMS через Docker Desktop, а не как локальный Python-процесс.

## API

Для `/api/*` нужен `X-API-Key: ZOOM_CONNECTOR_API_KEY`. Webhook использует подпись Zoom.

- `GET /api/zoom/calendar?user_id=...` — кеш встреч.
- `GET /api/zoom/recordings` — задания Cloud Recording.
- `GET /api/zoom/rtms` — активные и завершённые RTMS-потоки.
- `GET /api/zoom/rtms/{id}/transcript` — текущие реплики с `user_name`, `user_id` и timestamp.
- `GET /health` — liveness API; не подтверждает доступ к Zoom или запуск workers.

Подробности: [настройка Zoom](docs/ZOOM_SETUP.md), [календарь](docs/CALENDAR.md),
[состояния и восстановление](docs/AUTOMATION.md), [источники и ограничения проверки](docs/SOURCES.md).

## Проверка разработки

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
python scripts/init_config.py
docker compose --profile rtms build
```

Тесты не подключаются к чужим встречам и не скачивают реальные записи. Полная приёмка требует
Zoom-аккаунт с Cloud Recording и RTMS, публичный HTTPS webhook и тестовую встречу с уведомлёнными
участниками.
