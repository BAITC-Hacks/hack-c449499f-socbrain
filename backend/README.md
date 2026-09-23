# Backend

Два процесса над общей SQLite-базой в volume `/data`:

- **api** (`app/api/main.py`) — REST API и раздача `frontend/`: загрузка записи, совещания, поручения,
  экспорт протокола, напоминания.
- **worker** (`app/worker.py`) — берёт записи из очереди и прогоняет конвейер (`app/pipeline/runner.py`).

## Конвейер

| Шаг | Модуль | Что делает |
|---|---|---|
| Конвертация | `pipeline/audio.py` | ffmpeg → WAV 16 кГц моно |
| Распознавание | `stt/` | `STTProvider`: `local` (faster-whisper) или `external` (OpenAI Whisper). Отдаёт слова с таймкодами. Подсказка — тема, имена участников из карточки, `WHISPER_PROMPT` |
| Диаризация | `pipeline/diarization.py` | sherpa-onnx; «голоса» с парой секунд речи сводятся к соседям |
| Склейка | `pipeline/align.py` | каждое слово — говорящему с наибольшим перекрытием; реплики; язык реплики |
| Язык | `pipeline/lang.py` | ru / kk / mixed по казахским буквам и служебным словам |
| Анализ | `pipeline/extract.py` | LLM: кто есть кто, поручения (что/кому/срок дословно/цитата/срочность/направление), саммари. Без LLM — шаблон «…, ответственный X, срок Y» |
| Сроки | `pipeline/dates.py` | «до пятницы», «к пятнадцатому октября», «за две недели», «жұмаға дейін» → дата относительно даты совещания |
| Экспорт | `export/` | DOCX (python-docx), PDF (reportlab, шрифт DejaVu — казахские буквы) |

«Переанализировать» (`POST /api/meetings/{id}/reprocess?mode=llm`) повторяет только анализ по готовой
стенограмме — секунды вместо повторного распознавания.

## LLM

Один клиент (`pipeline/llm.py`) для любого OpenAI-совместимого `/chat/completions`, провайдер — `LLM_PROVIDER`:

| Провайдер | Где | Для чего |
|---|---|---|
| `ollama`, `vllm` | в контуре | сдача по ТЗ |
| `openai`, `nvidia` | облако | разработка на синтетических записях |
| `none` | — | только шаблоны |

Ответ запрашивается по JSON-схеме (`response_format: json_schema`); если провайдер схему не поддерживает —
откат на JSON по инструкции.

## Запуск без Docker (только распознавание, как раньше)

```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt            # + requirements-local.txt для STT_PROVIDER=local
copy .env.example .env
python -m app.transcribe "../Тех_задание/Совещание №1.mp3"
```

## Проверка качества

`python -m app.evaluate <id совещания> <эталон.docx>` сверяет найденные поручения с таблицей эталонного
протокола из [`../Тех_задание/`](../Тех_задание/): полнота, точность, верность ответственного и срока.
