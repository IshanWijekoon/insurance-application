const TOKEN_KEY = "aiclaims.access";

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
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401 && !path.includes("/auth/")) {
    try {
      const refreshed = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
      if (refreshed.ok) {
        const body = await refreshed.json();
        setToken(body.access_token);
        headers.set("Authorization", `Bearer ${body.access_token}`);
        return parse(await fetch(path, { ...init, headers, credentials: "include" }));
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
