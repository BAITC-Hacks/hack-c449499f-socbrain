# Источники и проверка

## Cisco

- [Cisco DevNet](https://developer.cisco.com/cisco-meeting-server/) — каталог SDK и примеров.
- [Canopy](https://github.com/ciscocms/canopy) — готовый Python SDK управления CMS.
- [auto-dial](https://github.com/ciscocms/auto-dial) — приглашение участников по событиям.
- [Postman Collection](https://github.com/ciscocms/cms-postman-collection) — примеры API-запросов.
- [CMS API Reference 3.13](https://www.cisco.com/c/dam/en/us/td/docs/conferencing/ciscoMeetingServer/Reference_Guides/Version-3-13/Cisco-Meeting-Server-API-Reference-Guide-3-13.pdf) — Call Bridge и Scheduler, раздел 15.
- [Events Guide 3.12+](https://www.cisco.com/c/dam/en/us/td/docs/conferencing/ciscoMeetingServer/Reference_Guides/Version-3-12/Cisco-Meeting-Server-Events-Guide-3-12.pdf) — имена и activeSpeaker.

Canopy/auto-dial использованы как исследованные альтернативы; их исходники в проект не копировались.
Коннектор реализует ограниченный набор документированных HTTP-запросов на HTTPX.

## SIP и зависимости

SIP-часть собирается из [официального PJSIP/PJPROJECT 2.16](https://github.com/pjsip/pjproject/tree/2.16).
Инструкция сборки: [PJSUA2 Python](https://docs.pjsip.org/en/2.16/pjsua2/building.html).
Образ содержит upstream COPYING в `/usr/share/doc/pjsip/COPYING`.
PJSIP использует собственные условия GPL/commercial licensing; они не заменяются условиями этого проекта.
Исходная версия и рецепт сборки доступны в Dockerfile; образ не публикуется этим репозиторием автоматически.
Для распространения производных бинарных образов нужно сохранить применимые условия upstream.

FastAPI, HTTPX, Uvicorn, defusedxml, python-multipart и tzdata устанавливаются по requirements.txt;
используются их собственные лицензии. Облачных SDK записи или ASR в зависимостях нет.

## Что проверяется

На 23.09.2026 локально пройдены 27 тестов коннектора и 5 тестов приёмника Jinalys AI,
сборка Docker-образов и SIP/RTP smoke test
с синтетическим тоном. Контроль RTP проверен на установленном PJSUA2 2.16.

- Unit/integration tests: TLS-конфигурация, авторизация API, XML, Scheduler JSON,
  часовые пояса, повторные экземпляры, отмены, конфликты, сбои и загрузка файлов.
- Docker build: сборка API и PJSUA2 worker.
- `tests/sip_smoke.py`: настоящий локальный SIP/RTP-вызов и WAV с тестовым тоном.

Эти проверки не подтверждают совместимость с конкретной сетью Cisco.
Версия CMS заказчика, Scheduler, SIP/TLS/SRTP, доступ к комнате и доставка в реальное приложение
должны быть проверены на тестовом совещании после заполнения конфигурации.
Автоматическое распознавание по именам и Events API пока описаны только как дальнейшее развитие.
