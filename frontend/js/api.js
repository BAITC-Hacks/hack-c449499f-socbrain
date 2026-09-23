// SOCBrain — связь страниц с бэкендом (backend/app/api/main.py).
// Разметка и стили — из каркаса фронтенда; здесь только данные.
// Страница выбирается по <body data-page="...">.

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const LANG = { ru: "рус", kk: "қаз", mixed: "смеш", "": "—" };
const STAGES = { start: "подготовка", convert: "конвертация аудио", asr: "распознавание речи",
                 diarization: "диаризация", llm: "анализ стенограммы", llm_only: "в очереди на анализ" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const tc = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const qs = (name) => new URLSearchParams(location.search).get(name) || "";

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${y !== new Date().getFullYear() ? " " + y : ""}`;
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.status === 204 ? null : r.json();
}

function langTag(code) {
  return code === "mixed" || code === "kk" ? `<span class="tag warn">${LANG[code]}</span>` : LANG[code ?? ""] ?? esc(code);
}

function statusTag(m) {
  if (m.status === "done") return '<span class="tag ok">готово</span>';
  if (m.status === "error") return '<span class="tag bad">сбой</span>';
  const stage = STAGES[m.stage] ? ` · ${STAGES[m.stage]}` : "";
  return `<span class="tag">${m.status === "queued" ? "в очереди" : "обрабатывается"}${stage}</span>`;
}

// Статус поручения так, как его рисовал каркас: «просрочено», «срок завтра», «в работе», «выполнено».
function taskTag(t) {
  if (t.state === "done") return '<span class="tag ok">выполнено</span>';
  if (t.state === "overdue") return '<span class="tag bad">просрочено</span>';
  if (t.due_date) {
    const days = Math.round((new Date(t.due_date) - new Date(new Date().toISOString().slice(0, 10))) / 864e5);
    if (days === 0) return '<span class="tag warn">срок сегодня</span>';
    if (days === 1) return '<span class="tag warn">срок завтра</span>';
    if (days <= 3) return `<span class="tag warn">через ${days} дн.</span>`;
  }
  return '<span class="tag">в работе</span>';
}

function dueCell(t) {
  const said = t.deadline_text && t.deadline_text !== t.due_date
    ? `<div class="muted" style="font-size:12px">«${esc(t.deadline_text)}»</div>` : "";
  if (t.due_date) return fmtDate(t.due_date) + said;
  return `<span class="tag warn" title="Срок не назван — проверить вручную">не указан</span>${said}`;
}

function summaryOf(m) {
  try { return JSON.parse(m.summary || "{}"); } catch { return { overview: m.summary || "" }; }
}

// Предупреждение, если текст/аудио уходят во внешний API (ТЗ требует закрытого контура).
async function privacyBanner() {
  document.getElementById("privacy-banner")?.remove();
  const c = await api("/api/config").catch(() => null);
  if (!c || !(c.llm_external || c.stt_external)) return;
  const what = [c.stt_external && "аудио (распознавание)", c.llm_external && `текст стенограммы (LLM: ${c.llm_provider})`]
    .filter(Boolean).join(" и ");
  document.querySelector("main").insertAdjacentHTML("afterbegin",
    `<div class="note warn" id="privacy-banner">Режим разработки: ${what} отправляется во внешний API. ` +
    "Для закрытого контура переключите STT_PROVIDER=local и LLM_PROVIDER=ollama/vllm.</div>");
}

// ---------------------------------------------------------------- дашборд
async function pageDashboard() {
  const [s, meetings, tasks] = await Promise.all([api("/api/stats"), api("/api/meetings"), api("/api/tasks")]);
  const active = s.tasks.in_progress + s.tasks.overdue;
  document.getElementById("cards").innerHTML = `
    <div class="card"><div class="n">${s.meetings_month}</div><div class="l">совещаний за месяц</div></div>
    <div class="card"><div class="n">${active}</div><div class="l"><a href="tasks.html">активных поручений</a></div></div>
    <div class="card danger"><div class="n">${s.tasks.overdue}</div><div class="l"><a href="tasks.html?status=overdue">просрочено</a></div></div>
    <div class="card ok"><div class="n">${s.tasks.done}</div><div class="l"><a href="tasks.html?status=done">выполнено</a></div></div>`;
  document.getElementById("langs").innerHTML = [["ru", "русский"], ["kk", "казахский"], ["mixed", "смешанный (шала-қаз)"]]
    .map(([k, l]) => `<div class="card"><div class="n">${s.languages[k] || 0}</div><div class="l"><a href="meetings.html?lang=${k}">${l}</a></div></div>`).join("");
  document.getElementById("recent").innerHTML = meetingsTable(meetings.slice(0, 5), false);
  const soon = tasks.filter((t) => t.state !== "done").slice(0, 6);
  document.getElementById("soon").innerHTML = soon.length ? tasksTable(soon, false) : '<p class="sub">Открытых поручений нет.</p>';
}

// ---------------------------------------------------------------- совещания
function meetingsTable(items, withGist) {
  if (!items.length) return '<p class="sub">Совещаний пока нет — загрузите запись.</p>';
  return `<div class="scroll"><table>
    <tr><th>Дата</th><th>Тема</th><th>Участников</th><th>Язык</th><th>Статус</th><th class="right">Поручений</th>${withGist ? '<th class="wrap">Суть</th>' : ""}</tr>
    ${items.map((m) => `<tr>
      <td><a href="meeting.html?id=${m.id}">${fmtDate(m.meeting_date)}</a></td>
      <td class="wrap"><a href="meeting.html?id=${m.id}">${esc(m.title)}</a></td>
      <td>${m.status === "done" ? m.speaker_count : ""}</td>
      <td>${m.status === "done" ? langTag(m.language) : ""}</td>
      <td>${statusTag(m)}</td>
      <td class="right">${m.status === "done" ? m.task_count : '<span class="muted">—</span>'}</td>
      ${withGist ? (m.status === "done"
        ? `<td class="gist muted"><span class="clip">${esc(summaryOf(m).overview)}</span><span class="more"></span></td>`
        : `<td class="wrap muted">${m.status === "error" ? esc(m.error || "") : "расшифровка ещё не готова"}</td>`) : ""}
    </tr>`).join("")}</table></div>`;
}

async function pageMeetings() {
  const form = document.getElementById("filters");
  for (const el of form.elements) if (el.name && qs(el.name)) el.value = qs(el.name);

  const upload = document.getElementById("upload");
  upload.meeting_date.value = new Date().toISOString().slice(0, 10);
  upload.onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById("upload-msg");
    const btn = upload.querySelector("button");
    btn.disabled = true; msg.textContent = "Загрузка файла…";
    try {
      const { id } = await api("/api/meetings", { method: "POST", body: new FormData(upload) });
      location.href = `meeting.html?id=${id}`;
    } catch (err) { msg.textContent = err.message; btn.disabled = false; }
  };

  const render = async () => {
    const all = await api("/api/meetings");
    const f = Object.fromEntries(new FormData(form));
    const text = (m) => `${m.title} ${m.participants || ""} ${m.summary || ""}`.toLowerCase();
    const shown = all.filter((m) =>
      (!f.from || m.meeting_date >= f.from) && (!f.to || m.meeting_date <= f.to) &&
      (!f.lang || m.language === f.lang) && (!f.status || m.status === f.status ||
        (f.status === "processing" && m.status === "queued")) &&
      (!f.who || text(m).includes(f.who.toLowerCase())) && (!f.q || text(m).includes(f.q.toLowerCase())));
    document.getElementById("found").textContent = `Найдено: ${shown.length} · всего в базе: ${all.length}`;
    document.getElementById("list").innerHTML = meetingsTable(shown, true);
    return all.some((m) => m.status === "queued" || m.status === "processing");
  };
  const loop = async () => { if (await render()) setTimeout(loop, 5000); };
  loop();
  document.addEventListener("click", (e) => { const c = e.target.closest("td.gist"); if (c) c.classList.toggle("open"); });
}

// ---------------------------------------------------------------- одно совещание
async function pageMeeting() {
  const id = qs("id");
  const root = document.getElementById("meeting");
  if (!id) { root.innerHTML = '<p class="sub">Не указано совещание. <a href="meetings.html">Ко всем совещаниям</a></p>'; return; }
  const m = await api(`/api/meetings/${id}`);
  document.title = `Совещание · ${m.title} · SOCBrain`;

  if (m.status !== "done") {
    root.innerHTML = `<h1>${esc(m.title)}</h1>
      <p class="sub">${fmtDate(m.meeting_date)} · ${statusTag(m)}</p>
      ${m.error ? `<div class="note bad">${esc(m.error)}</div>` : '<p class="sub">Страница обновится автоматически.</p>'}
      <div class="toolbar"><button class="ghost" onclick="reprocess('${id}','full')">Обработать заново</button></div>`;
    if (m.status !== "error") setTimeout(pageMeeting, 5000);
    return;
  }

  const names = Object.fromEntries(m.speakers.map((s) => [s.label, s]));
  const talk = {};
  m.segments.forEach((s) => { talk[s.speaker] = (talk[s.speaker] || 0) + s.end - s.start; });
  const issuers = {};
  m.tasks.forEach((t) => { if (t.issuer_speaker) issuers[t.issuer_speaker] = (issuers[t.issuer_speaker] || 0) + 1; });
  // Председатель — тот, кто раздаёт поручения; если LLM не отметила — кто говорил дольше всех.
  const chair = Object.keys(issuers).sort((a, b) => issuers[b] - issuers[a])[0]
    || Object.keys(talk).sort((a, b) => talk[b] - talk[a])[0];
  const who = (label) => names[label]?.name || label;
  const summary = summaryOf(m);
  const langs = m.segments.reduce((acc, s) => { if (s.lang) acc[s.lang] = (acc[s.lang] || 0) + 1; return acc; }, {});

  root.innerHTML = `
  <p class="sub"><a href="meetings.html">← ко всем совещаниям</a></p>
  <h1>${esc(m.title)}</h1>
  <p class="sub">${fmtDate(m.meeting_date)} · ${tc(m.duration || 0)} · ${statusTag(m)} · язык: ${langTag(m.language)}</p>

  <div class="toolbar">
    <a class="btn" href="/api/meetings/${id}/export.pdf">Экспорт в PDF</a>
    <a class="btn ghost" href="/api/meetings/${id}/export.docx">Экспорт в DOCX</a>
    <button class="ghost" onclick="reprocess('${id}','llm')" title="Повторный анализ готовой стенограммы — секунды, без распознавания">Переанализировать</button>
    <button class="ghost" onclick="reprocess('${id}','full')">Обработать заново</button>
  </div>

  <div class="cards">
    <div class="card"><div class="n" style="font-size:17px">${m.speakers.length}</div><div class="l">говорящих</div></div>
    <div class="card"><div class="n" style="font-size:17px">${(summary.topics || []).length || "—"}</div><div class="l">темы в повестке</div></div>
    <div class="card"><div class="n" style="font-size:17px">${m.tasks.length}</div><div class="l">выделено поручений</div></div>
    <div class="card"><div class="n" style="font-size:17px">${Object.entries(langs).map(([k, n]) => `${LANG[k] || k} ${n}`).join(" · ") || "—"}</div><div class="l">реплик по языкам</div></div>
  </div>

  <h2>Саммари</h2>
  ${m.llm_used ? "" : '<div class="note warn">LLM не подключена: саммари нет, поручения выделены по шаблонам — только явные формулировки.</div>'}
  ${summary.overview ? `<div class="note">${esc(summary.overview)}</div>` : ""}
  ${(summary.topics || []).map((t) => `<div class="note"><b>${esc(t.title)}.</b> ${(t.points || []).map(esc).join(" ")}</div>`).join("")}
  ${(summary.decisions || []).length ? `<div class="note ok"><b>Решения.</b> ${summary.decisions.map(esc).join(" ")}</div>` : ""}

  <h2>Поручения</h2>
  <p class="sub">Проверьте цитату, ответственного и срок: срок, который не прозвучал, не угадывается, а помечается «не указан».</p>
  ${m.tasks.length ? tasksTable(m.tasks, false, true) : '<p class="sub">Поручений не найдено.</p>'}

  <h2>Участники</h2>
  <p class="sub">Метки получены диаризацией, имена — из контекста речи и карточки совещания. Исправление сразу меняет стенограмму и протокол.</p>
  <div class="scroll"><table>
    <tr><th>Метка</th><th>Имя</th><th>Должность</th><th class="right">Речь</th><th></th></tr>
    ${m.speakers.map((s) => `<tr>
      <td>${s.label === chair ? "<b>председатель</b><br>" : ""}<span class="muted">${s.label}</span></td>
      <td><input type="text" id="n-${s.label}" value="${esc(s.name)}"></td>
      <td><input type="text" id="r-${s.label}" value="${esc(s.role)}"></td>
      <td class="right">${tc(talk[s.label] || 0)}</td>
      <td><button class="ghost" onclick="saveSpeaker('${id}','${s.label}')">Сохранить</button></td></tr>`).join("")}
  </table></div>

  <h2>Карточка совещания</h2>
  <p class="sub">Участники по строке: «Имя Отчество — должность». Подсказка для распознавания и анализа; после правки нажмите «Переанализировать».</p>
  <textarea id="participants" rows="4">${esc(m.participants || "")}</textarea>
  <div class="toolbar" style="margin-top:8px"><button class="ghost" onclick="saveParticipants('${id}')">Сохранить участников</button></div>

  <h2>Совещание</h2>
  <p class="sub">Реплики привязаны к говорящему диаризацией; председатель выделен — удобно проверить, кто раздавал поручения.</p>
  <div class="dialog">
    ${m.segments.map((s) => `<div class="line ${s.speaker === chair ? "chair" : "member"}">
      <span class="who">${esc(who(s.speaker))}<br><span class="muted">${tc(s.start)}${names[s.speaker]?.role ? " · " + esc(names[s.speaker].role) : ""}${s.lang === "kk" || s.lang === "mixed" ? " · " + LANG[s.lang] : ""}</span></span>
      <span class="say">${esc(s.text)}</span></div>`).join("")}
  </div>

  <h2>Служебное</h2>
  <div class="scroll"><table>
    <tr><td>Идентификатор записи</td><td><code>${m.id}</code></td></tr>
    <tr><td>Загружено</td><td>${esc(m.created_at)} · обработано ${esc(m.finished_at || "")}</td></tr>
    <tr><td>Анализ стенограммы</td><td>${m.llm_used ? "LLM" : "шаблоны (LLM не подключена)"}</td></tr>
    <tr><td>Согласие участников на запись</td><td>${m.consent ? "подтверждено при загрузке" : "не подтверждено"}</td></tr>
  </table></div>`;
}

async function reprocess(id, mode) {
  await api(`/api/meetings/${id}/reprocess?mode=${mode}`, { method: "POST" });
  pageMeeting();
}
async function saveSpeaker(id, label) {
  await api(`/api/meetings/${id}/speakers/${label}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: document.getElementById(`n-${label}`).value, role: document.getElementById(`r-${label}`).value }),
  });
  pageMeeting();
}
async function saveParticipants(id) {
  await api(`/api/meetings/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ participants: document.getElementById("participants").value }),
  });
  pageMeeting();
}

// ---------------------------------------------------------------- поручения
function tasksTable(tasks, withMeeting, editable = true) {
  return `<div class="scroll"><table>
    <tr><th class="wrap">Поручение</th><th>Ответственный</th><th>Срок</th><th>Статус</th>${withMeeting ? '<th class="wrap">Совещание</th>' : ""}</tr>
    ${tasks.map((t) => `<tr>
      <td class="wrap">${esc(t.description)}
        ${t.quote ? `<div class="muted" style="font-size:12px">«${esc(t.quote)}»</div>` : ""}
        ${t.priority === "high" ? '<span class="tag bad">срочно</span> ' : ""}${t.category ? `<span class="tag">${esc(t.category)}</span>` : ""}</td>
      <td>${esc(t.assignee || "—")}${t.assignee_speaker ? "" : t.assignee ? '<div class="muted" style="font-size:12px">не участник</div>' : ""}</td>
      <td>${dueCell(t)}</td>
      <td>${taskTag(t)}${editable ? `<br><label class="muted" style="font-size:12px"><input type="checkbox" ${t.status === "done" ? "checked" : ""}
        onchange="toggleTask(${t.id}, this.checked)"> выполнено</label>` : ""}</td>
      ${withMeeting ? `<td class="wrap"><a href="meeting.html?id=${t.meeting_id}">${esc(t.meeting_title)}</a><div class="muted" style="font-size:12px">${fmtDate(t.meeting_date)}</div></td>` : ""}
    </tr>`).join("")}</table></div>`;
}

async function toggleTask(id, done) {
  await api(`/api/tasks/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: done ? "done" : "in_progress" }) });
  PAGES[document.body.dataset.page]();
}

async function pageTasks() {
  const form = document.getElementById("filters");
  for (const el of form.elements) if (el.name && qs(el.name)) el.value = qs(el.name);
  const tasks = await api("/api/tasks");
  const count = (s) => tasks.filter((t) => t.state === s).length;
  document.getElementById("cards").innerHTML = `
    <div class="card"><div class="n">${count("in_progress")}</div><div class="l"><a href="tasks.html?status=in_progress">в работе</a></div></div>
    <div class="card danger"><div class="n">${count("overdue")}</div><div class="l"><a href="tasks.html?status=overdue">просрочено</a></div></div>
    <div class="card ok"><div class="n">${count("done")}</div><div class="l"><a href="tasks.html?status=done">выполнено</a></div></div>`;
  const f = Object.fromEntries(new FormData(form));
  const shown = tasks.filter((t) => (!f.status || t.state === f.status) &&
    (!f.who || (t.assignee || "").toLowerCase().includes(f.who.toLowerCase())) &&
    (!f.meeting || (t.meeting_title || "").toLowerCase().includes(f.meeting.toLowerCase())));
  document.getElementById("list").innerHTML = shown.length ? tasksTable(shown, true) : '<p class="sub">Поручений не найдено.</p>';
}

// ---------------------------------------------------------------- настройки
const placeTag = (external) => external ? '<span class="tag bad">внешняя</span>' : '<span class="tag ok">локальная</span>';
const SOURCE = { "интерфейс": "задано здесь", ".env": "из backend/.env", "по умолчанию": "по умолчанию" };

// Поля форм по разделам (config.SECTIONS на бэкенде). widget: seg | switch | text | number | textarea | select | header
const FORMS = {
  appearance: [
    { name: "theme", label: "Тема", hint: "«Как в системе» следует настройке устройства", widget: "seg",
      options: [["system", "Как в системе"], ["light", "Светлая"], ["dark", "Тёмная"]] },
    { name: "density", label: "Плотность таблиц", hint: "Плотная умещает на экран примерно на треть больше строк", widget: "seg",
      options: [["normal", "Обычная"], ["compact", "Плотная"]] },
    { name: "font_scale", label: "Размер текста", widget: "seg", options: [["100", "100%"], ["115", "115%"], ["130", "130%"]] },
    { name: "high_contrast", label: "Повышенный контраст", hint: "Границы и подписи темнее — при слабом зрении и ярком свете", widget: "switch" },
    { name: "reduce_motion", label: "Меньше движения", hint: "Без анимаций и переходов", widget: "switch" },
    { name: "org_name", label: "Организация", hint: "Печатается в шапке протокола (PDF/DOCX)", widget: "text", placeholder: "АО «Самрук-Қазына Ондеу»" },
  ],
  mail: [
    { name: "host", label: "Адрес сервера", hint: "SMTP, исходящая почта", widget: "text", placeholder: "smtp.company.kz" },
    { name: "port", label: "Порт", hint: "587 — STARTTLS, 465 — SSL", widget: "number" },
    { name: "security", label: "Шифрование", hint: "Без шифрования логин и пароль уходят открытым текстом", widget: "seg",
      options: [["starttls", "STARTTLS"], ["ssl", "SSL/TLS"], ["none", "нет"]] },
    { name: "username", label: "Логин", hint: "Пароль — SMTP_PASSWORD в backend/.env", widget: "text" },
    { name: "sender", label: "Адрес отправителя", hint: "Домен должен быть разрешён на сервере, иначе письма уйдут в спам", widget: "text", placeholder: "protocol@company.kz" },
    { name: "reminders_enabled", label: "Напоминания по почте", hint: "Рассылка ответственным при приближении срока — включится вместе с адресами участников", widget: "switch" },
  ],
  llm: [
    { name: "provider", label: "Провайдер", widget: "select", options: [] /* заполняется из /api/llm/providers */ },
    { name: "model", label: "Модель", hint: "Пусто — модель шаблона провайдера", widget: "text" },
    { name: "base_url", label: "Адрес", hint: "Пусто — адрес шаблона. Свой сервер в контуре (NIM, vLLM): http://<сервер>:8000/v1", widget: "text" },
    { name: "timeout", label: "Таймаут, с", widget: "number" },
  ],
  stt: [
    { name: "provider", label: "Где распознавать", hint: "Внешний — аудио уходит в OpenAI; по ТЗ запрещено", widget: "seg",
      options: [["local", "Локально (faster-whisper)"], ["external", "OpenAI Whisper API"]] },
    { name: "language", label: "Язык", hint: "Авто — язык по фрагментам: нужен для шала-казахской речи", widget: "seg",
      options: [["", "Авто"], ["ru", "Русский"], ["kk", "Казахский"]] },
    { name: "prompt", label: "Словарь-подсказка", hint: "Названия организаций, объектов, термины. Имена участников добавляются из карточки совещания сами", widget: "textarea" },
  ],
  diarization: [
    { name: "num_speakers", label: "Число говорящих", hint: "0 — автоматически; если в карточке совещания указаны участники — берётся их число", widget: "number" },
    { name: "threshold", label: "Порог кластеризации", hint: "Меньше — больше разных голосов; больше — голоса чаще сливаются", widget: "number", step: "0.05" },
    { name: "min_talk_seconds", label: "Мин. речь участника, с", hint: "«Голос» с меньшей суммарной речью — шум, отходит соседу", widget: "number", step: "0.5" },
  ],
  processing: [
    { name: "remind_days_before", label: "Напоминать за, дней", hint: "Поручение попадает в «Ближайшие сроки» и напоминания", widget: "number" },
    { name: "audio_retention_days", label: "Хранить аудио, дней", hint: "Потом исходная запись удаляется, протокол и стенограмма остаются. 0 — бессрочно", widget: "number" },
  ],
  integrations: [
    { widget: "header", label: "Zoom", hint: "Server-to-Server OAuth; запись приходит по вебхуку recording.completed. Секрет — ZOOM_CLIENT_SECRET" },
    { name: "zoom_enabled", label: "Включить", widget: "switch" },
    { name: "zoom_account_id", label: "Account ID", widget: "text" },
    { name: "zoom_client_id", label: "Client ID", widget: "text" },
    { widget: "header", label: "Microsoft Teams", hint: "Приложение в Entra ID, Graph API callRecords. Секрет — TEAMS_CLIENT_SECRET" },
    { name: "teams_enabled", label: "Включить", widget: "switch" },
    { name: "teams_tenant_id", label: "Tenant ID", widget: "text" },
    { name: "teams_client_id", label: "Client ID", widget: "text" },
    { widget: "header", label: "Google Meet", hint: "Сервисный аккаунт с доступом к записям в Drive. Ключ — файл MEET_KEY_FILE" },
    { name: "meet_enabled", label: "Включить", widget: "switch" },
    { name: "meet_service_account", label: "Сервисный аккаунт", widget: "text", placeholder: "protocol@project.iam.gserviceaccount.com" },
    { widget: "header", label: "СЭД", hint: "Выгрузка утверждённого протокола. Ключ — SED_API_KEY" },
    { name: "sed_enabled", label: "Включить", widget: "switch" },
    { name: "sed_url", label: "Адрес API", widget: "text", placeholder: "https://sed.company.kz/api" },
  ],
};

function fieldHtml(section, f, value, meta) {
  const id = `f-${section}-${f.name}`;
  let input;
  if (f.widget === "seg") {
    input = `<span class="seg-choice">${f.options.map(([v, l]) => `<label><input type="radio" name="${id}" value="${esc(v)}"
      ${String(value) === v ? "checked" : ""}><span>${esc(l)}</span></label>`).join("")}</span>`;
  } else if (f.widget === "switch") {
    input = `<label class="switch"><input type="checkbox" id="${id}" ${value ? "checked" : ""}> ${value ? "включено" : "выключено"}</label>`;
  } else if (f.widget === "select") {
    input = `<select id="${id}">${f.options.map(([v, l]) => `<option value="${esc(v)}" ${value === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  } else if (f.widget === "textarea") {
    input = `<textarea id="${id}" rows="3">${esc(value)}</textarea>`;
  } else {
    input = `<input type="${f.widget === "number" ? "number" : "text"}" id="${id}" value="${esc(value)}"
      ${f.step ? `step="${f.step}"` : ""} placeholder="${esc(f.placeholder || "")}">`;
  }
  return `<label for="${id}">${esc(f.label)}${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</label>
    <div class="field">${input}<div class="src">${esc(SOURCE[meta?.source] || "")}${meta?.env ? ` · ${esc(meta.env)}` : ""}</div>
    <div class="err" id="${id}-err"></div></div>`;
}

function readField(section, f) {
  const id = `f-${section}-${f.name}`;
  if (f.widget === "seg") return document.querySelector(`input[name="${id}"]:checked`)?.value ?? "";
  if (f.widget === "switch") return document.getElementById(id).checked;
  return document.getElementById(id).value;
}

const SECRET_LABELS = {
  NVIDIA_API_KEY: ["Ключ NVIDIA", "build.nvidia.com → модель → Get API Key, вида nvapi-…"],
  OPENAI_API_KEY: ["Ключ OpenAI", "platform.openai.com → API keys, вида sk-…; им же пользуется внешнее распознавание"],
  VLLM_API_KEY: ["Ключ vLLM", "если сервер запущен с --api-key"],
  OLLAMA_API_KEY: ["Ключ Ollama", "обычно не нужен"],
  LLM_API_KEY: ["Ключ LLM", ""],
  SMTP_PASSWORD: ["Пароль SMTP", "пароль учётной записи из поля «Логин»"],
  ZOOM_CLIENT_SECRET: ["Zoom Client Secret", ""],
  TEAMS_CLIENT_SECRET: ["Teams Client Secret", ""],
  MEET_KEY_FILE: ["Google Meet: ключ сервисного аккаунта", "содержимое JSON одной строкой"],
  SED_API_KEY: ["Ключ API СЭД", ""],
};

// Поле секрета — только запись: значение уходит на сервер, обратно приходит лишь «задан, …ab12».
function secretsBlock(section, data) {
  let names = Object.keys(data.secrets[section] || {});
  if (section === "llm") {
    const provider = data.values.llm.provider;
    const keyFor = { nvidia: "NVIDIA_API_KEY", openai: "OPENAI_API_KEY", vllm: "VLLM_API_KEY", ollama: "OLLAMA_API_KEY" };
    // сначала ключ активного провайдера, затем облачные — их чаще всего и вставляют
    names = [...new Set([keyFor[provider], "NVIDIA_API_KEY", "OPENAI_API_KEY"].filter(Boolean))];
  }
  if (!names.length) return "";
  return `<div class="form">${names.map((name) => {
    const st = data.secrets[section][name] || {};
    const [label, hint] = SECRET_LABELS[name] || [name, ""];
    const state = !st.set ? '<span class="tag">не задан</span>'
      : !st.usable ? `<span class="tag warn">задан ${esc(st.hint)}, но привязан к ${esc(st.bound_host)} — для текущего адреса не используется</span>`
      : `<span class="tag ok">задан ${esc(st.hint)}</span> <span class="muted" style="font-size:12px">${st.source === ".env" ? "из backend/.env" : "введён здесь" + (st.bound_host ? ", только для " + esc(st.bound_host) : "")}</span>`;
    return `<label>${esc(label)}<small>${esc(hint)}</small></label>
      <div class="field" data-secret="${name}">
        <div style="margin-bottom:6px">${state}</div>
        <input type="password" autocomplete="new-password" spellcheck="false" placeholder="${st.set ? "вставьте новый, чтобы заменить" : "вставьте ключ"}" style="width:100%;max-width:520px">
        <div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" data-act="save">Сохранить ключ</button>
          ${st.source === "интерфейс" ? '<button type="button" class="ghost" data-act="clear">Удалить</button>' : ""}
          <span class="muted" data-msg></span>
        </div>
        <div class="src">Хранится зашифрованным и больше не показывается; <code>${name}</code></div>
      </div>`;
  }).join("")}</div>`;
}

function wireSecrets(root, refresh) {
  root.querySelectorAll("[data-secret]").forEach((box) => {
    const name = box.dataset.secret;
    const input = box.querySelector("input");
    const msg = box.querySelector("[data-msg]");
    const run = async (method) => {
      msg.textContent = "…";
      const r = await fetch(`/api/secrets/${name}`, { method, headers: { "Content-Type": "application/json" },
        body: method === "PUT" ? JSON.stringify({ value: input.value }) : undefined });
      input.value = "";  // значение не держим в странице дольше необходимого
      if (!r.ok) { msg.textContent = (await r.json().catch(() => ({}))).detail || r.statusText; return; }
      refresh();
    };
    box.querySelector('[data-act="save"]').onclick = () => (input.value.trim() ? run("PUT") : (msg.textContent = "Вставьте ключ"));
    box.querySelector('[data-act="clear"]')?.addEventListener("click", () => run("DELETE"));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); box.querySelector('[data-act="save"]').click(); } });
  });
}

function renderForm(section, data, onSaved) {
  const root = document.getElementById(`form-${section}`);
  if (!root) return;
  const fields = FORMS[section];
  const values = data.values[section];
  const secrets = data.secrets[section];
  const body = fields.map((f) => f.widget === "header"
    ? `<div style="grid-column:1/-1;margin-top:6px"><b>${esc(f.label)}</b><div class="muted" style="font-size:12px">${esc(f.hint || "")}</div></div>`
    : fieldHtml(section, f, values[f.name], data.fields[section][f.name])).join("");
  root.innerHTML = `<form class="form" id="frm-${section}">${body}
    <div class="actions"><button type="submit">Сохранить</button>
      <button type="button" class="ghost" id="rst-${section}" title="Убрать значения, заданные здесь, — вернуться к backend/.env">Сбросить к .env</button>
      <span class="muted" id="msg-${section}"></span></div></form>${secretsBlock(section, data)}`;
  wireSecrets(root, () => api("/api/settings").then((fresh) => { renderForm(section, fresh, onSaved); if (onSaved) onSaved(fresh); }));

  const submit = async (payload) => {
    const msg = document.getElementById(`msg-${section}`);
    root.querySelectorAll(".err").forEach((e) => { e.textContent = ""; });
    try {
      const r = await fetch(`/api/settings/${section}`, { method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload) });
      const j = await r.json();
      if (!r.ok) {
        const errors = j.detail?.errors || {};
        Object.entries(errors).forEach(([k, v]) => { const e = document.getElementById(`f-${section}-${k}-err`); if (e) e.textContent = v; });
        msg.textContent = Object.keys(errors).length ? "Исправьте поля" : (j.detail || r.statusText);
        return;
      }
      const fresh = await api("/api/settings");
      renderForm(section, fresh, onSaved);
      document.getElementById(`msg-${section}`).textContent = "Сохранено ✓";
      if (onSaved) onSaved(fresh);
    } catch (err) { msg.textContent = err.message; }
  };
  document.getElementById(`frm-${section}`).onsubmit = (e) => {
    e.preventDefault();
    submit(Object.fromEntries(fields.filter((f) => f.name).map((f) => [f.name, readField(section, f)])));
  };
  document.getElementById(`rst-${section}`).onclick = () =>
    submit(Object.fromEntries(fields.filter((f) => f.name).map((f) => [f.name, ""])));
  // Тема применяется сразу при выборе, до сохранения — чтобы было видно, что выбираешь.
  if (section === "appearance") {
    root.querySelectorAll("input").forEach((el) => el.addEventListener("change", () =>
      applyAppearance(Object.fromEntries(fields.filter((f) => f.name && f.widget !== "text").map((f) => [f.name, readField(section, f)])))));
  }
}

function storeAppearance(a) {
  try { localStorage.setItem("socbrain.appearance", JSON.stringify(a)); } catch (e) { /* приватный режим */ }
  if (window.applyAppearance) applyAppearance(a);
}

function presetEnv(p) {
  const lines = [`LLM_PROVIDER=${p.id}`];
  if (p.model) lines.push(`LLM_MODEL=${p.model}`);
  if (p.id === "ollama" || p.id === "vllm") lines.push(`LLM_BASE_URL=${p.base_url}`);
  if (p.external) lines.push(`${p.key_env}=${p.id === "nvidia" ? "nvapi-…" : "…"}`);
  return lines.join("\n");
}

async function renderChecks(data, cfg) {
  const mark = { ok: '<span class="tag ok">в порядке</span>', warn: '<span class="tag warn">стоит поправить</span>',
                 bad: '<span class="tag bad">опасно</span>' };
  const llm = data.values.llm;
  const llmKeyEnv = { nvidia: "NVIDIA_API_KEY", openai: "OPENAI_API_KEY" }[llm.provider];
  const checks = [
    ["Вход в систему и роли", "bad", "не реализованы — любой в сети видит протоколы и поручения", "usr-users"],
    ["Распознавание речи локальное", cfg.stt_external ? "bad" : "ok",
      cfg.stt_external ? "аудио уходит в OpenAI — по ТЗ запрещено" : "аудио не покидает сервер", "proc-asr"],
    ["Анализ стенограммы в контуре", llm.provider === "none" ? "warn" : cfg.llm_external ? "bad" : "ok",
      llm.provider === "none" ? "LLM отключена — поручения только по шаблонам"
        : cfg.llm_external ? `текст стенограммы уходит во внешний API (${llm.provider}) — только для разработки` : "LLM в своей сети", "int-ai"],
    ...(cfg.llm_external && llmKeyEnv ? [["Ключ LLM задан", data.secrets.llm[llmKeyEnv]?.usable ? "ok" : "bad",
      data.secrets.llm[llmKeyEnv]?.usable ? `${llmKeyEnv} ${data.secrets.llm[llmKeyEnv].hint}`
        : `нет ключа ${llmKeyEnv} — вставьте его в разделе «Распознавание речи и ИИ»`, "int-ai"]] : []),
    ["Соединение защищено (HTTPS)", location.protocol === "https:" ? "ok" : "warn",
      location.protocol === "https:" ? "" : "страница открыта по HTTP — протоколы идут по сети открытым текстом", null],
    ["Почта подключена", data.values.mail.host ? "ok" : "warn",
      data.values.mail.host ? data.values.mail.host : "нет SMTP — не будет рассылки поручений и напоминаний", "int-mail"],
    ["Срок хранения аудио задан", data.values.processing.audio_retention_days > 0 ? "ok" : "warn",
      data.values.processing.audio_retention_days > 0 ? `${data.values.processing.audio_retention_days} дн.` : "записи хранятся бессрочно", "proc-retention"],
  ];
  const order = { bad: 0, warn: 1, ok: 2 };
  checks.sort((a, b) => order[a[1]] - order[b[1]]);
  const n = (s) => checks.filter((c) => c[1] === s).length;
  document.getElementById("checks").innerHTML = `<div class="scroll"><table>
    <tr><th class="wrap">Проверка</th><th>Состояние</th><th class="wrap">Что это значит</th></tr>
    ${checks.map(([t, s, why, tab]) => `<tr><td>${tab ? `<a href="#${tab}">${esc(t)}</a>` : esc(t)}</td><td>${mark[s]}</td>
      <td class="wrap muted">${esc(why)}</td></tr>`).join("")}</table></div>
    <p class="sub">Итого: ${checks.length} проверок · ${n("bad")} опасно · ${n("warn")} стоит поправить · ${n("ok")} в порядке.</p>`;
}

async function renderAi() {
  const [cfg, llmInfo] = await Promise.all([api("/api/config"), api("/api/llm/providers")]);
  const active = llmInfo.presets.find((p) => p.id === llmInfo.active) || {};
  document.getElementById("ai-models").innerHTML = `<div class="scroll"><table>
    <tr><th class="wrap">Модель</th><th>Назначение</th><th>Расположение</th></tr>
    <tr><td>${cfg.stt_external ? "OpenAI Whisper API" : "faster-whisper " + esc(cfg.whisper_model)}</td>
        <td>распознавание речи (STT)</td><td>${placeTag(cfg.stt_external)}</td></tr>
    <tr><td>sherpa-onnx: pyannote-3.0 + 3D-Speaker</td><td>диаризация — кто говорит</td><td>${placeTag(false)}</td></tr>
    <tr><td>${esc(llmInfo.active_model || "—")} <span class="muted">(${esc(active.title || llmInfo.active)})</span></td>
        <td>анализ стенограммы: поручения, саммари</td>
        <td>${llmInfo.active === "none" ? '<span class="tag">отключена</span>' : placeTag(llmInfo.active_external)}</td></tr>
  </table></div>`;

  document.getElementById("ai-llm").innerHTML = `<div class="scroll"><table>
    <tr><td>Действует сейчас</td><td><b>${esc(active.title || llmInfo.active)}</b> · <code>${esc(llmInfo.active_model || "—")}</code></td></tr>
    <tr><td>Адрес</td><td><code>${esc(llmInfo.active_base_url)}</code> ${placeTag(llmInfo.active_external)}</td></tr>
    <tr><td>Ключ</td><td>${llmInfo.active_external && active.key_env
      ? (active.key_set ? `<span class="tag ok">задан</span> <code>${esc(active.key_env)}</code>`
                        : `<span class="tag bad">не задан</span> вставьте ключ в поле ниже`)
      : '<span class="tag">не требуется</span>'}</td></tr>
  </table></div>`;

  document.getElementById("ai-presets").innerHTML = `<div class="grid2">${llmInfo.presets.map((p) => `
    <div class="card">
      <div class="n" style="font-size:17px">${esc(p.title)} ${p.id === llmInfo.active ? '<span class="tag ok">активен</span>' : ""}</div>
      <div class="l">${placeTag(p.external)} ${p.external ? (p.key_set ? '<span class="tag ok">ключ задан</span>' : '<span class="tag">ключ не задан</span>') : ""}</div>
      <p class="sub" style="margin:8px 0">${esc(p.note)}${p.docs ? ` <a href="${esc(p.docs)}" target="_blank" rel="noopener">документация</a>` : ""}</p>
      <pre style="margin:0 0 10px">${esc(presetEnv(p))}</pre>
      ${p.id === llmInfo.active ? "" : `<button type="button" class="ghost" onclick="usePreset('${p.id}')">Использовать</button>`}
    </div>`).join("")}</div>`;
  return llmInfo;
}

async function usePreset(id) {
  await api("/api/settings/llm", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: id, model: "", base_url: "" }) });
  pageSettings();
}

function wireChecks() {
  document.getElementById("ai-check").onclick = async () => {
    const msg = document.getElementById("ai-check-msg");
    const out = document.getElementById("ai-check-result");
    msg.textContent = "Проверяю…"; out.innerHTML = "";
    try {
      const r = await api("/api/llm/check", { method: "POST" });
      const ok = r.reachable && r.structured_ok;
      msg.textContent = "";
      const mark = (v) => v === null ? '<span class="tag">—</span>' : v ? '<span class="tag ok">да</span>' : '<span class="tag bad">нет</span>';
      out.innerHTML = `<div class="note ${ok ? "ok" : "bad"}">${ok ? "Подключение работает: модель отвечает по JSON-схеме." : esc(r.error || "Подключение не работает")}</div>
        <div class="scroll"><table>
          <tr><td>Сервер отвечает</td><td>${mark(r.reachable)}</td></tr>
          <tr><td>Модель <code>${esc(r.model)}</code> есть в списке провайдера</td><td>${mark(r.model_listed)}</td></tr>
          <tr><td>Структурированный ответ (пробный синтетический запрос)</td><td>${mark(r.structured_ok)}</td></tr>
        </table></div>
        ${r.models.length ? `<details style="margin-top:10px"><summary class="muted">Доступные модели (${r.models.length})</summary>
          <pre>${esc(r.models.join("\n"))}</pre></details>` : ""}`;
    } catch (err) { msg.textContent = err.message; }
  };
  document.getElementById("mail-check").onclick = async () => {
    const msg = document.getElementById("mail-check-msg");
    msg.textContent = "Проверяю…";
    const r = await api("/api/settings/mail/check", { method: "POST" }).catch((e) => ({ ok: false, steps: [], error: e.message }));
    msg.textContent = "";
    document.getElementById("mail-check-result").innerHTML = `<div class="note ${r.ok ? "ok" : "bad"}">
      ${r.ok ? "Сервер принял подключение" : esc(r.error)}${r.steps.length ? ` · ${r.steps.map(esc).join(" → ")}` : ""}. Письмо не отправлялось.</div>`;
  };
}

function openTabFromHash() {
  const tab = location.hash && document.querySelector(`[data-tab-target="${location.hash.slice(1)}"]`);
  if (tab) tab.click();
}

async function pageSettings() {
  openTabFromHash();
  window.onhashchange = openTabFromHash;
  const [data, cfg] = await Promise.all([api("/api/settings"), api("/api/config")]);
  const llmInfo = await renderAi();
  FORMS.llm[0].options = llmInfo.presets.map((p) => [p.id, `${p.title}${p.external ? " — облако" : ""}`]);
  const refresh = async () => { const [d, c] = await Promise.all([api("/api/settings"), api("/api/config")]); renderChecks(d, c); };
  for (const section of Object.keys(FORMS)) {
    renderForm(section, data, async (fresh) => {
      if (section === "appearance") storeAppearance(fresh.values.appearance);
      if (section === "llm" || section === "stt") { await renderAi(); privacyBanner(true); }
      refresh();
    });
  }
  renderChecks(data, cfg);
  wireChecks();
}

const PAGES = { dashboard: pageDashboard, meetings: pageMeetings, meeting: pageMeeting, tasks: pageTasks,
                settings: pageSettings };
document.addEventListener("DOMContentLoaded", () => {
  // Внешний вид по умолчанию — с сервера; theme.js уже применил сохранённый, здесь — обновить.
  api("/api/config").then((c) => c.appearance && storeAppearance(c.appearance)).catch(() => {});
  const page = PAGES[document.body.dataset.page];
  if (!page) return;
  privacyBanner();
  page().catch((err) => document.querySelector("main").insertAdjacentHTML("beforeend",
    `<div class="note bad">Бэкенд недоступен: ${esc(err.message)}. Запустите docker compose up (см. README).</div>`));
});
