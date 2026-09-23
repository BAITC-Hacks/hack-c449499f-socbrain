# Приём записей Cisco/Zoom и локальное распознавание

HTTP-приёмник принимает закрытые файлы Cisco и Zoom, сохраняет файл полностью и только затем создаёт
задание SQLite. Отдельный STT-worker использует существующий `FasterWhisperProvider` напрямую.
Внешний OpenAI-провайдер в этом сценарии не вызывается; поведение прежней CLI не изменено.

## Приёмник

Из каталога `backend`:

```sh
python scripts/init_ingest.py
docker compose -f compose.ingest.yml up -d --build receiver
```

Скрипт создаёт `.env.ingest` со случайным `SOCBRAIN_API_KEY`, не печатает ключ и не перезаписывает файл.
Приёмник доступен на `127.0.0.1:8020`; API-документация — `/docs`, JSON-спецификация — `/openapi.json`.
Для обоих методов `/api/recordings` нужен заголовок `X-API-Key` с SOCBRAIN_API_KEY.
Healthcheck `/health` не проверяет наличие запущенного STT-worker.

- POST `/api/recordings`: multipart `file`, `title`, `meeting_date=YYYY-MM-DD`, `participants_notified=true`,
  `source` (`cms`, `zoom-cloud` или `zoom-rtms`).
- GET `/api/recordings/{id}`: статус queued/processing/done/error; при done — язык, текст и segments с start/end/text.
- `Idempotency-Key` необязателен, но Cisco-коннектор передаёт его всегда. Повтор того же файла с тем же ключом
  возвращает прежний id. Другие байты, название или дата с тем же ключом дают HTTP 409.

`INGEST_MAX_BYTES` ограничивает сохраняемый файл (по умолчанию 1 GiB). Multipart предварительно
разбирается веб-сервером; ограничение размера входящего запроса задайте также на reverse proxy.
Поддерживаются WAV/MP3/MP4/M4A/OGG/FLAC/WEBM/OPUS; декодирование проверяется STT-worker.

## Локальный STT-worker

Подготовьте модель **faster-whisper / CTranslate2** и перенесите её полный каталог в
`backend/models/faster-whisper-small`. Это не оригинальный файл OpenAI Whisper `.pt`.
Среди файлов должны быть `model.bin`, `config.json`, tokenizer и остальные файлы модели.
Путь задаётся через WHISPER_MODEL; CPU по умолчанию использует int8.
Модель и её зависимости готовятся заранее, до переноса в закрытый контур.

```sh
docker compose -f compose.ingest.yml --profile stt up -d --build
docker compose -f compose.ingest.yml logs --tail 50 stt-worker
```

Worker требует существующий локальный каталог модели. HF_HUB_OFFLINE=1 запрещает автоматическое
скачивание с Hub во время работы. Если модели нет, worker завершится с понятной ошибкой,
а приёмник продолжит сохранять задания queued. Веса и качество распознавания RU/KZ на реальном
оборудовании этим изменением не проверены; размер модели подбирается по требуемому качеству и ресурсам.
Диаризация, имена говорящих и извлечение поручений в этом обработчике ещё не реализованы.

После аварийного перезапуска задания processing снова переходят в queued.
Обработка локального файла может повториться, но запись не создаётся повторно.
Межпроцессная блокировка допускает только один worker на volume.
Файлы и результаты сохраняются до удаления администратором; автоматической очистки пока нет.

## Связь с коннекторами совещаний

В [его конфигурации](../integrations/cisco-connector/.env.example) задайте:

```dotenv
APP_UPLOAD_URL=http://127.0.0.1:8020/api/recordings
APP_CONTRACT=gateway
APP_API_KEY=<SOCBRAIN_API_KEY из .env.ingest>
APP_ALLOW_HTTP=true
APP_IDEMPOTENT=true
```

Этот пример — для SIP-worker с host networking и приёмника на одном Linux-хосте.
Для разных серверов нужен внутренний HTTPS reverse proxy и его адрес в APP_UPLOAD_URL.
Не публикуйте ключи и реальные записи в Git.

После доставки коннектор хранит `result.id` из этого API. По нему запрашивается транскрипт.
Статические страницы frontend ещё не обращаются к этому API; пока результат доступен программно.

[Zoom-коннектор](../integrations/zoom-connector/README.md) использует тот же `APP_UPLOAD_URL` и ключ.
Он передаёт `source=zoom-cloud` для готовой облачной записи и `source=zoom-rtms` для WAV,
собранного в реальном времени.

## Проверка

```sh
python -m pip install -r requirements-ingest.txt pytest httpx
python -m pytest tests -q
```

Тесты проверяют целостность файла до публикации в очереди, повторную отправку, конфликт ключа,
ограничения размера, авторизацию и передачу в интерфейс локального STT с тестовым провайдером.
Они не загружают модель и не отправляют аудио во внешние сервисы.
