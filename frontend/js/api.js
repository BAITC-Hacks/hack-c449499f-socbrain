// SOCBrain — тонкий клиент к backend/app/main.py.
// Порт зависит от того, что было свободно при запуске uvicorn —
// поменяй здесь, если у тебя не 8001.
const API_BASE = "http://127.0.0.1:8001";

function getToken() {
  return sessionStorage.getItem("socbrain_token");
}

function setSession(token, name) {
  sessionStorage.setItem("socbrain_token", token);
  sessionStorage.setItem("socbrain_name", name);
}

function clearSession() {
  sessionStorage.removeItem("socbrain_token");
  sessionStorage.removeItem("socbrain_name");
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, Object.assign({}, options, { headers }));
  const isJson = (res.headers.get("content-type") || "").includes("application/json");
  const data = isJson ? await res.json() : null;

  if (!res.ok) {
    const message = (data && data.detail) || `Ошибка ${res.status}`;
    throw new Error(message);
  }
  return data;
}

async function apiLogin(login, password) {
  const data = await apiFetch("/api/login", {
    method: "POST",
    body: JSON.stringify({ login, password }),
  });
  setSession(data.token, data.name);
  return data;
}

async function apiLogout() {
  try {
    await apiFetch("/api/logout", { method: "POST" });
  } catch (e) {
    // сессия могла уже истечь — выходим локально в любом случае
  }
  clearSession();
}
