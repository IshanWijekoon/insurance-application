const TOKEN_KEY = "aiclaims.access";

/** Absolute API origin when frontend and API are on different hosts (Railway). Empty = same-origin / Next rewrite. */
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${API_BASE}${path}`;
}

export function wsUrl(path: string): string {
  const base = API_BASE;
  if (base) {
    const u = new URL(base);
    const proto = u.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${u.host}${path}`;
  }
  const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
  const host = typeof window !== "undefined" ? window.location.host : "localhost:3000";
  return `${proto}://${host}${path}`;
}

export function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, string> = {},
  ) {
    super(message);
  }

  fieldMessages(): string[] {
    return Object.entries(this.details).map(([field, msg]) => {
      const name = field.replace(/_/g, " ");
      const cleaned = msg.replace(/^Value error,\s*/i, "").replace(/^String should /i, "should ");
      return `${name}: ${cleaned}`;
    });
  }

  displayMessage(): string {
    const fields = this.fieldMessages();
    if (fields.length === 1) return fields[0];
    if (fields.length > 1) return fields.join(" ");
    return this.message;
  }
}

async function parse(res: Response) {
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code || "ERROR", err.message || res.statusText, err.details || {});
  }
  return data;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const url = apiUrl(path);
  const res = await fetch(url, { ...init, headers, credentials: "include" });
  if (res.status === 401 && !path.includes("/auth/")) {
    try {
      const refreshed = await fetch(apiUrl("/api/v1/auth/refresh"), { method: "POST", credentials: "include" });
      if (refreshed.ok) {
        const body = await refreshed.json();
        setToken(body.access_token);
        headers.set("Authorization", `Bearer ${body.access_token}`);
        return parse(await fetch(url, { ...init, headers, credentials: "include" }));
      }
    } catch {
      clearToken();
    }
  }
  return parse(res);
}

export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) });
export const patch = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
