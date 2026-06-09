const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(body?.error?.message ?? `${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const err = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(err?.error?.message ?? `${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const err = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(err?.error?.message ?? `${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "DELETE" });
  if (!response.ok) {
    const err = (await response.json().catch(() => null)) as
      | { error?: { message?: string } }
      | null;
    throw new Error(err?.error?.message ?? `${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
