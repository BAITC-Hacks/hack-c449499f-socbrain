# Backend — распознавание речи (первый срез)

Для автоматического приёма записей Cisco добавлены отдельный HTTP-приёмник и локальный
STT-worker в Docker: [инструкция запуска и API](INGEST.md).
Этот сценарий использует только локальное распознавание. Описанная ниже CLI сохранена.

Первый кусок бэкенда: загрузили готовый аудиофайл совещания → получили
текст с таймкодами. Диаризация и извлечение поручений — следующие шаги
поверх этого.

## Провайдеры

Один интерфейс (`app/stt/base.py:STTProvider`), три реализации:

- **external_openai** (`app/stt/external_openai.py`) — OpenAI Whisper API.
- **external_nvidia** (`app/stt/external_nvidia_riva.py`) — NVIDIA Riva
  (whisper-large-v3 через NVCF, `grpc.nvcf.nvidia.com`). Требует ffmpeg
  в PATH — Riva принимает только mono WAV/OPUS/FLAC, конвертация из
  исходного формата идёт перед отправкой.
- **local** (`app/stt/local_faster_whisper.py`) — self-hosted
  faster-whisper. Целевой провайдер для сдачи. Не проверялся на
  реальном железе, требует отдельной установки зависимостей.

**И external_openai, и external_nvidia — временные**, для обкатки
пайплайна на этапе разработки: оба вызывают чужой облачный API, а ТЗ
это прямо запрещает ("передача аудио/текста во внешние облачные API
запрещена"). К моменту сдачи `STT_PROVIDER` должен быть `local`.

Переключение — одной переменной в `.env`.

## Запуск (external_nvidia — сейчас основной путь для тестов)

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# вписать в .env: NVIDIA_API_KEY=...  (STT_PROVIDER уже = external_nvidia)

python -m app.transcribe "../Тех_задание/Совещание №1.mp3"
```

## Запуск (external_openai)

Поставить в `.env`: `STT_PROVIDER=external_openai`, вписать `OPENAI_API_KEY`.
Дальше та же команда `python -m app.transcribe ...`.

## Переход на local (позже)

```bash
pip install -r requirements-local.txt
```

В `.env` поставить `STT_PROVIDER=local`. Модель (`large-v3` по умолчанию,
см. `local_faster_whisper.py`) скачается при первом запуске — несколько ГБ.

## Проверка качества

В [`../Тех_задание/`](../Тех_задание/) уже лежат два тестовых аудио и
эталонные протоколы к ним (`Протокол_совещания№1.docx`,
`Протокол_совещания№2.docx`) — можно сверять вывод `transcribe.py`
с реальным текстом совещания.

## API: логин, журнал доступа, подключения ИИ-моделей

Второй срез — по образцу того, что уже реализовано в `Teams_analyz`
(`AiConnectionService` — подключения в БД, проверка, default) и
`Analyz-zapis` (`auth.go` — bcrypt, блокировка после подбора, лог
каждой попытки входа). SQLite-файл (`data/socbrain.db`, не в git).

Завести первого пользователя и поднять сервер:

```bash
python seed.py artem "Артём Е." <свой пароль>
uvicorn app.main:app --reload --port 8000
```

Эндпоинты:

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/login` | `{login, password}` → токен сессии; каждая попытка (успех/отказ) пишется в журнал |
| POST | `/api/logout` | завершает сессию |
| GET | `/api/access-log` | журнал доступа — требует `Authorization: Bearer <токен>` |
| GET | `/api/ai-connections` | список подключённых ИИ-моделей (без секретов) |
| POST | `/api/ai-connections` | добавить модель: `{name, type, base_url?, api_key?, model?}` — `type` один из `external_openai`/`external_nvidia`/`local_faster_whisper` |
| POST | `/api/ai-connections/{id}/test` | собрать провайдера с текущими настройками и проверить, что это не падает |
| POST | `/api/ai-connections/{id}/default` | сделать активной именно эту — её и возьмёт `get_default_provider()` |

Как только модель добавлена через `/api/ai-connections` и помечена
default — её сразу использует `app.ai_connections.get_default_provider()`,
без правки `.env` и перезапуска процесса. Если ни одного подключения
не заведено — фолбэк на переменные окружения, как раньше.

**Не сделано в этом срезе:** реальная сетевая проверка при "Тест"
(сейчас — только что провайдер собирается без ошибки, не что ключ
валиден и служба отвечает — как `ListModelsAsync` у Teams_analyz);
подключение фронта (`settings.html` пока статика, к этим эндпоинтам
не обращается).
