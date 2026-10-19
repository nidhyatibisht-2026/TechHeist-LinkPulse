// Thin fetch wrapper: attaches the token, parses JSON, and turns API errors into readable messages.
export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "linkpulse.token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function messageFrom(body, status) {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  if (Array.isArray(d) && d[0]?.msg) {
    const field = d[0].loc?.slice(1).join(".");
    return field ? `${field}: ${d[0].msg.replace(/^Value error, /, "")}` : d[0].msg;
  }
  return status >= 500 ? "Something went wrong on the server. Try again." : `Request failed (${status}).`;
}

export async function api(path, { method = "GET", body, form, raw } = {}) {
  const headers = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is the backend running?`, 0, null);
  }
  if (res.status === 401 && token) {
    tokenStore.clear();
    window.dispatchEvent(new Event("linkpulse:logout"));
  }
  if (raw && res.ok) return res;
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new ApiError(messageFrom(data, res.status), res.status, data);
  return data;
}

// Images and downloads need the auth header, so fetch them as blobs.
export async function blobUrl(path) {
  const res = await api(path, { raw: true });
  return URL.createObjectURL(await res.blob());
}

export async function download(path, filename) {
  const url = await blobUrl(path);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
