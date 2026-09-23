# Настройка Zoom

## Server-to-Server OAuth

В Zoom App Marketplace создайте внутреннее Server-to-Server OAuth приложение. Сохраните в `.env`
`ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` и Secret Token подписки webhook как
`ZOOM_WEBHOOK_SECRET`. Access token живёт один час; коннектор получает новый автоматически.

Добавьте только необходимые granular scopes. Точные подписи в Marketplace могут меняться; для
текущих API нужны разрешения, соответствующие:

- `cloud_recording:read:recording:admin` для события `recording.completed`;
- `cloud_recording:read:list_recording_files:admin` для скачивания облачной записи;
- `meeting:read:list_meetings:admin` для встреч организатора;
- `meeting:read:list_upcoming_meetings:admin` для ближайших приглашений;
- `meeting:update:participant_rtms_app_status:admin`, только если включён ручной RTMS start.

Включите Event Subscriptions и задайте публичный HTTPS URL:

```text
https://meetings.company.example/webhooks/zoom
```

Подпишитесь на используемые события:

- `recording.completed`;
- `meeting.started` — метаданные встречи и необязательный manual start;
- `meeting.rtms_started`;
- `meeting.rtms_stopped`.

Zoom выполняет `endpoint.url_validation`; коннектор возвращает HMAC-ответ автоматически.
Все рабочие события принимаются только с корректной `x-zm-signature` и timestamp не старше пяти минут.

## Cloud Recording

У организаторов должен быть тариф с Cloud Recording, а запись должна быть включена вручную или
автоматически. По умолчанию выбирается первый доступный файл в порядке `AUDIO_ONLY,M4A,MP4`.
Порядок меняется через `ZOOM_RECORDING_TYPES`. В очередь попадает один файл на occurrence, поэтому
галерея и active speaker не создают дубли одного протокола.

Webhook сохраняет задание и отвечает сразу. Worker получает новый OAuth token, скачивает файл по
HTTPS с ограничением `ZOOM_MAX_DOWNLOAD_BYTES` и передаёт его в Jinalys AI с `Idempotency-Key`.
OAuth заголовок удаляется перед переходом на стороннее object storage.

## RTMS

В Marketplace добавьте RTMS feature и разрешения на Audio и Transcript. В Zoom web portal включите
**Share realtime meeting content with apps** и добавьте приложение в список разрешённых.
RTMS использует платные credits и лимит одновременных потоков вашего Developer Pack.

Рекомендуется account/group/user auto-start: когда организатор начинает встречу, Zoom отправляет
`meeting.rtms_started`, и worker подключается к медиапотоку без участника-бота.

`ZOOM_RTMS_AUTO_START=true` включает REST-запрос после `meeting.started`, но Zoom применяет ограничения:
пользователь приложения должен быть явным приглашённым, уже находиться во встрече, а host или
alternative host должен присутствовать. Поэтому этот режим оставлен выключенным по умолчанию.

RTMS-worker запрашивает mixed L16 PCM, 16 kHz, mono. Он сохраняет:

- `{stream-id}.wav` — смешанное аудио;
- `{stream-id}.transcript.jsonl` — живые реплики с именами;
- `{stream-id}.events.jsonl` — active speaker и вход/выход участников.

После остановки WAV отправляется в Jinalys AI. Live-транскрипт доступен через API коннектора ещё во
время встречи. Файлы содержат данные совещаний и должны находиться на зашифрованном томе с политикой
срока хранения.
