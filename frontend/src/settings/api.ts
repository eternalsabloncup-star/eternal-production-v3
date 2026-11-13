/** Isolated adapter: no automatic runtime mounting, token storage or navigation. */
export interface SettingsApi {
  request<T>(path: string, body?: unknown, method?: string): Promise<T>;
}
export function createSettingsApi(base: string, token: () => string): SettingsApi {
  return {
    async request<T>(path: string, body?: unknown, method?: string): Promise<T> {
      const response = await fetch(`${base}/settings${path}`, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}` },
        cache: "no-store", credentials: "same-origin",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail && typeof data.detail === "string"
        ? data.detail : data?.error?.message || `Permintaan ditolak (${response.status})`);
      if (data === null) throw new Error("Respons API tidak valid");
      return data as T;
    },
  };
}
