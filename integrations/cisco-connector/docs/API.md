# API коннектора

Все `/api/*` требуют `X-API-Key`. `/health`, `/docs`, `/openapi.json` открыты и не содержат секретов.

| Метод | Путь | Назначение |
|---|---|---|
| GET | /health | Проверка процесса, не связи с Cisco |
| GET | /api/integrations | Наличие конфигурации CMS/Scheduler/ассистента |
| GET | /api/cms/connection | Проверка CMS, версия, лицензии и первые 100 alarms |
| GET | /api/cms/schedule?hours=24 | Календарь Scheduler за интервал от текущего времени |
| GET | /api/cms/spaces | Комнаты coSpaces |
| GET | /api/cms/spaces/{id} | Конкретная комната |
| GET | /api/cms/alarms | Системные ошибки |
| GET | /api/cms/calls | Активные вызовы |
| GET | /api/cms/calls/{id} | Состояние вызова |
| GET | /api/cms/calls/{id}/participants | Участники |
| POST | /api/cms/calls/{id}/bot | Пригласить настроенный CMS_BOT_SIP_URI |
| PUT | /api/cms/calls/{id}/recording | Команда CMS Recorder |
| PUT | /api/cms/calls/{id}/streaming | Команда CMS Streamer |
| GET | /api/assistant/jobs?limit=100 | Последние задания и результат отправки |
| GET | /api/assistant/status | Heartbeat worker, ошибка календаря, текущее задание |

У списков CMS есть `offset=0&limit=50` (limit до 100). XML конвертируется в JSON:
атрибуты с `@`, дочерние элементы всегда массивы, например `data.calls.call[0]["@id"]`.
Расписание возвращается как исходный JSON Cisco. При достижении SCHEDULE_LIMIT результат
считается потенциально обрезанным и отклоняется; молчаливого пропуска встреч нет.

PowerShell, ключ задаётся только в текущем локальном окружении:

```powershell
$headers = @{ 'X-API-Key' = $env:GATEWAY_API_KEY }
Invoke-RestMethod http://127.0.0.1:8010/api/cms/schedule -Headers $headers
Invoke-RestMethod http://127.0.0.1:8010/api/assistant/jobs -Headers $headers
```

Команда Recorder/Streamer: JSON `{"enabled":true,"participants_notified":true}`.
Отключение: `{"enabled":false,"participants_notified":false}`.
Приглашение bot: `{"participants_notified":true}`.
HTTP 202 подтверждает приём команды, а не подключение или фактическую запись.
Операции не повторяются автоматически. Для записи отдельным SIP-worker эти команды не нужны.

Ошибки: 401 — ключ коннектора; 404 — ресурс не найден; 422 — неверные параметры;
429 — ограничение CMS; 502 — ошибка CMS/TLS/формата/прав; 503 — подключение не настроено;
504 — таймаут. Тела ошибок внешнего сервера клиенту не передаются.
