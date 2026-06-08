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
