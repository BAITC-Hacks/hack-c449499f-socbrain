# Cisco CMS Connector

Отдельный backend для внутреннего **Cisco Meeting Server**, с Docker-образами API и SIP-ассистента.
Язык — Python 3.12; FastAPI/HTTPX для API, PJSIP/PJSUA2 для SIP/RTP и записи WAV.
Сервисы работают внутри организации, без облачных моделей и внешних сервисов записи.

## Возможности

- Проверка связи с CMS, чтение версии, лицензий, ошибок, комнат, вызовов и участников.
- Получение расписания из отдельного **CMS Scheduler API, CMS 3.3+**.
- Автоматическое подключение SIP-ассистента к разрешённым комнатам в назначенное время.
- Запись входящего аудио, завершение WAV и отправка файла в ваше приложение по HTTP API.
- Журнал заданий в SQLite; защита от повторного подключения после перезапуска.
- Ручные команды CMS Recorder/Streamer и приглашения существующего SIP-клиента.

**Текущие границы:** один ассистент обслуживает одну встречу одновременно. TMS/Exchange календарь
напрямую не подключён. SIP/PIN/лобби и маршрутизация должны допускать вход ассистента.
Распознавание выполняет принимающее приложение. Потоковая транскрибация и автоматическая подпись
реплик именами пока не реализованы — [исследование возможности](docs/LIVE_TRANSCRIPTION.md).

## Быстрый запуск API

Нужны Docker Engine с Compose и Python 3 для генерации конфигурации.

```powershell
git clone https://github.com/BAITC-Hacks/hack-c449499f-socbrain.git
cd hack-c449499f-socbrain/integrations/cisco-connector
python scripts/init_config.py
# Отредактируйте .env локально: CMS_URL, CMS_USERNAME, CMS_PASSWORD, CMS_CA_FILE.
docker compose up -d --build connector
```

Скрипт создаёт случайный `GATEWAY_API_KEY`, не выводит его и не перезаписывает существующий `.env`.
Без адреса CMS сервис запустится, но проверка соединения вернёт 503.
Адрес сервиса: http://127.0.0.1:8010. Спецификация: `/openapi.json`, Swagger UI: `/docs`.
Swagger UI загружает JS/CSS из CDN; в закрытом контуре используйте OpenAPI и curl/PowerShell.

```powershell
docker compose exec connector python -m meeting_gateway.check
docker compose ps
docker compose logs --tail 50 connector
```

Код возврата проверки: 0 — API и дополнительные проверки доступны; 1 — соединение не прошло;
2 — API доступен, но отдельные диагностические методы недоступны. Наличие лицензии не доказывает приём аудио.

## Запуск автоматического ассистента

Для SIP/RTP рекомендуется отдельный **Linux-хост в сети CMS/SBC**. Worker использует host networking;
подключение через Docker Desktop на Windows требует отдельной проверки сетевой конфигурации.

1. Заполните `CMS_SCHEDULER_URL` и проверьте `/api/cms/schedule`.
2. Укажите `ASSISTANT_SPACES` — UUID комнат, которые разрешено записывать.
3. Настройте `SIP_ID_URI`, `SIP_DOMAIN` и параметры маршрутизации по [инструкции Cisco](docs/CISCO_SETUP.md).
4. Настройте `APP_UPLOAD_URL` и контракт приёма по [инструкции интеграции](docs/APP_INTEGRATION.md).
5. После уведомления участников выставьте `PARTICIPANTS_NOTIFIED=true` и `ASSISTANT_ENABLED=true`.

```sh
docker compose --profile assistant up -d --build
docker compose logs --tail 50 assistant
```

Сборка образа ассистента компилирует PJSIP 2.16 из официальных исходников и занимает несколько минут.
Ассистент отображается как `[REC] Protocol AI assistant`. Он не воспроизводит голосовое уведомление.
Не запускайте несколько workers на один volume: блокировка предотвращает повторную обработку.

Для локального запуска только API без Docker:

```sh
python -m venv .venv
# Активируйте .venv и установите переменные из .env в окружение процесса.
python -m pip install -r requirements.txt
# CONNECTOR_DATA_DIR должен указывать на доступную для записи папку.
python -m uvicorn meeting_gateway.api:app --host 127.0.0.1 --port 8010
```

При запуске uvicorn `.env` автоматически не читается. Docker Compose читает его самостоятельно.

## Документация

- [Подготовка Cisco, Scheduler, SIP и сети](docs/CISCO_SETUP.md)
- [Тестовый стенд dCloud и приёмочная проверка](docs/TEST_LAB.md)
- [Переменные окружения](docs/CONFIGURATION.md)
- [API и примеры запросов](docs/API.md)
- [Автоматизация, остановка, ошибки и восстановление](docs/AUTOMATION.md)
- [Передача записи в приложение](docs/APP_INTEGRATION.md)
- [Распознавание в реальном времени и имена участников](docs/LIVE_TRANSCRIPTION.md)
- [Источники, зависимости и ограничения проверки](docs/SOURCES.md)

## Проверка разработки

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
docker compose --profile assistant build
docker compose run --rm -v "$PWD/tests:/tests:ro" assistant python /tests/sip_smoke.py
```

Последняя проверка создаёт локальную SIP-пару и передаёт тестовый тон через RTP в WAV;
не подключается к Cisco и не записывает людей. Для реального CMS нужен отдельный приёмочный тест.

Код и конфигурационные примеры можно переносить отдельно от Protocol AI. Записи, ключи, `.env`,
сертификаты и SQLite не входят в Git. Контейнеры запускаются непривилегированным пользователем.
Для другого сервера подключите внутренний HTTPS reverse proxy; по умолчанию API доступен только на localhost.

В этом репозитории также добавлен [HTTP-приёмник Jinalys AI и локальный STT-worker](../../backend/INGEST.md).
Для него используйте `APP_CONTRACT=gateway` и `APP_IDEMPOTENT=true`.
