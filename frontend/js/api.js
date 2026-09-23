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
  const c = await api("/api/config").catch(() => null);
  if (!c || !(c.llm_external || c.stt_external)) return;
  const what = [c.stt_external && "аудио (распознавание)", c.llm_external && `текст стенограммы (LLM: ${c.llm_provider})`]
    .filter(Boolean).join(" и ");
  document.querySelector("main").insertAdjacentHTML("afterbegin",
    `<div class="note warn">Режим разработки: ${what} отправляется во внешний API. ` +
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

const PAGES = { dashboard: pageDashboard, meetings: pageMeetings, meeting: pageMeeting, tasks: pageTasks };
document.addEventListener("DOMContentLoaded", () => {
  const page = PAGES[document.body.dataset.page];
  if (!page) return;
  privacyBanner();
  page().catch((err) => document.querySelector("main").insertAdjacentHTML("beforeend",
    `<div class="note bad">Бэкенд недоступен: ${esc(err.message)}. Запустите docker compose up (см. README).</div>`));
});
