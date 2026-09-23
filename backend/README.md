# Backend — распознавание речи (первый срез)

Первый кусок бэкенда: загрузили готовый аудиофайл совещания → получили
текст с таймкодами. Диаризация и извлечение поручений — следующие шаги
поверх этого.

## Провайдеры

Один интерфейс (`app/stt/base.py:STTProvider`), две реализации:

- **external** (`app/stt/external_openai.py`) — OpenAI Whisper API.
  Временно, для обкатки пайплайна. **Не соответствует ограничению ТЗ**
  (запрет на внешние облачные API) — держать это в голове.
- **local** (`app/stt/local_faster_whisper.py`) — self-hosted
  faster-whisper. Целевой провайдер для сдачи. Не проверялся на
  реальном железе, требует отдельной установки зависимостей.

Переключение — одной переменной в `.env`.

## Запуск (external / OpenAI)

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# вписать в .env: OPENAI_API_KEY=...

python -m app.transcribe "../Тех_задание/Совещание №1.mp3"
```

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
