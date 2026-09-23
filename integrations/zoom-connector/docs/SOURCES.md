# Официальные источники и границы проверки

- [Server-to-Server OAuth](https://developers.zoom.us/docs/internal-apps/s2s-oauth/)
- [Zoom webhooks](https://developers.zoom.us/docs/api/webhooks/)
- [Meetings API](https://developers.zoom.us/docs/api/meetings/)
- [RTMS lifecycle](https://developers.zoom.us/docs/rtms/meetings/work-with-streams/)
- [RTMS media](https://developers.zoom.us/docs/rtms/meetings/media/)
- [Zoom RTMS Python SDK](https://github.com/zoom/rtms), версия 1.1.0, MIT
- [Python quickstart](https://github.com/zoom/rtms-quickstart-py)
- [RTMS samples](https://github.com/zoom/rtms-samples)

Код quickstart не скопирован. Коннектор использует опубликованный пакет `rtms==1.1.0` и его API;
версия закреплена в `requirements-rtms.txt`. Образ проверяет импорт SDK во время сборки.

Локально проверяются подписи webhook, URL validation, идемпотентная очередь, приоритет аудиофайла,
OAuth/API pagination, объединение календаря, безопасный redirect загрузки, доставка в Jinalys AI,
WAV 16 kHz и JSONL с именем участника. Без реквизитов Zoom невозможно подтвердить реальные scopes,
Cloud Recording download и RTMS handshake; они требуют приёмочного теста в аккаунте заказчика.
