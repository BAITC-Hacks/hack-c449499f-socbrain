# Подготовка Cisco

## CMS REST API

Администратор определяет адрес Call Bridge Web Admin/API и выдаёт отдельного API-пользователя.
В `.env` указываются `CMS_URL=https://cms.company.local:445`, логин и пароль.
Порт 445 — пример: используйте фактический порт Web Admin, часто 443.
В адресе не должно быть `/api/v1`. Для корпоративного центра сертификации задайте `CMS_CA_FILE`.
Разрешите исходящий HTTPS с хоста коннектора к этому адресу.

Запрос `/api/cms/connection` читает версию и диагностику. Лицензии экземпляра и кластера
показываются отдельно: в CMS 3.x это разные источники данных.

## Календарь CMS Scheduler

CMS с версии 3.3 может иметь включённый Scheduler. У него **отдельный HTTPS listener**,
например `https://cms.company.local:8443`. Это не путь обычного Web Admin API.
В справочнике Cisco описаны команды настройки `scheduler https listen` и `scheduler https certs`.
Настройку существующей системы выполняет её администратор по документации вашей версии.

Укажите `CMS_SCHEDULER_URL`. Если развёртывание/proxy требует Basic Auth, укажите отдельные
`CMS_SCHEDULER_USERNAME` и `CMS_SCHEDULER_PASSWORD`; credentials Call Bridge не подставляются
в Scheduler автоматически. TLS проверяется тем же CA, что и CMS API.

Коннектор читает `/api/v1/scheduler/meetings` с `fromTime`, `untilTime`, `maxMeetings`.
CMS возвращает экземпляры повторяющихся встреч, coSpace и часовой пояс.
Встречи, созданные только в Cisco TMS/Exchange, могут отсутствовать в CMS Scheduler.
Для такого развёртывания потребуется отдельный адаптер TMS, которого в этой версии нет.

## SIP-ассистент

Worker сам звонит на SIP URI комнаты из `/coSpaces/{id}`. Если URI содержит только имя комнаты,
к нему добавляется `SIP_DOMAIN`. Он участвует как обычный аудиотерминал: CMS Recorder/Streamer
для этой схемы не используется. Применяются обычные правила допуска и ёмкости CMS.

Администратор задаёт SIP identity, маршрут через CMS/SBC/CUCM, при необходимости registrar,
proxy и digest credentials. PIN и интерактивное прохождение лобби не автоматизированы.
Если без них нельзя войти, настройте согласованный маршрут/доступ для ассистента.

На Linux worker работает в host network. Разрешите нужные направления между ним и CMS/SBC:

- HTTPS к CMS и Scheduler;
- SIP: фактический порт `SIP_PORT`, по умолчанию 5060; UDP/TCP либо TLS согласно конфигурации;
- RTP/RTCP UDP: диапазон от `SIP_RTP_PORT`, по умолчанию 40000–40020;
- HTTP(S) к приложению для передачи записи.

`SIP_PUBLIC_ADDRESS` нужен, когда локальный адрес отличается от адреса, доступного CMS.
NAT/firewall и опубликованные SDP-адреса проверяются отдельно. TLS использует `SIP_CA_FILE`;
`SIP_SRTP=2` требует SRTP, `1` допускает его при согласовании. Не меняйте политику шифрования
Cisco ради теста: подберите параметры клиента под вашу систему.

Источник: [CMS API Guide 3.13](https://www.cisco.com/c/dam/en/us/td/docs/conferencing/ciscoMeetingServer/Reference_Guides/Version-3-13/Cisco-Meeting-Server-API-Reference-Guide-3-13.pdf),
[настройка Scheduler](https://www.cisco.com/c/en/us/support/docs/conferencing/meeting-server-1000/217367-configuring-cisco-meeting-server-schedul.html).
