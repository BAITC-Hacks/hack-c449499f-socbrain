# Конфигурация

Рабочий `.env` создаётся `python scripts/init_config.py` и никогда не публикуется.
Пароли с `$`, `#` и пробелами в Compose env-файле заключайте в одинарные кавычки,
например `CMS_PASSWORD='literal$secret'`. После изменений пересоздайте соответствующий сервис.

| Переменная | Назначение |
|---|---|
| GATEWAY_API_KEY | Случайный ключ клиента коннектора, минимум 32 символа |
| CMS_URL | HTTPS origin Call Bridge/Web Admin с фактическим портом |
| CMS_USERNAME / CMS_PASSWORD | Учётная запись REST API |
| CMS_CA_FILE | Корпоративный CA PEM; пусто = системные доверенные CA |
| CMS_SCHEDULER_URL | Отдельный HTTPS origin Scheduler |
| CMS_SCHEDULER_USERNAME / CMS_SCHEDULER_PASSWORD | Необязательный Basic Auth Scheduler/proxy |
| CMS_BOT_SIP_URI | Адрес внешнего готового SIP-клиента для ручного endpoint /bot |
| CONNECTOR_DATA_DIR | SQLite, WAV, результаты и heartbeat; в Docker /data |
| ASSISTANT_ENABLED | Включение автоматизации, по умолчанию false |
| PARTICIPANTS_NOTIFIED | true только если участники уведомлены о записи и обработке |
| ASSISTANT_SPACES | Разрешённые coSpace UUID через запятую; пустой список не разрешает запись |
| POLL_SECONDS | Период чтения календаря, по умолчанию 15 секунд, минимум 2 |
| SCHEDULE_LIMIT | Максимум записей календаря, по умолчанию 1000, максимум 10000 |
| SIP_ID_URI | SIP identity ассистента, например sip:assistant@company.local |
| SIP_DOMAIN | Домен для URI комнат, если CMS отдаёт только имя |
| SIP_TRANSPORT | udp, tcp или tls |
| SIP_PORT | Локальный SIP-порт, по умолчанию 5060 |
| SIP_BIND_ADDRESS | Локальный интерфейс, по умолчанию 0.0.0.0 |
| SIP_PUBLIC_ADDRESS | Адрес в сигнализации/SDP, доступный Cisco; при необходимости NAT |
| SIP_RTP_PORT | Начало диапазона RTP/RTCP, по умолчанию 40000 |
| SIP_SRTP | 0 — выключено, 1 — optional, 2 — mandatory; согласовать с Cisco |
| SIP_CA_FILE | CA для проверки SIP TLS |
| SIP_REGISTRAR | Необязательный registrar URI |
| SIP_PROXY | Необязательный outbound proxy URI, например sip:sbc.company.local;lr |
| SIP_REALM / SIP_USERNAME / SIP_PASSWORD | Digest credentials при необходимости |
| APP_UPLOAD_URL | Полный URL метода приёма файла в приложении |
| APP_CONTRACT | gateway или protocol-ai |
| APP_API_KEY | X-API-Key принимающего приложения, если нужен |
| APP_CA_FILE | CA для HTTPS принимающего приложения |
| APP_ALLOW_HTTP | Явное разрешение HTTP в изолированной сети; по умолчанию false |
| APP_IDEMPOTENT | true только если получатель гарантирует Idempotency-Key; SOCBrain receiver поддерживает |

В `.env.example` нет рабочих адресов. Параметры allowlist, уведомления и получателя проверяются
при старте включённого worker. Контейнер API может работать без worker.

Доступ к самим `.env` и volume должен быть только у администратора сервиса.
Volume хранит записи до явного удаления администратором; автоматической очистки нет.
