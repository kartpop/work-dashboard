export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010";

// Session cookie flows on every request (goal 8). In dev the frontend (:5173) and
// backend (:8010) are the same site (localhost), so the SameSite=Lax cookie is sent;
// in prod they share an origin. `credentials: "include"` is required for both.
const CREDENTIALS: RequestCredentials = "include";

// A 401 anywhere means the session lapsed — the AuthProvider registers a handler here
// to flip the whole app back to the sign-in screen instead of each panel guessing.
let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn;
}

export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(response: Response, path: string): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    const body = (await response.json().catch(() => null)) as {
      error?: { message?: string };
    } | null;
    throw new HttpError(
      response.status,
      body?.error?.message ?? `${path} failed with status ${response.status}`,
    );
  }
  return (await response.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE_URL}${path}`, { credentials: CREDENTIALS }),
    path,
  );
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE_URL}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: CREDENTIALS,
      body: JSON.stringify(body),
    }),
    path,
  );
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: CREDENTIALS,
      body: JSON.stringify(body),
    }),
    path,
  );
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE_URL}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: CREDENTIALS,
      body: JSON.stringify(body),
    }),
    path,
  );
}

export async function apiDelete<T>(path: string): Promise<T> {
  return handle<T>(
    await fetch(`${API_BASE_URL}${path}`, {
      method: "DELETE",
      credentials: CREDENTIALS,
    }),
    path,
  );
}
